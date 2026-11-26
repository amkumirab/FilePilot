import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from filepilot.engine import execute, history, preview_undo, undo
from filepilot.paths import FilePilotError
from filepilot.quarantine import plan_quarantine


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.keep = self.root / "original.jpg"
        self.copy = self.root / "نسخه‌ها" / "copy.jpg"
        self.copy.parent.mkdir()
        self.keep.write_bytes(b"same")
        self.copy.write_bytes(b"same")
        self.relative = self.copy.relative_to(self.root).as_posix()
        self.destination = self.root / ".filepilot-quarantine" / self.relative

    def plan(self):
        return plan_quarantine(self.root, self.keep.name, [self.relative])

    def apply(self):
        plan, keeper, hashes = self.plan()
        return execute(plan, keeper=keeper, hashes=hashes)

    def command(self, *args):
        result = subprocess.run(
            [sys.executable, "-m", "filepilot", *map(str, args)],
            capture_output=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_cli_preview_apply_history_and_undo_keep_unselected_copies(self):
        extra = self.root / "extra.jpg"
        extra.write_bytes(b"same")
        args = ("quarantine", self.root, "--keep", self.keep.name, "--move", self.relative)
        preview = self.command(*args, "--json")
        self.assertTrue(preview["preview"])
        self.assertFalse((self.root / ".filepilot").exists())
        self.assertFalse(self.destination.exists())
        run = self.command(*args, "--apply", "--json")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(self.destination.read_bytes(), b"same")
        self.assertFalse(self.copy.exists())
        self.assertEqual(self.keep.read_bytes(), b"same")
        self.assertEqual(extra.read_bytes(), b"same")
        self.assertEqual(history(self.root)[0]["id"], run["id"])
        self.assertEqual(preview_undo(self.root, run["id"])[0]["target"], self.relative)
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")
        self.assertEqual(self.copy.read_bytes(), b"same")

    def test_same_size_different_content_refuses_entire_selection(self):
        other = self.root / "different.jpg"
        other.write_bytes(b"diff")
        with self.assertRaisesRegex(FilePilotError, "content changed"):
            plan_quarantine(self.root, self.keep.name, [self.relative, other.name])
        self.assertTrue(self.copy.exists())
        self.assertFalse(self.destination.exists())

    def test_keep_content_is_rechecked_under_lock(self):
        plan, keeper, hashes = self.plan()
        stamp = self.keep.stat()
        self.keep.write_bytes(b"diff")
        os.utime(self.keep, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with self.assertRaisesRegex(FilePilotError, "Kept file changed"):
            execute(plan, keeper=keeper, hashes=hashes)
        self.assertEqual(history(self.root), [])
        self.assertTrue(self.copy.exists())

    def test_existing_quarantine_destination_is_preserved(self):
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(b"existing")
        with self.assertRaisesRegex(FilePilotError, "occupied"):
            self.apply()
        self.assertEqual(self.destination.read_bytes(), b"existing")
        self.assertEqual(self.copy.read_bytes(), b"same")

    def test_undo_preserves_new_file_at_original_path(self):
        run = self.apply()
        self.copy.write_bytes(b"replacement")
        self.assertEqual(undo(self.root, run["id"])["status"], "undo_partial")
        self.assertEqual(self.copy.read_bytes(), b"replacement")
        self.assertEqual(self.destination.read_bytes(), b"same")
        self.copy.unlink()
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")

    def test_rejects_unsafe_paths_and_hard_link_aliases(self):
        alias = self.root / "alias.jpg"
        os.link(self.keep, alias)
        for source in ("../outside", ".filepilot/runs/record.json", self.keep.name, alias.name):
            with self.subTest(source=source), self.assertRaises(FilePilotError):
                plan_quarantine(self.root, self.keep.name, [source])
        self.assertFalse((self.root / ".filepilot-quarantine").exists())

    def test_journal_cannot_redirect_quarantine_undo(self):
        run = self.apply()
        record = self.root / ".filepilot" / "runs" / f"{run['id']}.json"
        run["entries"][0]["target"] = "somewhere/copy.jpg"
        record.write_text(json.dumps(run), encoding="utf-8")
        with self.assertRaises(FilePilotError):
            undo(self.root, run["id"])
        self.assertTrue(self.destination.exists())
