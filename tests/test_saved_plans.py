import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filepilot.engine import validate_plan
from filepilot.paths import FilePilotError
from filepilot.planner import build_plan
from filepilot.saved_plans import load_plan, save_plan


class SavedPlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.root = self.work / "inbox با فاصله"
        self.root.mkdir()
        (self.root / "a.pdf").write_bytes(b"first")
        (self.root / "b.pdf").write_bytes(b"second")
        self.output = self.work / "plan.json"

    def snapshot(self):
        return save_plan(build_plan(self.root), self.output)

    def write(self, document):
        self.output.write_text(json.dumps(document), encoding="utf-8")

    def test_round_trip_preserves_exact_order_metadata_and_hashes(self):
        plan = build_plan(self.root)
        saved = save_plan(plan, self.output)
        loaded = load_plan(self.output)
        self.assertEqual(saved, loaded)
        self.assertEqual(loaded.plan, plan)
        self.assertEqual(loaded.hashes[0], hashlib.sha256(b"first").hexdigest())
        self.assertEqual(validate_plan(loaded.plan, loaded.hashes), loaded.hashes)
        document = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(document["format"], "filepilot-plan")
        self.assertEqual(document["version"], 1)
        self.assertEqual(document["moves"][1]["source"], "b.pdf")
        self.assertEqual({p.name for p in self.root.iterdir()}, {"a.pdf", "b.pdf"})

    def test_existing_plan_is_never_overwritten(self):
        self.snapshot()
        before = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            save_plan(build_plan(self.root), self.output)
        self.assertEqual(self.output.read_bytes(), before)

    def test_plan_cannot_be_written_over_a_source_target_or_history(self):
        plan = build_plan(self.root)
        for relative in ("a.pdf", "Documents", "Documents/a.pdf", ".filepilot/plan.json"):
            with self.subTest(relative=relative), self.assertRaises(FilePilotError):
                save_plan(plan, self.root / relative)
        self.assertFalse((self.root / "Documents").exists())
        self.assertFalse((self.root / ".filepilot").exists())

    def test_hashing_detects_a_file_changed_during_snapshot(self):
        from filepilot.engine import _digest

        def changed(path):
            digest = _digest(path)
            path.write_bytes(b"changed during hashing")
            return digest

        with (
            patch("filepilot.engine._digest", side_effect=changed),
            self.assertRaisesRegex(FilePilotError, "changed"),
        ):
            self.snapshot()
        self.assertFalse(self.output.exists())

    def test_empty_plan_and_skipped_unicode_file_round_trip(self):
        for path in self.root.iterdir():
            path.unlink()
        (self.root / "یادداشت.xyz").write_bytes(b"unknown")
        saved = self.snapshot()
        self.assertEqual(load_plan(self.output), saved)
        self.assertEqual(saved.hashes, ())
        self.assertEqual(saved.plan.skipped[0].source, "یادداشت.xyz")

    def test_invalid_schema_is_rejected(self):
        self.snapshot()
        valid = json.loads(self.output.read_text())
        invalid = [
            None,
            [],
            {},
            {**valid, "format": "other"},
            {**valid, "version": 2},
            {**valid, "version": True},
            {**valid, "extra": 0},
            {**valid, "root": 42},
            {**valid, "root": "relative"},
            {**valid, "moves": {}},
            {**valid, "skipped": {}},
            {**valid, "moves": [None]},
            {**valid, "skipped": [None]},
            {**valid, "skipped": [{"source": 2, "reason": "x"}]},
            {**valid, "skipped": [{"source": "x", "reason": 2}]},
        ]
        for key, value in (
            ("source", "nested/a.pdf"),
            ("source", "../outside"),
            ("target", "../outside.pdf"),
            ("target", "flat.pdf"),
            ("target", ".filepilot/runs/x.json"),
            ("rule", None),
            ("size", True),
            ("size", -1),
            ("modified_ns", "123"),
            ("modified_ns", False),
            ("sha256", None),
            ("sha256", "a"),
            ("sha256", "G" * 64),
        ):
            document = copy.deepcopy(valid)
            document["moves"][0][key] = value
            invalid.append(document)
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(FilePilotError):
                self.write(document)
                load_plan(self.output)

    def test_duplicate_and_conflicting_paths_are_rejected(self):
        self.snapshot()
        valid = json.loads(self.output.read_text())
        for key, value in (
            ("source", "A.pdf"),
            ("target", "documents/A.pdf"),
            ("target", "Documents/a.pdf/nested.pdf"),
        ):
            document = copy.deepcopy(valid)
            document["moves"][1][key] = value
            self.write(document)
            with self.subTest(key=key, value=value), self.assertRaises(FilePilotError):
                load_plan(self.output)

    def test_invalid_json_duplicate_keys_and_oversized_input_are_rejected(self):
        for content in (
            "{",
            '{"version":1,"version":1}',
            "[" * 2000,
            b"\xff",
            " " * (10 * 1024 * 1024 + 1),
        ):
            with self.subTest(size=len(content)), self.assertRaises(FilePilotError):
                self.output.write_bytes(content if isinstance(content, bytes) else content.encode())
                load_plan(self.output)

    def test_relocated_or_missing_root_is_rejected(self):
        self.snapshot()
        original = json.loads(self.output.read_text())
        for root in (str(self.root / "missing"), str(self.root / ".." / self.root.name)):
            self.write({**original, "root": root})
            with self.subTest(root=root), self.assertRaises((FilePilotError, OSError)):
                load_plan(self.output)

    def test_all_sources_are_checked_and_metadata_preserving_edits_are_detected(self):
        saved = self.snapshot()
        path = self.root / "b.pdf"
        info = path.stat()
        path.write_bytes(b"SECOND")
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        with self.assertRaisesRegex(FilePilotError, "content changed"):
            validate_plan(saved.plan, saved.hashes)
        self.assertTrue((self.root / "a.pdf").exists())
        self.assertFalse((self.root / ".filepilot").exists())

    def test_preflight_rejects_missing_changed_sources_and_invalid_hash_count(self):
        saved = self.snapshot()
        with self.assertRaises(FilePilotError):
            validate_plan(saved.plan, ())
        (self.root / "b.pdf").write_bytes(b"longer content")
        with self.assertRaisesRegex(FilePilotError, "changed"):
            validate_plan(saved.plan, saved.hashes)
        (self.root / "b.pdf").unlink()
        with self.assertRaises(OSError):
            validate_plan(saved.plan, saved.hashes)

    def test_preflight_refuses_occupied_targets_and_parent_files(self):
        saved = self.snapshot()
        (self.root / "Documents").write_bytes(b"occupied")
        with self.assertRaisesRegex(FilePilotError, "occupied"):
            validate_plan(saved.plan, saved.hashes)
        (self.root / "Documents").unlink()
        (self.root / "Documents").mkdir()
        (self.root / "Documents/B.PDF").write_bytes(b"existing")
        with self.assertRaisesRegex(FilePilotError, "occupied"):
            validate_plan(saved.plan, saved.hashes)

    def test_plan_location_cannot_be_a_destination_when_loading(self):
        self.snapshot()
        document = json.loads(self.output.read_text())
        (self.root / "Documents").mkdir()
        relocated = self.root / "Documents/a.pdf"
        relocated.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(FilePilotError):
            load_plan(relocated)


if __name__ == "__main__":
    unittest.main()
