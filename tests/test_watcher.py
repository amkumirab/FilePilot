import os
import tempfile
import unittest
from pathlib import Path

from filepilot.config import Rule
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


if __name__ == "__main__":
    unittest.main()
