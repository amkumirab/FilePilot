import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from filepilot.engine import execute, load_run
from filepilot.journal import save_run
from filepilot.planner import build_plan


class JournalWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "report.pdf").write_bytes(b"original")
        self.run_record = execute(build_plan(self.root))

    @staticmethod
    def sharing_error(code=32):
        error = PermissionError(errno.EACCES, "test: journal is temporarily open")
        error.winerror = code
        return error

    def test_transient_windows_sharing_errors_retry_and_save_the_new_state(self):
        import os

        original_replace = os.replace
        for code in (5, 32, 33):
            attempts = 0

            def replace(source, target, error_code=code):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise self.sharing_error(error_code)
                return original_replace(source, target)

            self.run_record["status"] = "partial"
            with (
                self.subTest(code=code),
                patch("filepilot.journal.os.replace", side_effect=replace),
            ):
                save_run(self.root, self.run_record)
            self.assertEqual(attempts, 2)
            self.assertEqual(load_run(self.root, self.run_record["id"])["status"], "partial")

    def test_persistent_sharing_failure_is_bounded_and_preserves_old_journal(self):
        original = (self.root / ".filepilot/runs" / f"{self.run_record['id']}.json").read_bytes()
        with (
            patch("filepilot.journal.os.replace", side_effect=self.sharing_error()) as replace,
            self.assertRaises(PermissionError),
        ):
            save_run(self.root, self.run_record)
        self.assertEqual(replace.call_count, 6)
        self.assertEqual(
            (self.root / ".filepilot/runs" / f"{self.run_record['id']}.json").read_bytes(), original
        )
        self.assertEqual(list((self.root / ".filepilot/runs").glob("*.tmp")), [])

    def test_other_replace_errors_are_not_retried(self):
        for error in (OSError(errno.ENOSPC, "disk full"), PermissionError(errno.EACCES, "denied")):
            with (
                self.subTest(error=error),
                patch("filepilot.journal.os.replace", side_effect=error) as replace,
                self.assertRaises(OSError),
            ):
                save_run(self.root, self.run_record)
            self.assertEqual(replace.call_count, 1)


if __name__ == "__main__":
    unittest.main()
