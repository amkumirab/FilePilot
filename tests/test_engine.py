import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filepilot.engine import execute, history, load_run, undo
from filepilot.paths import FilePilotError
from filepilot.planner import build_plan


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "report.pdf").write_bytes(b"original bytes")

    def organize(self):
        return execute(build_plan(self.root))

    def test_execute_and_undo_restore_original_bytes(self):
        run = self.organize()
        self.assertEqual(run["status"], "completed")
        self.assertFalse((self.root / "report.pdf").exists())
        self.assertEqual((self.root / "Documents/report.pdf").read_bytes(), b"original bytes")
        self.assertEqual(history(self.root)[0]["id"], run["id"])
        restored = undo(self.root, run["id"])
        self.assertEqual(restored["status"], "undone")
        self.assertEqual((self.root / "report.pdf").read_bytes(), b"original bytes")
        self.assertFalse((self.root / "Documents/report.pdf").exists())

    def test_undo_refuses_changed_content(self):
        run = self.organize()
        (self.root / "Documents/report.pdf").write_bytes(b"edited")
        result = undo(self.root, run["id"])
        self.assertEqual(result["status"], "undo_partial")
        self.assertIn("changed", result["entries"][0]["error"])
        self.assertFalse((self.root / "report.pdf").exists())

    def test_undo_refuses_occupied_original_path_and_can_be_retried(self):
        run = self.organize()
        (self.root / "report.pdf").write_bytes(b"new file")
        self.assertEqual(undo(self.root, run["id"])["status"], "undo_partial")
        self.assertEqual((self.root / "report.pdf").read_bytes(), b"new file")
        (self.root / "report.pdf").unlink()
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")

    def test_stale_plan_does_not_move_modified_file(self):
        plan = build_plan(self.root)
        (self.root / "report.pdf").write_bytes(b"changed since preview")
        result = execute(plan)
        self.assertEqual(result["status"], "partial")
        self.assertTrue((self.root / "report.pdf").exists())

    def test_execute_never_replaces_a_newly_occupied_destination(self):
        plan = build_plan(self.root)
        (self.root / "Documents").mkdir()
        (self.root / "Documents/report.pdf").write_bytes(b"do not overwrite")
        result = execute(plan)
        self.assertEqual(result["status"], "partial")
        self.assertEqual((self.root / "Documents/report.pdf").read_bytes(), b"do not overwrite")
        self.assertTrue((self.root / "report.pdf").exists())

    def test_partial_failure_preserves_successful_moves_for_undo(self):
        from filepilot.engine import _move_no_replace

        (self.root / "second.pdf").write_bytes(b"second")

        def move(source, target):
            if source.name == "second.pdf":
                raise PermissionError("test: locked file")
            _move_no_replace(source, target)

        with patch("filepilot.engine._move_no_replace", side_effect=move):
            run = self.organize()
        self.assertEqual(run["status"], "partial")
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")
        self.assertEqual((self.root / "report.pdf").read_bytes(), b"original bytes")
        self.assertEqual((self.root / "second.pdf").read_bytes(), b"second")

    def test_interrupted_move_remains_recoverable(self):
        from filepilot.engine import _move_no_replace

        def interrupted(source, target):
            _move_no_replace(source, target)
            raise KeyboardInterrupt

        with patch("filepilot.engine._move_no_replace", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.organize()
        run = history(self.root)[0]
        self.assertEqual(run["entries"][0]["status"], "pending")
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")

    def test_interrupted_undo_can_resume(self):
        from filepilot.engine import _move_no_replace

        run = self.organize()

        def interrupted(source, target):
            _move_no_replace(source, target)
            raise KeyboardInterrupt

        with patch("filepilot.engine._move_no_replace", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                undo(self.root, run["id"])
        self.assertEqual(load_run(self.root, run["id"])["entries"][0]["status"], "undo_pending")
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")

    def test_empty_plan_creates_no_history(self):
        (self.root / "report.pdf").unlink()
        with self.assertRaises(FilePilotError):
            self.organize()
        self.assertFalse((self.root / ".filepilot").exists())

    def test_history_read_without_history_is_read_only(self):
        self.assertEqual(history(self.root), [])
        self.assertFalse((self.root / ".filepilot").exists())

    def test_run_id_cannot_escape_state_directory(self):
        with self.assertRaises(FilePilotError):
            load_run(self.root, "../../outside")


if __name__ == "__main__":
    unittest.main()
