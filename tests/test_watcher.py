import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filepilot.config import Rule
from filepilot.engine import history, undo
from filepilot.journal import locked
from filepilot.paths import FilePilotError
from filepilot.planner import build_plan
from filepilot.watcher import FolderWatcher, WatchOptions


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def file(self, name="report.pdf", content=b"original"):
        source = self.root / name
        source.write_bytes(content)
        return source

    def test_existing_file_waits_for_settle_time_and_preview_is_reported_once(self):
        source = self.file()
        watcher = FolderWatcher(self.root, settle=2)
        self.assertEqual(watcher.poll(0), [])
        self.assertEqual(watcher.poll(1), [])
        events = watcher.poll(2)
        self.assertEqual(events[0]["event"], "preview")
        self.assertEqual(events[0]["plan"]["moves"][0]["source"], source.name)
        self.assertEqual(watcher.poll(100), [])
        self.assertEqual(list(self.root.iterdir()), [source])

    def test_settling_uses_elapsed_time_with_a_negative_clock_epoch(self):
        self.file()
        watcher = FolderWatcher(self.root, settle=1)
        self.assertEqual(watcher.poll(-10), [])
        self.assertEqual(watcher.poll(-9)[0]["event"], "preview")

    def test_changes_reset_the_quiet_interval(self):
        source = self.file()
        watcher = FolderWatcher(self.root, settle=2)
        watcher.poll(0)
        source.write_bytes(b"still downloading")
        self.assertEqual(watcher.poll(1), [])
        self.assertEqual(watcher.poll(2), [])
        self.assertEqual(watcher.poll(3)[0]["event"], "preview")

    def test_new_files_and_changed_previews_are_detected(self):
        watcher = FolderWatcher(self.root, settle=1)
        self.assertEqual(watcher.poll(0), [])
        source = self.file()
        self.assertEqual(watcher.poll(1), [])
        self.assertEqual(len(watcher.poll(2)), 1)
        source.write_bytes(b"new content")
        self.assertEqual(watcher.poll(3), [])
        self.assertEqual(len(watcher.poll(4)), 1)

    def test_recreated_file_with_same_size_and_mtime_settles_again(self):
        source = self.file()
        original_time = source.stat().st_mtime_ns
        watcher = FolderWatcher(self.root, settle=1)
        watcher.poll(0)
        watcher.poll(1)
        replacement = self.root / "replacement.tmp"
        replacement.write_bytes(b"original")
        os.utime(replacement, ns=(original_time, original_time))
        os.replace(replacement, source)
        self.assertEqual(watcher.poll(2), [])
        self.assertEqual(len(watcher.poll(3)), 1)

    def test_temporary_hidden_unmatched_and_config_files_are_ignored(self):
        for name in ("download.pdf.part", ".hidden.pdf", "unknown.bin", "rules.pdf"):
            self.file(name)
        (self.root / "subfolder").mkdir()
        watcher = FolderWatcher(self.root, settle=1, exclude=(self.root / "rules.pdf",))
        self.assertEqual(watcher.poll(0), [])
        self.assertEqual(watcher.poll(10), [])
        self.assertFalse((self.root / ".filepilot").exists())

    def test_unstable_file_is_not_included_in_a_stable_files_plan(self):
        self.file("ready.pdf")
        changing = self.file("busy.txt")
        rules = (Rule("pdf", ("pdf",), "Documents"), Rule("text", ("txt",), "Missing/Child"))
        watcher = FolderWatcher(self.root, rules=rules, settle=2)
        watcher.poll(0)
        self.file("Missing", b"blocks text rule")
        changing.write_bytes(b"still changing")
        events = watcher.poll(2)
        self.assertEqual([m["source"] for m in events[0]["plan"]["moves"]], ["ready.pdf"])

    def test_planner_include_is_optional_and_excludes_unselected_files(self):
        self.file("a.pdf")
        self.file("b.pdf")
        plan = build_plan(self.root, include=frozenset({"b.pdf"}))
        self.assertEqual([move.source for move in plan.moves], ["b.pdf"])
        self.assertEqual(len(build_plan(self.root).moves), 2)

    def test_invalid_timing_and_limits_are_rejected(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(FilePilotError):
                WatchOptions(interval=value)
            with self.subTest(value=value), self.assertRaises(FilePilotError):
                FolderWatcher(self.root, settle=value)
        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(FilePilotError):
                WatchOptions(max_cycles=value)

    def test_applying_a_stable_batch_uses_history_and_can_be_undone(self):
        source = self.file()
        watcher = FolderWatcher(self.root, settle=1, apply=True)
        watcher.poll(0)
        events = watcher.poll(1)
        self.assertEqual(events[0]["event"], "run")
        self.assertEqual(events[0]["run"]["status"], "completed")
        self.assertFalse(source.exists())
        self.assertEqual(watcher.poll(2), [])
        self.assertEqual(len(history(self.root)), 1)
        self.assertEqual(undo(self.root)["status"], "undone")
        self.assertEqual(source.read_bytes(), b"original")

    def test_failed_moves_have_spaced_bounded_retries_and_changes_reset_them(self):
        source = self.file()
        watcher = FolderWatcher(self.root, settle=1, apply=True)
        watcher.poll(0)
        with patch(
            "filepilot.engine._move_no_replace", side_effect=PermissionError("busy")
        ) as move:
            self.assertEqual(watcher.poll(1)[0]["run"]["status"], "partial")
            self.assertEqual(watcher.poll(1.5), [])
            watcher.poll(2)
            watcher.poll(3)
            self.assertEqual(watcher.poll(100), [])
            self.assertEqual(move.call_count, 3)
        self.assertTrue(watcher.has_failures)
        source.write_bytes(b"modified")
        self.assertEqual(watcher.poll(101), [])
        self.assertEqual(watcher.poll(102)[0]["run"]["status"], "completed")
        self.assertFalse(watcher.has_failures)

    def test_changes_during_planning_restart_settling(self):
        source = self.file()
        watcher = FolderWatcher(self.root, settle=1, apply=True)
        watcher.poll(0)
        original = build_plan

        def changed(*args, **kwargs):
            plan = original(*args, **kwargs)
            source.write_bytes(b"changed during planning")
            return plan

        with patch("filepilot.watcher.build_plan", side_effect=changed):
            self.assertEqual(watcher.poll(1), [])
        self.assertFalse((self.root / ".filepilot").exists())
        self.assertEqual(watcher.poll(2)[0]["run"]["status"], "completed")

    def test_disappearing_files_are_removed_from_tracking(self):
        source = self.file()
        watcher = FolderWatcher(self.root, settle=1)
        watcher.poll(0)
        source.unlink()
        self.assertEqual(watcher.poll(1), [])
        self.file()
        self.assertEqual(watcher.poll(2), [])
        self.assertEqual(len(watcher.poll(3)), 1)

    def test_scan_errors_are_reported_once_then_retried(self):
        self.file()
        watcher = FolderWatcher(self.root, settle=1)
        with patch("filepilot.watcher._signature", side_effect=PermissionError("busy")):
            self.assertEqual(watcher.poll(0)[0]["event"], "error")
            self.assertEqual(watcher.poll(1), [])
            self.assertTrue(watcher.has_failures)
        self.assertEqual(watcher.poll(2), [])
        self.assertEqual(len(watcher.poll(3)), 1)
        self.assertFalse(watcher.has_failures)

    def test_removed_root_stops_watching(self):
        watcher = FolderWatcher(self.root)
        self.root.rmdir()
        with self.assertRaises(OSError):
            watcher.poll(0)

    def test_journal_errors_are_fatal_and_do_not_become_repeated_attempts(self):
        source = self.file()
        watcher = FolderWatcher(self.root, settle=1, apply=True)
        watcher.poll(0)
        with (
            patch("filepilot.engine.save_run", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            watcher.poll(1)
        self.assertEqual(source.read_bytes(), b"original")

    def test_named_watcher_lock_does_not_block_the_execution_lock(self):
        with locked(self.root, name="watch.lock"), locked(self.root):
            self.assertTrue((self.root / ".filepilot/watch.lock").exists())

    def test_invalid_lock_name_is_rejected_without_creating_state(self):
        with self.assertRaises(FilePilotError), locked(self.root, name="../other"):
            self.fail("unsafe lock name accepted")
        self.assertFalse((self.root / ".filepilot").exists())

    def test_replaced_root_stops_before_processing_the_new_directory(self):
        watcher = FolderWatcher(self.root)
        with tempfile.TemporaryDirectory() as replacement:
            container = Path(replacement).resolve()
            destination = container / "original"
            self.assertTrue(destination.is_relative_to(container))
            self.root.rename(destination)
            self.root.mkdir()
            with self.assertRaises(FilePilotError):
                watcher.poll(0)

    def test_file_disappearing_during_snapshot_does_not_stop_the_watcher(self):
        source = self.file()
        watcher = FolderWatcher(self.root, settle=1)
        with patch("filepilot.watcher._signature", side_effect=FileNotFoundError):
            self.assertEqual(watcher.poll(0), [])
        self.assertEqual(source.read_bytes(), b"original")
        self.assertEqual(watcher.poll(1), [])
        self.assertEqual(len(watcher.poll(2)), 1)

    def test_file_disappearing_after_planning_is_not_executed(self):
        source = self.file()
        watcher = FolderWatcher(self.root, settle=1, apply=True)
        watcher.poll(0)

        def removed(*args, **kwargs):
            plan = build_plan(*args, **kwargs)
            source.unlink()
            return plan

        with patch("filepilot.watcher.build_plan", side_effect=removed):
            self.assertEqual(watcher.poll(1), [])
        self.assertFalse((self.root / ".filepilot").exists())


if __name__ == "__main__":
    unittest.main()
