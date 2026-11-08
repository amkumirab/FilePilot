import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filepilot.config import Rule
from filepilot.engine import _move_no_replace, execute, load_run
from filepilot.journal import locked
from filepilot.paths import FilePilotError
from filepilot.planner import build_plan


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "report.pdf").write_bytes(b"keep these bytes")

    def test_os_lock_blocks_another_process_and_is_released_after_exit(self):
        program = (
            "from pathlib import Path; import sys; "
            "from filepilot.journal import locked; "
            "from filepilot.paths import FilePilotError; "
            "\ntry:\n with locked(Path(sys.argv[1])): pass"
            "\nexcept FilePilotError: sys.exit(7)"
        )
        with locked(self.root):
            result = subprocess.run(
                [sys.executable, "-c", program, str(self.root)], capture_output=True, timeout=10
            )
            self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(execute(build_plan(self.root))["status"], "completed")

    def test_journal_failure_prevents_move(self):
        with (
            patch("filepilot.engine.save_run", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            execute(build_plan(self.root))
        self.assertTrue((self.root / "report.pdf").exists())
        self.assertFalse((self.root / "Documents/report.pdf").exists())

    def test_invalid_journal_status_is_a_readable_error(self):
        run = execute(build_plan(self.root))
        path = self.root / ".filepilot/runs" / f"{run['id']}.json"
        run["status"] = []
        path.write_text(json.dumps(run), encoding="utf-8")
        with self.assertRaises(FilePilotError):
            load_run(self.root, run["id"])

    def test_tampered_journal_cannot_restore_outside_root(self):
        run = execute(build_plan(self.root))
        path = self.root / ".filepilot/runs" / f"{run['id']}.json"
        run["entries"][0]["source"] = "../escape.pdf"
        path.write_text(json.dumps(run), encoding="utf-8")
        with self.assertRaises(FilePilotError):
            load_run(self.root, run["id"])

    def test_directory_link_cannot_redirect_moves_outside_root(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.root / "Documents"
        if os.name == "nt":
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(FilePilotError):
            build_plan(self.root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_posix_move_strategy_preserves_bytes_and_never_overwrites(self):
        source = self.root / "report.pdf"
        target = self.root / "moved.pdf"
        with patch("filepilot.engine.os.name", "posix"):
            _move_no_replace(source, target)
        self.assertEqual(target.read_bytes(), b"keep these bytes")
        source.write_bytes(b"new")
        with patch("filepilot.engine.os.name", "posix"), self.assertRaises(FileExistsError):
            _move_no_replace(source, target)
        self.assertEqual(source.read_bytes(), b"new")
        self.assertEqual(target.read_bytes(), b"keep these bytes")

    def test_portable_windows_names_and_path_templates_are_validated(self):
        for target in (
            "CON",
            "Data/NUL.pdf",
            "Docs/../outside",
            "Docs ",
            "Docs/{stem!r}",
            "Docs/{stem.__class__}",
            "Docs/{year:>20}",
        ):
            with self.subTest(target=target), self.assertRaises(FilePilotError):
                Rule("bad", (), target)

    def test_windows_hidden_attribute_is_respected(self):
        source = self.root / "report.pdf"
        if os.name == "nt":
            import ctypes

            self.assertTrue(ctypes.windll.kernel32.SetFileAttributesW(str(source), 2))
            self.addCleanup(ctypes.windll.kernel32.SetFileAttributesW, str(source), 128)
        else:
            source.rename(self.root / ".report.pdf")
        self.assertFalse(build_plan(self.root).moves)

    def test_planned_files_cannot_also_be_planned_parent_directories(self):
        (self.root / "second.txt").write_bytes(b"second")
        rules = (
            Rule("one", ("pdf",), "Docs", rename="nested"),
            Rule("two", ("txt",), "Docs/nested"),
        )
        with self.assertRaises(FilePilotError):
            build_plan(self.root, rules)


if __name__ == "__main__":
    unittest.main()
