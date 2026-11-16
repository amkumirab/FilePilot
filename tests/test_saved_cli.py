import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SavedCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.root = self.work / "پوشه با فاصله"
        self.root.mkdir()
        (self.root / "فاکتور.pdf").write_bytes(b"original")
        self.output = self.work / "reviewed plan.json"

    def command(self, *args, expected=0):
        result = subprocess.run(
            [sys.executable, "-m", "filepilot", *map(str, args)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=20,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def create(self, *extra):
        return self.command("plan", self.root, "--output", self.output, *extra)

    def test_saved_preview_is_read_only_then_apply_and_undo_round_trip(self):
        result = self.create("--json")
        document = json.loads(result.stdout)
        self.assertEqual(document, json.loads(self.output.read_text()))
        before = self.output.read_bytes()
        self.assertEqual(len(document["moves"]), 1)
        preview = json.loads(self.command("apply", self.output, "--json").stdout)
        self.assertTrue(preview["preview"])
        self.assertEqual(preview["moves"], document["moves"])
        human = self.command("apply", self.output).stdout
        self.assertIn("--apply", human)
        self.assertNotIn("organize FOLDER", human)
        self.assertFalse((self.root / ".filepilot").exists())
        run = json.loads(self.command("apply", self.output, "--apply", "--json").stdout)
        self.assertEqual(run["status"], "completed")
        self.command("undo", self.root, "--apply")
        self.assertEqual((self.root / "فاکتور.pdf").read_bytes(), b"original")
        self.assertEqual(self.output.read_bytes(), before)

    def test_no_overwrite_and_missing_required_arguments(self):
        self.assertIn("Saved", self.create().stdout)
        before = self.output.read_bytes()
        self.command("plan", self.root, "--output", self.output, expected=2)
        self.assertEqual(self.output.read_bytes(), before)
        self.command("plan", self.root, expected=2)
        self.command("apply", expected=2)

    def test_saved_paths_and_rules_are_not_recomputed_and_new_files_are_ignored(self):
        (self.root / "Documents").mkdir()
        occupant = self.root / "Documents/فاکتور.pdf"
        occupant.write_bytes(b"existing")
        self.create()
        occupant.unlink()
        (self.root / "new.pdf").write_bytes(b"not in plan")
        self.command("apply", self.output, "--apply")
        self.assertEqual((self.root / "Documents/فاکتور (2).pdf").read_bytes(), b"original")
        self.assertTrue((self.root / "new.pdf").exists())
        self.command("apply", self.output, "--apply", expected=2)
        self.assertEqual(len(list((self.root / ".filepilot/runs").glob("*.json"))), 1)

    def test_custom_config_and_plan_file_are_excluded_even_with_catch_all_rules(self):
        config = self.root / "rules.toml"
        config.write_text('[[rules]]\nname="all"\ntarget="Sorted"', encoding="utf-8")
        self.output = self.root / "plan.json"
        result = self.create("--config", config, "--json")
        self.assertEqual(len(json.loads(result.stdout)["moves"]), 1)
        config.write_text("now invalid", encoding="utf-8")
        self.command("apply", self.output, "--apply")
        self.assertTrue(config.exists())
        self.assertTrue(self.output.exists())
        self.assertEqual((self.root / "Sorted/فاکتور.pdf").read_bytes(), b"original")

    def test_changed_later_source_blocks_whole_batch_for_preview_and_apply(self):
        (self.root / "a.pdf").write_bytes(b"first")
        self.create()
        (self.root / "فاکتور.pdf").write_bytes(b"changed")
        self.command("apply", self.output, expected=2)
        self.assertFalse((self.root / ".filepilot").exists())
        result = self.command("apply", self.output, "--apply", expected=2)
        self.assertIn("changed", result.stderr)
        self.assertTrue((self.root / "a.pdf").exists())
        self.assertFalse((self.root / "Documents").exists())
        self.assertFalse((self.root / ".filepilot/runs").exists())

    def test_empty_plan_apply_is_a_successful_no_op(self):
        (self.root / "فاکتور.pdf").unlink()
        self.create()
        result = self.command("apply", self.output, "--apply", "--json")
        self.assertEqual(json.loads(result.stdout)["moves"], [])
        self.assertFalse((self.root / ".filepilot").exists())

    def test_malformed_missing_and_directory_plan_have_clear_errors(self):
        self.command("apply", self.output, "--apply", expected=2)
        self.output.write_text("not json", encoding="utf-8")
        self.command("apply", self.output, "--apply", expected=2)
        self.command("apply", self.root, "--apply", expected=2)
        self.assertFalse((self.root / ".filepilot").exists())


if __name__ == "__main__":
    unittest.main()
