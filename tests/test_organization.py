"""Organization rules, file content, and destination collisions."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from filepilot.config import DEFAULT_RULES, Rule
from filepilot.engine import execute, undo
from filepilot.paths import FilePilotError
from filepilot.planner import build_plan


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def file(self, name="report.pdf", content=b"original"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_every_builtin_extension_has_its_expected_category(self):
        for rule in DEFAULT_RULES:
            for extension in rule.extensions:
                self.file(f"sample.{extension.upper()}")
        plan = build_plan(self.root)
        expected = {
            f"sample.{ext.upper()}": f"{rule.target}/sample.{ext.upper()}"
            for rule in DEFAULT_RULES
            for ext in rule.extensions
        }
        self.assertEqual({move.source: move.target for move in plan.moves}, expected)

    def test_numbering_skips_existing_files_and_directories(self):
        self.file()
        directory = self.root / "Documents"
        directory.mkdir()
        (directory / "report.pdf").write_bytes(b"existing")
        (directory / "report (2).pdf").mkdir()
        plan = build_plan(self.root)
        self.assertEqual(plan.moves[0].target, "Documents/report (3).pdf")
        run = execute(plan)
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")
        self.assertEqual((directory / "report.pdf").read_bytes(), b"existing")
        self.assertTrue((directory / "report (2).pdf").is_dir())

    def test_zero_byte_and_large_binary_files_round_trip(self):
        payloads = {"empty.pdf": b"", "large.zip": bytes(range(256)) * 65536 + b"end"}
        for name, contents in payloads.items():
            self.file(name, contents)
        run = execute(build_plan(self.root))
        for entry in run["entries"]:
            self.assertEqual(entry["sha256"], hashlib.sha256(payloads[entry["source"]]).hexdigest())
        self.assertEqual(undo(self.root)["status"], "undone")
        for name, contents in payloads.items():
            self.assertEqual((self.root / name).read_bytes(), contents)

    def test_custom_catchall_handles_extensionless_files_and_spaces(self):
        self.file("README", b"no extension")
        self.file("notes with spaces.txt")
        rules = (Rule("all", (), "My Files/{year}", rename="saved_{name}"),)
        run = execute(build_plan(self.root, rules))
        self.assertEqual(len(run["entries"]), 2)
        self.assertEqual(undo(self.root)["status"], "undone")
        self.assertEqual((self.root / "README").read_bytes(), b"no extension")
        self.assertTrue((self.root / "notes with spaces.txt").exists())

    def test_empty_rule_set_and_unmatched_files_stay_in_place(self):
        source = self.file()
        self.assertFalse(build_plan(self.root, ()).moves)
        self.assertEqual(list(self.root.iterdir()), [source])

    def test_file_occupying_target_directory_blocks_preview_without_changes(self):
        source = self.file()
        blocker = self.file("Documents", b"do not replace")
        with self.assertRaises(FilePilotError):
            build_plan(self.root)
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual(blocker.read_bytes(), b"do not replace")
        self.assertFalse((self.root / ".filepilot").exists())

    def test_deleted_source_is_reported_without_creating_destination(self):
        source = self.file()
        plan = build_plan(self.root)
        source.unlink()
        run = execute(plan)
        self.assertEqual(run["status"], "partial")
        self.assertFalse((self.root / "Documents/report.pdf").exists())

    def test_existing_state_file_blocks_execution_without_moving_data(self):
        source = self.file()
        self.file(".filepilot", b"occupied")
        with self.assertRaises(OSError):
            execute(build_plan(self.root))
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual((self.root / ".filepilot").read_bytes(), b"occupied")

    def test_dense_collision_dataset_round_trips_every_original_byte(self):
        originals = {}
        for number in range(96):
            name = f"document {number:03}.pdf"
            payload = hashlib.sha256(str(number).encode()).digest() * (number + 1)
            self.file(name, payload)
            originals[name] = payload
        directory = self.root / "Documents"
        directory.mkdir()
        for number in range(1, 9):
            name = "same.pdf" if number == 1 else f"same ({number}).pdf"
            (directory / name).write_bytes(b"sentinel")
        rules = (Rule("all", ("pdf",), "Documents", rename="same{ext}"),)
        plan = build_plan(self.root, rules)
        self.assertEqual(len({move.target.casefold() for move in plan.moves}), len(originals))
        run = execute(plan)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(undo(self.root)["status"], "undone")
        for name, payload in originals.items():
            self.assertEqual((self.root / name).read_bytes(), payload)
        self.assertEqual(len(list(directory.iterdir())), 8)
        for sentinel in directory.iterdir():
            self.assertEqual(sentinel.read_bytes(), b"sentinel")


if __name__ == "__main__":
    unittest.main()
