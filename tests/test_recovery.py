"""Undo, interrupted operations, and preservation of recoverable data."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filepilot.engine import execute, history, preview_undo, undo
from filepilot.paths import FilePilotError
from filepilot.planner import build_plan


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def file(self, name="report.pdf", content=b"original"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_directory_replacing_organized_file_blocks_undo(self):
        self.file()
        execute(build_plan(self.root))
        target = self.root / "Documents/report.pdf"
        target.unlink()
        target.mkdir()
        result = undo(self.root)
        self.assertEqual(result["status"], "undo_partial")
        self.assertIn("Not a regular file", result["entries"][0]["error"])
        self.assertTrue(target.is_dir())
        self.assertFalse((self.root / "report.pdf").exists())

    def test_undo_twice_by_id_is_idempotent(self):
        self.file()
        run = execute(build_plan(self.root))
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")
        self.assertEqual((self.root / "report.pdf").read_bytes(), b"original")
        with self.assertRaises(FilePilotError):
            undo(self.root)

    def test_latest_undo_then_previous_undo_uses_distinct_runs(self):
        self.file("first.pdf", b"one")
        first = execute(build_plan(self.root))
        self.file("second.pdf", b"two")
        second = execute(build_plan(self.root))
        self.assertEqual(undo(self.root)["id"], second["id"])
        self.assertTrue((self.root / "second.pdf").exists())
        self.assertFalse((self.root / "first.pdf").exists())
        self.assertEqual(undo(self.root)["id"], first["id"])
        self.assertEqual(len(history(self.root)), 2)

    def test_missing_organized_file_blocks_undo_and_preview_is_read_only(self):
        self.file()
        run = execute(build_plan(self.root))
        (self.root / "Documents/report.pdf").unlink()
        journal = self.root / ".filepilot/runs" / f"{run['id']}.json"
        before = journal.read_bytes()
        preview = preview_undo(self.root)
        self.assertEqual(preview[0]["status"], "blocked")
        self.assertIn("missing", preview[0]["reason"])
        self.assertEqual(journal.read_bytes(), before)
        self.assertEqual(undo(self.root)["status"], "undo_partial")

    def test_undo_move_failure_is_retryable(self):
        self.file()
        execute(build_plan(self.root))
        with patch("filepilot.engine._move_no_replace", side_effect=PermissionError("locked")):
            run = undo(self.root)
        self.assertEqual(run["status"], "undo_partial")
        self.assertEqual((self.root / "Documents/report.pdf").read_bytes(), b"original")
        self.assertFalse((self.root / "report.pdf").exists())
        self.assertEqual(undo(self.root)["status"], "undone")

    def test_failed_undo_journal_write_never_moves_file(self):
        self.file()
        execute(build_plan(self.root))
        with (
            patch("filepilot.engine.save_run", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            undo(self.root)
        self.assertFalse((self.root / "report.pdf").exists())
        self.assertEqual((self.root / "Documents/report.pdf").read_bytes(), b"original")
        self.assertEqual(undo(self.root)["status"], "undone")

    def test_real_process_exit_after_move_is_recoverable(self):
        source = self.file()
        program = """
import os, sys
from pathlib import Path
import filepilot.engine as engine
from filepilot.planner import build_plan
original = engine._move_no_replace
def crash(source, target):
    original(source, target)
    os._exit(23)
engine._move_no_replace = crash
engine.execute(build_plan(Path(sys.argv[1])))
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(self.root)], capture_output=True, timeout=20
        )
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertFalse(source.exists())
        self.assertEqual(history(self.root)[0]["entries"][0]["status"], "pending")
        self.assertEqual(undo(self.root)["status"], "undone")
        self.assertEqual(source.read_bytes(), b"original")

    def test_pending_move_before_execution_is_safely_marked_undone(self):
        source = self.file()
        with (
            patch("filepilot.engine._move_no_replace", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            execute(build_plan(self.root))
        self.assertEqual(preview_undo(self.root)[0]["status"], "already in place")
        self.assertEqual(undo(self.root)["status"], "undone")
        self.assertEqual(source.read_bytes(), b"original")

    def test_ambiguous_link_interruption_preserves_both_copies(self):
        source = self.file()
        with (
            patch("filepilot.engine._move_no_replace", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            execute(build_plan(self.root))
        target = self.root / "Documents/report.pdf"
        os.link(source, target)
        self.assertEqual(undo(self.root)["status"], "undo_partial")
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual(target.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
