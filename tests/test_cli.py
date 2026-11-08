import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def command(self, *args):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(
            [sys.executable, "-m", "filepilot", *map(str, args)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_help_exposes_commands(self):
        result = self.command("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("scan", "organize", "undo", "history", "init"):
            self.assertIn(command, result.stdout)

    def test_full_cli_workflow_and_both_previews_are_read_only(self):
        source = self.root / "report.pdf"
        source.write_bytes(b"demo")
        result = self.command("scan", self.root, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["moves"][0]["target"], "Documents/report.pdf")
        self.assertEqual(self.command("organize", self.root).returncode, 0)
        self.assertEqual(list(self.root.iterdir()), [source])
        result = self.command("organize", self.root, "--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        run_id = json.loads(result.stdout)["id"]
        self.assertFalse(source.exists())
        journal = self.root / ".filepilot/runs" / f"{run_id}.json"
        before = journal.read_bytes()
        self.assertEqual(self.command("undo", self.root).returncode, 0)
        self.assertEqual(journal.read_bytes(), before)
        result = self.command("undo", self.root, "--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source.read_bytes(), b"demo")
        self.assertEqual(json.loads(result.stdout)["status"], "undone")

    def test_invalid_config_fails_without_creating_state(self):
        config = self.root / "bad.toml"
        config.write_text("not valid toml", encoding="utf-8")
        result = self.command("organize", self.root, "--config", config, "--apply")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.root / ".filepilot").exists())

    def test_init_is_exclusive_and_custom_config_is_not_organized(self):
        config = self.root / "rules.toml"
        self.assertEqual(self.command("init", "--output", config).returncode, 0)
        before = config.read_bytes()
        self.assertEqual(self.command("init", "--output", config).returncode, 2)
        self.assertEqual(config.read_bytes(), before)
        config.write_text('[[rules]]\nname="all"\ntarget="Other"', encoding="utf-8")
        result = self.command("scan", self.root, "--config", config, "--json")
        self.assertEqual(json.loads(result.stdout)["moves"], [])

    def test_unicode_filename_survives_json_and_round_trip(self):
        source = self.root / "فاکتور.pdf"
        source.write_bytes(b"unicode")
        result = self.command("organize", self.root, "--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["entries"][0]["source"], source.name)
        self.assertEqual(self.command("undo", self.root, "--apply").returncode, 0)
        self.assertEqual(source.read_bytes(), b"unicode")

    def test_empty_folder_and_missing_history_return_clear_messages(self):
        self.assertEqual(self.command("organize", self.root, "--apply").returncode, 0)
        self.assertEqual(json.loads(self.command("history", self.root, "--json").stdout), [])
        result = self.command("undo", self.root, "--apply")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / ".filepilot").exists())

    def test_partial_undo_returns_failure_status(self):
        source = self.root / "report.pdf"
        source.write_bytes(b"original")
        self.command("organize", self.root, "--apply")
        (self.root / "Documents/report.pdf").write_bytes(b"edited")
        result = self.command("undo", self.root, "--apply", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "undo_partial")

    def test_human_undo_output_shows_restoration_direction(self):
        (self.root / "report.pdf").write_bytes(b"original")
        self.assertEqual(self.command("organize", self.root, "--apply").returncode, 0)
        result = self.command("undo", self.root, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("'Documents/report.pdf' -> 'report.pdf'", result.stdout)


if __name__ == "__main__":
    unittest.main()
