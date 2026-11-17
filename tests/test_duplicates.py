import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from filepilot.duplicates import find_duplicates
from filepilot.paths import FilePilotError


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def file(self, name, content=b"same bytes"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_content_groups_ignore_names_and_extensions_and_preserve_bytes(self):
        self.file("report.pdf")
        self.file("copy.xyz")
        self.file("گزارش.bin")
        self.file("different.pdf", b"other data")
        self.file("unique.txt", b"unique length")
        before = {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.root.iterdir()
        }
        report = find_duplicates(self.root).to_dict()
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["root"], str(self.root))
        self.assertEqual(
            report["groups"],
            [
                {
                    "sha256": hashlib.sha256(b"same bytes").hexdigest(),
                    "size": 10,
                    "files": ["copy.xyz", "report.pdf", "گزارش.bin"],
                    "redundant_bytes": 20,
                }
            ],
        )
        self.assertEqual(
            report["summary"],
            {
                "scanned_files": 5,
                "hashed_files": 4,
                "duplicate_groups": 1,
                "duplicate_files": 2,
                "redundant_bytes": 20,
            },
        )
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["skipped"], [])
        after = {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.root.iterdir()
        }
        self.assertEqual(after, before)

    def test_same_size_different_content_does_not_match(self):
        self.file("a", b"abcd")
        self.file("b", b"efgh")
        report = find_duplicates(self.root)
        self.assertEqual(report.groups, ())
        self.assertEqual(report.hashed_files, 2)

    def test_unique_sizes_are_not_hashed(self):
        self.file("a", b"1")
        self.file("b", b"12")
        with patch("filepilot.duplicates._hash_file", side_effect=AssertionError("extra I/O")):
            report = find_duplicates(self.root)
        self.assertEqual(report.hashed_files, 0)
        self.assertEqual(report.scanned_files, 2)

    def test_windows_signature_uses_birthtime_instead_of_deprecated_ctime(self):
        from filepilot.duplicates import _signature

        original = dict(
            st_dev=1, st_ino=2, st_size=10, st_mtime_ns=100, st_ctime_ns=90, st_birthtime_ns=90
        )
        handle = {**original, "st_ctime_ns": 100}
        with patch("filepilot.duplicates.os.name", "nt"):
            self.assertEqual(
                _signature(SimpleNamespace(**original)), _signature(SimpleNamespace(**handle))
            )
            self.assertNotEqual(
                _signature(SimpleNamespace(**original)),
                _signature(SimpleNamespace(**{**handle, "st_birthtime_ns": 91})),
            )

    def test_empty_files_form_a_group_with_zero_logical_bytes(self):
        self.file("empty-a", b"")
        self.file("empty-b", b"")
        report = find_duplicates(self.root).to_dict()
        self.assertEqual(report["groups"][0]["size"], 0)
        self.assertEqual(report["groups"][0]["sha256"], hashlib.sha256(b"").hexdigest())
        self.assertEqual(report["summary"]["duplicate_files"], 1)
        self.assertEqual(report["summary"]["redundant_bytes"], 0)

    def test_empty_folder_is_read_only(self):
        report = find_duplicates(self.root)
        self.assertEqual(report.groups, ())
        self.assertEqual(report.scanned_files, 0)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_hidden_internal_temporary_and_nested_files_are_skipped(self):
        self.file("a")
        self.file("b")
        for name in (".hidden", "download.PART", "file.tmp", "archive.crdownload"):
            self.file(name)
        for name in ("nested", ".filepilot"):
            directory = self.root / name
            directory.mkdir()
            (directory / "copy").write_bytes(b"same bytes")
        report = find_duplicates(self.root)
        self.assertEqual(report.groups[0].files, ("a", "b"))
        self.assertEqual(len(report.skipped), 6)
        self.assertEqual(report.scanned_files, 2)

    def test_hard_link_aliases_do_not_inflate_groups_or_logical_bytes(self):
        first = self.file("a")
        os.link(first, self.root / "alias")
        self.file("b")
        report = find_duplicates(self.root).to_dict()
        self.assertEqual(report["groups"][0]["files"], ["a", "b"])
        self.assertEqual(report["summary"]["redundant_bytes"], 10)
        self.assertEqual(report["summary"]["scanned_files"], 2)
        self.assertIn("hard-link alias", report["skipped"][0]["reason"])

    def test_only_hard_links_are_not_reported_as_independent_copies(self):
        first = self.file("a")
        os.link(first, self.root / "b")
        report = find_duplicates(self.root)
        self.assertEqual(report.groups, ())
        self.assertEqual(report.hashed_files, 0)

    def test_large_files_are_hashed_in_bounded_chunks(self):
        content = b"01234567" * (1024 * 1024 // 8 + 3)
        self.file("a", content)
        self.file("b", content)
        real_sha256 = hashlib.sha256
        updates = []

        def tracked_hash():
            actual = real_sha256()

            class Tracked:
                def update(self, block):
                    updates.append(len(block))
                    actual.update(block)

                def hexdigest(self):
                    return actual.hexdigest()

            return Tracked()

        with patch("filepilot.duplicates.hashlib.sha256", side_effect=tracked_hash):
            report = find_duplicates(self.root)
        self.assertEqual(report.groups[0].sha256, real_sha256(content).hexdigest())
        self.assertLessEqual(max(updates), 1024 * 1024)
        self.assertGreater(len(updates), 2)

    def test_read_failure_is_partial_and_other_groups_are_retained(self):
        from filepilot.duplicates import _hash_file

        for name in ("a", "b", "locked"):
            self.file(name)

        def fail_one(root, candidate):
            if candidate.source == "locked":
                raise PermissionError("test: locked file")
            return _hash_file(root, candidate)

        with patch("filepilot.duplicates._hash_file", side_effect=fail_one):
            report = find_duplicates(self.root).to_dict()
        self.assertEqual(report["groups"][0]["files"], ["a", "b"])
        self.assertEqual(report["errors"], [{"source": "locked", "message": "test: locked file"}])
        self.assertEqual(report["summary"]["hashed_files"], 2)

    def test_changed_previously_hashed_file_is_removed_from_the_final_report(self):
        from filepilot.duplicates import _hash_file

        self.file("a")
        self.file("b")

        def change_earlier(root, candidate):
            digest = _hash_file(root, candidate)
            if candidate.source == "b":
                (root / "a").write_bytes(b"changed bytes")
            return digest

        with patch("filepilot.duplicates._hash_file", side_effect=change_earlier):
            report = find_duplicates(self.root)
        self.assertEqual(report.groups, ())
        self.assertEqual(report.errors[0].source, "a")
        self.assertIn("changed", report.errors[0].message)
        self.assertEqual(report.hashed_files, 2)

    def test_report_order_is_deterministic_across_creation_orders(self):
        for name, content in (("z", b"other"), ("b", b"same"), ("y", b"other"), ("A", b"same")):
            self.file(name, content)
        first = find_duplicates(self.root).to_dict()
        for path in list(self.root.iterdir()):
            path.unlink()
        for name, content in (("A", b"same"), ("y", b"other"), ("b", b"same"), ("z", b"other")):
            self.file(name, content)
        self.assertEqual(find_duplicates(self.root).to_dict(), first)
        self.assertEqual([group["files"] for group in first["groups"]], [["A", "b"], ["y", "z"]])

    def test_missing_or_file_root_has_a_readable_error(self):
        with self.assertRaises(OSError):
            find_duplicates(self.root / "missing")
        with self.assertRaises(FilePilotError):
            find_duplicates(self.file("not-a-folder"))


if __name__ == "__main__":
    unittest.main()
