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
        for command in ("scan", "organize", "watch", "undo", "history", "init"):
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

    def test_missing_folder_has_readable_error(self):
        result = self.command("scan", self.root / "does-not-exist", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_file_instead_of_folder_is_rejected(self):
        source = self.root / "file.pdf"
        source.write_bytes(b"original")
        result = self.command("organize", source, "--apply")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Not a directory", result.stderr)
        self.assertEqual(source.read_bytes(), b"original")

    def test_unknown_run_and_invalid_run_id_have_no_traceback(self):
        for run_id in ("../../escape", "20261108T000000000000Z-12345678"):
            result = self.command("undo", self.root, "--run", run_id, "--apply")
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.root / ".filepilot").exists())

    def test_version_flag(self):
        result = self.command("--version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "FilePilot 0.2.0")

    def test_custom_rules_round_trip_from_cli(self):
        source = self.root / "INVOICE.pdf"
        source.write_bytes(b"invoice")
        config = self.root / "rules.toml"
        config.write_text(
            '[[rules]]\nname="bills"\nextensions=["pdf"]\n'
            'contains="invoice"\ntarget="Bills"\nrename="saved_{name}"',
            encoding="utf-8",
        )
        result = self.command("organize", self.root, "--config", config, "--apply", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["entries"][0]["target"], "Bills/saved_INVOICE.pdf"
        )
        self.assertTrue(config.exists())
        self.assertEqual(self.command("undo", self.root, "--apply").returncode, 0)
        self.assertEqual(source.read_bytes(), b"invoice")

    def test_folder_with_spaces_and_unicode(self):
        folder = self.root / "پوشه با فاصله"
        folder.mkdir()
        (folder / "report.pdf").write_bytes(b"original")
        self.assertEqual(self.command("organize", folder, "--apply").returncode, 0)
        self.assertEqual(self.command("undo", folder, "--apply").returncode, 0)
        self.assertEqual((folder / "report.pdf").read_bytes(), b"original")

    def test_undo_preview_exposes_changed_content_as_blocked_json(self):
        (self.root / "report.pdf").write_bytes(b"original")
        self.assertEqual(self.command("organize", self.root, "--apply").returncode, 0)
        (self.root / "Documents/report.pdf").write_bytes(b"edited")
        result = self.command("undo", self.root, "--json")
        self.assertEqual(result.returncode, 0)
        preview = json.loads(result.stdout)
        self.assertTrue(preview["preview"])
        self.assertEqual(preview["moves"][0]["status"], "blocked")
        self.assertIn("changed", preview["moves"][0]["reason"])

    def test_human_history_identifies_the_run_and_status(self):
        (self.root / "report.pdf").write_bytes(b"original")
        result = self.command("organize", self.root, "--apply", "--json")
        run_id = json.loads(result.stdout)["id"]
        result = self.command("history", self.root)
        self.assertEqual(result.returncode, 0)
        self.assertIn(run_id, result.stdout)
        self.assertIn("completed", result.stdout)

    def test_empty_human_history_explains_there_are_no_saved_runs(self):
        result = self.command("history", self.root)
        self.assertEqual(result.returncode, 0)
        self.assertIn("No saved runs", result.stdout)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_interruption_returns_130_and_the_pending_run_can_be_undone(self):
        (self.root / "report.pdf").write_bytes(b"original")
        program = """
import sys
import filepilot.engine as engine
from filepilot.cli import main
def interrupted(source, target):
    raise KeyboardInterrupt
engine._move_no_replace = interrupted
sys.exit(main(['organize', sys.argv[1], '--apply']))
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(self.root)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 130)
        self.assertIn("Interrupted", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.command("undo", self.root, "--apply").returncode, 0)
        self.assertEqual((self.root / "report.pdf").read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
