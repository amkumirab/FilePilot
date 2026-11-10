import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filepilot.engine import history, undo
from filepilot.journal import locked
from filepilot.paths import FilePilotError
from filepilot.watcher import WatchOptions, watch_folder


class WatchRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "report.pdf").write_bytes(b"original")

    def test_bounded_apply_emits_events_and_stops_after_the_poll_limit(self):
        events = []
        with (
            patch("filepilot.watcher.monotonic", side_effect=[0, 1, 2]),
            patch("filepilot.watcher.sleep") as sleep,
        ):
            status = watch_folder(
                self.root,
                apply=True,
                options=WatchOptions(settle=1, max_cycles=3),
                emit=events.append,
            )
        self.assertEqual(status, 0)
        self.assertEqual([event["event"] for event in events], ["started", "run", "stopped"])
        self.assertEqual(events[-1]["cycles"], 3)
        self.assertEqual(events[-1]["moved"], 1)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(undo(self.root)["status"], "undone")

    def test_preview_runner_never_creates_state_and_can_discard_events(self):
        with (
            patch("filepilot.watcher.monotonic", side_effect=[0, 1]),
            patch("filepilot.watcher.sleep"),
        ):
            self.assertEqual(
                watch_folder(self.root, options=WatchOptions(settle=1, max_cycles=2)), 0
            )
        self.assertFalse((self.root / ".filepilot").exists())

    def test_interruption_releases_the_watcher_lock_and_reports_130(self):
        events = []
        with patch("filepilot.watcher.sleep", side_effect=KeyboardInterrupt):
            status = watch_folder(self.root, apply=True, emit=events.append)
        self.assertEqual(status, 130)
        self.assertEqual(events[-1]["reason"], "interrupted")
        with locked(self.root, name="watch.lock"):
            pass
        self.assertEqual(history(self.root), [])

    def test_second_applying_watcher_fails_before_emitting_started(self):
        events = []
        with locked(self.root, name="watch.lock"), self.assertRaises(FilePilotError):
            watch_folder(self.root, apply=True, emit=events.append)
        self.assertEqual(events, [])

    def test_bounded_watch_returns_one_when_a_file_still_has_failed_moves(self):
        with (
            patch("filepilot.watcher.monotonic", side_effect=[0, 1]),
            patch("filepilot.watcher.sleep"),
            patch("filepilot.engine._move_no_replace", side_effect=PermissionError("busy")),
        ):
            status = watch_folder(
                self.root, apply=True, options=WatchOptions(settle=1, max_cycles=2)
            )
        self.assertEqual(status, 1)
        self.assertEqual((self.root / "report.pdf").read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
