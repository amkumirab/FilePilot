import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.release_bundle import create_bundle, project_version, validate_tag, verify_bundle


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src/filepilot").mkdir(parents=True)
        (self.root / "docs").mkdir()
        (self.root / "examples").mkdir()
        (self.root / "pyproject.toml").write_text('[project]\nversion="0.2.1"')
        (self.root / "src/filepilot/__init__.py").write_text('__version__ = "0.2.1"')
        (self.root / "LICENSE").write_text("Fixture license")
        (self.root / "docs/windows-quickstart.txt").write_text("FilePilot @VERSION@")
        (self.root / "examples/rules.toml").write_text('[[rules]]\nname="all"\ntarget="Files"')
        self.exe = self.root / "FilePilot.exe"
        self.exe.write_bytes(b"fixture executable bytes")
        self.output = self.root / "release"

    def bundle(self):
        return create_bundle(
            self.exe,
            self.output,
            self.root,
            {"python": "3.13", "commit": "a" * 40, "pyinstaller": "6.22.3"},
            notices="Fixture third-party notices",
        )

    def refresh_checksum(self, archive):
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (self.output / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n")

    def test_project_and_module_versions_must_agree(self):
        self.assertEqual(project_version(self.root), "0.2.1")
        (self.root / "src/filepilot/__init__.py").write_text('__version__ = "0.2.0"')
        with self.assertRaises(ValueError):
            project_version(self.root)

    def test_tag_must_match_the_validated_version(self):
        validate_tag("v0.2.1", "0.2.1")
        for tag in ("v0.2.0", "0.2.1", "v0.2.1/../../bad", "v0.2.1-rc1"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                validate_tag(tag, "0.2.1")

    def test_unsafe_and_unsupported_versions_are_rejected(self):
        for version in ("../outside", "01.2.3", "0.2", "0.2.1-rc1"):
            (self.root / "pyproject.toml").write_text(f'[project]\nversion="{version}"')
            with self.subTest(version=version), self.assertRaises(ValueError):
                project_version(self.root)

    def test_missing_module_version_is_rejected(self):
        (self.root / "src/filepilot/__init__.py").write_text('"""No version."""')
        with self.assertRaises(ValueError):
            project_version(self.root)

    def test_bundle_includes_only_the_expected_files_and_versioned_instructions(self):
        archive = self.bundle()
        result = verify_bundle(self.output, "0.2.1")
        self.assertEqual(result["version"], "0.2.1")
        self.assertEqual(result["target"], "windows-x64")
        with zipfile.ZipFile(archive) as package:
            root = "FilePilot-0.2.1-windows-x64/"
            self.assertEqual(package.read(root + "FilePilot.exe"), self.exe.read_bytes())
            self.assertEqual(package.read(root + "README.txt"), b"FilePilot 0.2.1")
            self.assertEqual(package.read(root + "VERSION.txt"), b"0.2.1\n")
            self.assertEqual(len(package.namelist()), 7)

    def test_bundle_checksum_detects_modified_downloads(self):
        archive = self.bundle()
        with archive.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaises(ValueError):
            verify_bundle(self.output, "0.2.1")

    def test_checksum_cannot_select_an_outside_path(self):
        self.bundle()
        (self.output / "SHA256SUMS.txt").write_text("a" * 64 + "  ../outside.zip\n")
        with self.assertRaises(ValueError):
            verify_bundle(self.output, "0.2.1")

    def test_extra_archive_entries_are_rejected_even_with_a_valid_checksum(self):
        archive = self.bundle()
        with zipfile.ZipFile(archive, "a") as package:
            package.writestr("../outside.txt", "not allowed")
        self.refresh_checksum(archive)
        with self.assertRaises(ValueError):
            verify_bundle(self.output, "0.2.1")

    def test_mismatched_build_metadata_is_rejected(self):
        archive = self.bundle()
        with zipfile.ZipFile(archive) as package:
            contents = {info.filename: package.read(info) for info in package.infolist()}
        name = "FilePilot-0.2.1-windows-x64/BUILD.json"
        contents[name] = json.dumps({"version": "0.2.0", "target": "windows-x64"}).encode()
        with zipfile.ZipFile(archive, "w") as package:
            for member, content in contents.items():
                package.writestr(member, content)
        self.refresh_checksum(archive)
        with self.assertRaises(ValueError):
            verify_bundle(self.output, "0.2.1")

    def test_empty_executable_is_rejected(self):
        self.exe.write_bytes(b"")
        with self.assertRaises(ValueError):
            self.bundle()

    def test_missing_resources_prevent_packaging(self):
        (self.root / "LICENSE").unlink()
        with self.assertRaises(OSError):
            self.bundle()

    def test_publication_requires_a_clean_build(self):
        self.bundle()
        with self.assertRaises(ValueError):
            verify_bundle(self.output, "0.2.1", require_clean=True)
        create_bundle(
            self.exe,
            self.output,
            self.root,
            {"source_dirty": False},
            notices="Fixture third-party notices",
        )
        verify_bundle(self.output, "0.2.1", require_clean=True)

    def test_publication_commit_must_match(self):
        self.bundle()
        verify_bundle(self.output, "0.2.1", expected_commit="a" * 40)
        with self.assertRaises(ValueError):
            verify_bundle(self.output, "0.2.1", expected_commit="b" * 40)

    def test_missing_dependency_notices_prevent_packaging(self):
        with self.assertRaises(ValueError):
            create_bundle(self.exe, self.output, self.root, {}, notices="")

    def test_symbolic_link_members_are_rejected(self):
        import stat

        archive = self.bundle()
        with zipfile.ZipFile(archive) as package:
            contents = {info.filename: package.read(info) for info in package.infolist()}
        with zipfile.ZipFile(archive, "w") as package:
            for name, content in contents.items():
                info = zipfile.ZipInfo(name)
                if name.endswith("FilePilot.exe"):
                    info.create_system = 3
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                package.writestr(info, content)
        self.refresh_checksum(archive)
        with self.assertRaises(ValueError):
            verify_bundle(self.output, "0.2.1")


if __name__ == "__main__":
    unittest.main()
