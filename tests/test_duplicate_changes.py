import hashlib
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from filepilot.duplicates import CHUNK_BYTES, _hash_file, find_duplicates
from filepilot.paths import FilePilotError


def altered(info, **changes):
    fields = {
        key: getattr(info, key)
        for key in (
            "st_mode",
            "st_dev",
            "st_ino",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    }
    fields["st_birthtime_ns"] = getattr(info, "st_birthtime_ns", 0)
    return SimpleNamespace(**{**fields, **changes})


class DuplicateChangeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.root = self.work / "inbox"
        self.root.mkdir()
        (self.root / "a").write_bytes(b"same")
        (self.root / "b").write_bytes(b"same")

    def test_replaced_file_with_preserved_size_and_mtime_is_not_reported(self):
        def replace_before_read(root, candidate):
            if candidate.source == "a":
                path = root / "a"
                info = path.stat()
                replacement = root / ".replacement"
                replacement.write_bytes(b"same")
                os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
                os.replace(replacement, path)
            return _hash_file(root, candidate)

        with patch("filepilot.duplicates._hash_file", side_effect=replace_before_read):
            report = find_duplicates(self.root)
        self.assertEqual(report.groups, ())
        self.assertEqual(report.errors[0].source, "a")
        self.assertIn("changed", report.errors[0].message)

    def test_disappeared_file_is_an_error_while_other_candidates_continue(self):
        def disappear(root, candidate):
            if candidate.source == "a":
                (root / "a").unlink()
            return _hash_file(root, candidate)

        with patch("filepilot.duplicates._hash_file", side_effect=disappear):
            report = find_duplicates(self.root)
        self.assertEqual(report.groups, ())
        self.assertEqual(report.hashed_files, 1)
        self.assertEqual(report.errors[0].source, "a")

    def test_growing_and_shrinking_files_are_bounded_and_handles_are_closed(self):
        real_sha256 = hashlib.sha256
        for operation in ("grow", "shrink"):
            content = b"x" * (2 * CHUNK_BYTES + 3)
            (self.root / "a").write_bytes(content)
            (self.root / "b").write_bytes(content)
            mutated = False

            def mutate_on_update(operation=operation):
                digest = real_sha256()

                class MutatingHash:
                    def update(inner, block):
                        nonlocal mutated
                        digest.update(block)
                        if not mutated:
                            mutated = True
                            with (self.root / "a").open(
                                "ab" if operation == "grow" else "wb"
                            ) as writer:
                                writer.write(b"extra" if operation == "grow" else b"")

                    def hexdigest(inner):
                        return digest.hexdigest()

                return MutatingHash()

            with patch("filepilot.duplicates.hashlib.sha256", side_effect=mutate_on_update):
                report = find_duplicates(self.root)
            with self.subTest(operation=operation):
                self.assertEqual(report.groups, ())
                self.assertEqual(report.errors[0].source, "a")
                self.assertIn("changed", report.errors[0].message)
                (self.root / "a").unlink()  # Windows would fail if a reader handle leaked.

    def test_nonregular_replacement_is_rejected_after_open(self):
        real_fstat = os.fstat
        with patch(
            "filepilot.duplicates.os.fstat",
            side_effect=lambda fd: altered(
                real_fstat(fd),
                st_mode=stat.S_IFIFO,
            ),
        ):
            report = find_duplicates(self.root)
        self.assertEqual(report.groups, ())
        self.assertEqual(len(report.errors), 2)
        (self.root / "a").unlink()

    def test_scan_stat_errors_do_not_hide_healthy_duplicate_groups(self):
        (self.root / "denied").write_bytes(b"same")
        original_stat = Path.stat

        def denied(path, *args, **kwargs):
            if path.name == "denied":
                raise PermissionError("test: cannot stat")
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", denied):
            report = find_duplicates(self.root)
        self.assertEqual(report.groups[0].files, ("a", "b"))
        self.assertEqual(report.errors[0].source, "denied")

    def test_root_replacement_aborts_the_report(self):
        changed = False

        def replace_root(root, candidate):
            nonlocal changed
            digest = _hash_file(root, candidate)
            if not changed:
                changed = True
                root.rename(self.work / "old-inbox")
                root.mkdir()
            return digest

        with (
            patch("filepilot.duplicates._hash_file", side_effect=replace_root),
            self.assertRaisesRegex(FilePilotError, "folder changed"),
        ):
            find_duplicates(self.root)

    def test_enumeration_error_aborts_instead_of_claiming_no_matches(self):
        with (
            patch.object(Path, "iterdir", side_effect=PermissionError("test: cannot list")),
            self.assertRaises(PermissionError),
        ):
            find_duplicates(self.root)

    def test_zero_inodes_do_not_coalesce_unrelated_files(self):
        original_stat, original_fstat = Path.stat, os.fstat

        def no_inode(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            return altered(info, st_ino=0) if stat.S_ISREG(info.st_mode) else info

        with (
            patch.object(Path, "stat", no_inode),
            patch(
                "filepilot.duplicates.os.fstat",
                side_effect=lambda fd: altered(
                    original_fstat(fd),
                    st_ino=0,
                ),
            ),
        ):
            report = find_duplicates(self.root)
        self.assertEqual(report.groups[0].files, ("a", "b"))
        self.assertEqual(report.scanned_files, 2)

    def test_unreadable_subfolder_keeps_results_from_other_paths(self):
        denied = self.root / "sub" / "denied"
        denied.mkdir(parents=True)
        original_iterdir = Path.iterdir

        def iterdir(path):
            if path == denied:
                raise PermissionError("test: cannot list subfolder")
            return original_iterdir(path)

        with patch.object(Path, "iterdir", iterdir):
            report = find_duplicates(self.root, recursive=True)
        self.assertEqual(report.groups[0].files, ("a", "b"))
        self.assertEqual([error.source for error in report.errors], ["sub/denied"])

    def test_junction_or_symlink_is_skipped_without_following_it(self):
        outside = self.work / "outside"
        outside.mkdir()
        (outside / "copy").write_bytes(b"same")
        nested = self.root / "nested"
        nested.mkdir()
        link = nested / "linked"
        if os.name == "nt":
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(outside, target_is_directory=True)
        report = find_duplicates(self.root, recursive=True)
        self.assertEqual(report.groups[0].files, ("a", "b"))
        self.assertEqual(report.skipped[0].reason, "link or junction")
        self.assertEqual(report.skipped[0].source, "nested/linked")
        self.assertEqual(report.scanned_files, 2)

    def test_nonregular_fifo_is_not_opened_on_posix(self):
        if os.name != "nt":
            os.mkfifo(self.root / "pipe")
        report = find_duplicates(self.root)
        self.assertEqual(report.groups[0].files, ("a", "b"))
        if os.name != "nt":
            self.assertEqual(report.skipped[0].reason, "directory or non-regular file")

    def test_native_file_sharing_errors_preserve_healthy_groups_and_originals(self):
        path = self.root / "locked"
        path.write_bytes(b"same")
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateFileW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            kernel.CreateFileW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 128, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value, ctypes.get_last_error())
            try:
                report = find_duplicates(self.root)
            finally:
                self.assertTrue(kernel.CloseHandle(handle))
            self.assertEqual(report.groups[0].files, ("a", "b"))
            self.assertEqual(report.errors[0].source, "locked")
        else:
            with path.open("rb"):
                report = find_duplicates(self.root)
            self.assertEqual(report.groups[0].files, ("a", "b", "locked"))
            self.assertEqual(report.errors, ())
        self.assertEqual(path.read_bytes(), b"same")


if __name__ == "__main__":
    unittest.main()
