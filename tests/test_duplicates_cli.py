import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DuplicatesCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "پوشه با فاصله"
        self.root.mkdir()

    def command(self, *args, expected=0, program=None):
        prefix = [sys.executable, "-c", program] if program else [sys.executable, "-m", "filepilot"]
        result = subprocess.run(
            [*prefix, *map(str, args)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=20,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def files(self):
        (self.root / "invoice.pdf").write_bytes(b"duplicate")
        (self.root / "فاکتور.bin").write_bytes(b"duplicate")
        (self.root / "different.xyz").write_bytes(b"different")

    def test_json_report_has_exact_groups_summary_and_no_filesystem_changes(self):
        self.files()
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}
        result = self.command("duplicates", self.root, "--json")
        report = json.loads(result.stdout)
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["root"], str(self.root))
        self.assertEqual(report["groups"][0]["files"], ["invoice.pdf", "فاکتور.bin"])
        self.assertEqual(report["summary"]["duplicate_files"], 1)
        self.assertEqual(report["summary"]["redundant_bytes"], 9)
        self.assertEqual(report["errors"], [])
        self.assertEqual(result.stderr, "")
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}
        self.assertEqual(after, before)
        self.assertFalse((self.root / ".filepilot").exists())

    def test_human_report_includes_hash_names_counts_and_logical_bytes(self):
        self.files()
        result = self.command("duplicates", self.root)
        self.assertIn("invoice.pdf", result.stdout)
        self.assertIn("فاکتور.bin", result.stdout)
        self.assertIn("SHA-256", result.stdout)
        self.assertIn("9", result.stdout)
        self.assertIn("logical bytes", result.stdout)
        self.assertIn("Read-only", result.stdout)

    def test_no_matches_and_empty_folder_are_successful_reports(self):
        self.assertIn("No duplicate", self.command("duplicates", self.root).stdout)
        (self.root / "one.pdf").write_bytes(b"unique")
        report = json.loads(self.command("duplicates", self.root, "--json").stdout)
        self.assertEqual(report["groups"], [])
        self.assertEqual(report["summary"]["hashed_files"], 0)
        self.assertFalse((self.root / ".filepilot").exists())

    def test_missing_folder_and_file_root_return_input_error_without_json(self):
        (self.root / "file.txt").write_bytes(b"unique")
        for folder in (self.root / "missing", self.root / "file.txt"):
            result = self.command("duplicates", folder, "--json", expected=2)
            self.assertEqual(result.stdout, "")
            self.assertIn("Error:", result.stderr)

    def test_moving_and_rule_flags_are_not_accepted(self):
        self.files()
        for option in ("--apply", "--delete", "--recursive", "--config"):
            self.command("duplicates", self.root, option, expected=2)
        self.assertFalse((self.root / ".filepilot").exists())
        self.assertTrue((self.root / "invoice.pdf").exists())

    def test_filtered_entries_are_visible_in_json(self):
        self.files()
        (self.root / "download.PART").write_bytes(b"duplicate")
        (self.root / ".hidden").write_bytes(b"duplicate")
        (self.root / "nested").mkdir()
        report = json.loads(self.command("duplicates", self.root, "--json").stdout)
        self.assertEqual(report["summary"]["scanned_files"], 3)
        self.assertEqual(len(report["skipped"]), 3)
        human = self.command("duplicates", self.root).stdout
        self.assertIn("SKIP", human)
        self.assertIn("download.PART", human)

    def test_partial_json_is_machine_readable_and_returns_exit_one(self):
        self.files()
        program = """
import sys
from unittest.mock import patch
from filepilot.cli import main
from filepilot.duplicates import _hash_file

def read(root, candidate):
    if candidate.source == 'different.xyz':
        raise PermissionError('test: unreadable file')
    return _hash_file(root, candidate)

with patch('filepilot.duplicates._hash_file', side_effect=read):
    sys.exit(main(['duplicates', sys.argv[1], *sys.argv[2:]]))
"""
        result = self.command(self.root, "--json", expected=1, program=program)
        report = json.loads(result.stdout)
        self.assertEqual(report["groups"][0]["files"], ["invoice.pdf", "فاکتور.bin"])
        self.assertEqual(report["errors"][0]["source"], "different.xyz")
        self.assertEqual(result.stderr, "")
        human = self.command(self.root, expected=1, program=program)
        self.assertIn("incomplete", human.stdout)
        self.assertIn("different.xyz", human.stderr)
        self.assertIn("test: unreadable file", human.stderr)
        self.assertFalse((self.root / ".filepilot").exists())

    def test_interruption_is_read_only_and_returns_130(self):
        self.files()
        program = """
import sys
from unittest.mock import patch
from filepilot.cli import main
with patch('filepilot.duplicates._hash_file', side_effect=KeyboardInterrupt):
    sys.exit(main(['duplicates', sys.argv[1]]))
"""
        result = self.command(self.root, expected=130, program=program)
        self.assertIn("Interrupted", result.stderr)
        self.assertNotIn("history", result.stderr)
        self.assertFalse((self.root / ".filepilot").exists())
        self.assertEqual((self.root / "invoice.pdf").read_bytes(), b"duplicate")


if __name__ == "__main__":
    unittest.main()
