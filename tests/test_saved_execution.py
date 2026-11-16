import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from filepilot.engine import execute, history, undo
from filepilot.journal import locked, save_run
from filepilot.paths import FilePilotError
from filepilot.planner import build_plan
from filepilot.saved_plans import save_plan


class SavedExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.root = self.work / "inbox"
        self.root.mkdir()
        (self.root / "a.pdf").write_bytes(b"first")
        (self.root / "b.pdf").write_bytes(b"second")
        self.saved = save_plan(build_plan(self.root), self.work / "plan.json")

    def apply(self):
        return execute(self.saved.plan, hashes=self.saved.hashes)

    def test_saved_batch_uses_existing_history_and_undo(self):
        run = self.apply()
        self.assertEqual(run["status"], "completed")
        self.assertEqual([entry["source"] for entry in run["entries"]], ["a.pdf", "b.pdf"])
        self.assertEqual(run["entries"][0]["sha256"], self.saved.hashes[0])
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")
        self.assertEqual((self.root / "a.pdf").read_bytes(), b"first")
        self.assertEqual((self.root / "b.pdf").read_bytes(), b"second")

    def test_stale_last_source_stops_before_first_move_and_records_no_run(self):
        (self.root / "b.pdf").unlink()
        with self.assertRaises(OSError):
            self.apply()
        self.assertEqual((self.root / "a.pdf").read_bytes(), b"first")
        self.assertFalse((self.root / "Documents").exists())
        self.assertEqual(history(self.root), [])

    def test_occupied_last_destination_stops_the_whole_batch(self):
        (self.root / "Documents").mkdir()
        (self.root / "Documents/b.pdf").write_bytes(b"do not overwrite")
        with self.assertRaisesRegex(FilePilotError, "occupied"):
            self.apply()
        self.assertTrue((self.root / "a.pdf").exists())
        self.assertEqual((self.root / "Documents/b.pdf").read_bytes(), b"do not overwrite")
        self.assertEqual(history(self.root), [])

    def test_preflight_happens_after_acquiring_the_lock(self):
        @contextmanager
        def change_on_lock(root):
            with locked(root):
                (root / "b.pdf").write_bytes(b"changed before preflight")
                yield

        with (
            patch("filepilot.engine.locked", change_on_lock),
            self.assertRaisesRegex(FilePilotError, "changed"),
        ):
            self.apply()
        self.assertTrue((self.root / "a.pdf").exists())
        self.assertEqual(history(self.root), [])

    def test_second_writer_cannot_apply_under_an_existing_lock(self):
        with locked(self.root), self.assertRaisesRegex(FilePilotError, "Another FilePilot"):
            self.apply()
        self.assertTrue((self.root / "a.pdf").exists())
        self.assertEqual(history(self.root), [])

    def test_content_is_rechecked_after_preflight_and_failure_can_be_undone(self):
        changed = False

        def change_after_validation(root, run):
            nonlocal changed
            save_run(root, run)
            if not changed:
                changed = True
                path = root / "b.pdf"
                info = path.stat()
                path.write_bytes(b"SECOND")
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))

        with patch("filepilot.engine.save_run", side_effect=change_after_validation):
            run = self.apply()
        self.assertEqual(run["status"], "partial")
        self.assertEqual(run["entries"][1]["status"], "failed")
        self.assertIn("content changed", run["entries"][1]["error"])
        self.assertEqual((self.root / "b.pdf").read_bytes(), b"SECOND")
        self.assertEqual(undo(self.root, run["id"])["status"], "undone")
        self.assertEqual((self.root / "a.pdf").read_bytes(), b"first")
        self.assertEqual((self.root / "b.pdf").read_bytes(), b"SECOND")

    def test_destination_created_after_preflight_is_never_replaced(self):
        def occupy(root, run):
            save_run(root, run)
            if run["entries"][0]["status"] == "pending":
                (root / "Documents/a.pdf").write_bytes(b"new occupant")

        with patch("filepilot.engine.save_run", side_effect=occupy):
            run = self.apply()
        self.assertEqual(run["status"], "partial")
        self.assertEqual((self.root / "Documents/a.pdf").read_bytes(), b"new occupant")
        self.assertTrue((self.root / "a.pdf").exists())

    def test_interrupted_saved_execution_remains_recoverable(self):
        from filepilot.engine import _move_no_replace

        def interrupted(source, target):
            _move_no_replace(source, target)
            raise KeyboardInterrupt

        with (
            patch("filepilot.engine._move_no_replace", side_effect=interrupted),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.apply()
        self.assertEqual(undo(self.root)["status"], "undone")
        self.assertEqual((self.root / "a.pdf").read_bytes(), b"first")


if __name__ == "__main__":
    unittest.main()
