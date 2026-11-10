import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from filepilot.journal import locked


class WatchCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "report.pdf").write_bytes(b"original")

    def command(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "filepilot", *map(str, args)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    def watch(self, *args):
        return self.command(
            "watch", self.root, "--interval", ".02", "--settle", ".01", "--max-cycles", "3", *args
        )

    def test_watch_help_explains_timing_preview_and_bounded_runs(self):
        result = self.command("watch", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ("--interval", "--settle", "--max-cycles", "--apply", "--config", "--json"):
            self.assertIn(flag, result.stdout)

    def test_default_preview_is_deduplicated_read_only_json_lines(self):
        result = self.watch("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([event["event"] for event in events], ["started", "preview", "stopped"])
        self.assertEqual(events[-1]["cycles"], 3)
        self.assertTrue((self.root / "report.pdf").exists())
        self.assertFalse((self.root / ".filepilot").exists())

    def test_apply_creates_a_journaled_run_and_undo_restores_bytes(self):
        result = self.watch("--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([event["event"] for event in events], ["started", "run", "stopped"])
        self.assertEqual(events[-1]["moved"], 1)
        run_id = events[1]["run"]["id"]
        self.assertFalse((self.root / "report.pdf").exists())
        self.assertEqual(self.command("undo", self.root, "--run", run_id, "--apply").returncode, 0)
        self.assertEqual((self.root / "report.pdf").read_bytes(), b"original")

    def test_custom_rules_are_loaded_and_the_config_is_excluded(self):
        config = self.root / "rules.toml"
        config.write_text('[[rules]]\nname="all"\ntarget="Sorted"', encoding="utf-8")
        result = self.watch("--apply", "--json", "--config", config)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(config.exists())
        self.assertEqual((self.root / "Sorted/report.pdf").read_bytes(), b"original")

    def test_invalid_options_fail_before_creating_state(self):
        for flag in ("--interval", "--settle"):
            for value in ("0", "-1", "nan", "inf"):
                result = self.command("watch", self.root, flag, value, "--apply")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        for value in ("0", "-1", "1.5"):
            self.assertEqual(self.command("watch", self.root, "--max-cycles", value).returncode, 2)
        self.assertFalse((self.root / ".filepilot").exists())

    def test_human_preview_and_apply_summaries(self):
        preview = self.watch()
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("preview", preview.stdout.lower())
        self.assertIn("report.pdf", preview.stdout)
        result = self.watch("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("completed", result.stdout)
        self.assertIn("Stopped", result.stdout)

    def test_another_applying_watcher_is_rejected(self):
        with locked(self.root, name="watch.lock"):
            result = self.watch("--apply", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Another FilePilot process", result.stderr)
        self.assertTrue((self.root / "report.pdf").exists())

    def test_interrupt_emits_a_final_json_event_and_returns_130(self):
        program = """
import sys
from unittest.mock import patch
from filepilot.cli import main
with patch('filepilot.watcher.sleep', side_effect=KeyboardInterrupt):
    sys.exit(main(['watch', sys.argv[1], '--apply', '--json']))
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(self.root)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 130, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(events[-1]["event"], "stopped")
        self.assertEqual(events[-1]["reason"], "interrupted")
        self.assertEqual(self.watch("--apply").returncode, 0)

    def test_scan_errors_are_visible_once_and_return_one_at_a_poll_limit(self):
        program = """
import sys
from unittest.mock import patch
from filepilot.cli import main
with patch('filepilot.watcher._signature', side_effect=PermissionError('busy')):
    sys.exit(main(['watch', sys.argv[1], '--max-cycles', '2', '--interval', '.01']))
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(self.root)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr.count("Watch error"), 1)
        self.assertTrue((self.root / "report.pdf").exists())
        self.assertFalse((self.root / ".filepilot").exists())

    def test_unresolved_move_failures_are_in_the_event_stream_and_exit_status(self):
        program = """
import sys
from unittest.mock import patch
from filepilot.cli import main
with patch('filepilot.engine._move_no_replace', side_effect=PermissionError('busy')):
    sys.exit(main(['watch', sys.argv[1], '--apply', '--json', '--max-cycles', '3',
                   '--interval', '.02', '--settle', '.01']))
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(self.root)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        runs = [event["run"] for event in events if event["event"] == "run"]
        self.assertTrue(runs)
        self.assertTrue(all(run["status"] == "partial" for run in runs))
        self.assertTrue(events[-1]["failed"])
        self.assertEqual((self.root / "report.pdf").read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
