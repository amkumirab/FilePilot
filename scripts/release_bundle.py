"""Create and verify the portable Windows release archive."""

import argparse
import ast
import hashlib
import json
import re
import stat
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = frozenset(
    {
        "FilePilot.exe",
        "README.txt",
        "LICENSE",
        "filepilot.toml",
        "VERSION.txt",
        "BUILD.json",
        "THIRD_PARTY_NOTICES.txt",
    }
)
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")


def _version(value: str) -> str:
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError("Version must have three numeric components, for example 0.2.1.")
    return value


def project_version(root: Path = ROOT) -> str:
    with (root / "pyproject.toml").open("rb") as stream:
        version = _version(tomllib.load(stream)["project"]["version"])
    tree = ast.parse((root / "src/filepilot/__init__.py").read_text(encoding="utf-8"))
    values = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
    ]
    if values != [version]:
        raise ValueError("Package metadata and filepilot.__version__ must agree.")
    return version


def validate_tag(tag: str, version: str) -> None:
    if tag != f"v{_version(version)}":
        raise ValueError(f"Expected tag v{version}, got {tag!r}.")


def create_bundle(
    executable: Path, output: Path, root: Path, build_info: dict, *, notices: str
) -> Path:
    version = project_version(root)
    binary = executable.read_bytes()
    if executable.name != "FilePilot.exe" or not binary:
        raise ValueError("A nonempty FilePilot.exe is required.")
    if not notices.strip():
        raise ValueError("Bundled interpreter and bootloader license notices are required.")
    contents = {
        "FilePilot.exe": binary,
        "README.txt": (root / "docs/windows-quickstart.txt")
        .read_text(encoding="utf-8")
        .replace("@VERSION@", version)
        .encode("utf-8"),
        "LICENSE": (root / "LICENSE").read_bytes(),
        "THIRD_PARTY_NOTICES.txt": notices.encode("utf-8"),
        "filepilot.toml": (root / "examples/rules.toml").read_bytes(),
        "VERSION.txt": f"{version}\n".encode(),
        "BUILD.json": (
            json.dumps(
                {**build_info, "version": version, "target": "windows-x64"},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode(),
    }
    output.mkdir(parents=True, exist_ok=True)
    prefix = f"FilePilot-{version}-windows-x64"
    archive = output / f"{prefix}.zip"
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as package:
        for name, content in sorted(contents.items()):
            info = zipfile.ZipInfo(f"{prefix}/{name}")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            package.writestr(info, content)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS.txt").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii", newline="\n"
    )
    return archive


def verify_bundle(
    directory: Path,
    version: str,
    *,
    require_clean: bool = False,
    expected_commit: str | None = None,
) -> dict:
    prefix = f"FilePilot-{_version(version)}-windows-x64"
    archive = directory / f"{prefix}.zip"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if (directory / "SHA256SUMS.txt").read_text(
        encoding="ascii"
    ).strip() != f"{digest}  {archive.name}":
        raise ValueError("Release checksum does not match the expected ZIP.")
    with zipfile.ZipFile(archive) as package:
        infos = package.infolist()
        expected = {f"{prefix}/{name}" for name in FILES}
        if len(infos) != len(expected) or {item.filename for item in infos} != expected:
            raise ValueError("Release ZIP contains missing, duplicate, or unexpected files.")
        if any(stat.S_ISLNK(item.external_attr >> 16) for item in infos):
            raise ValueError("Release ZIP must not contain symbolic links.")
        if sum(item.file_size for item in infos) > 256 * 1024 * 1024:
            raise ValueError("Release ZIP exceeds the expected size limit.")
        metadata = json.loads(package.read(f"{prefix}/BUILD.json"))
        if (
            not isinstance(metadata, dict)
            or metadata.get("version") != version
            or metadata.get("target") != "windows-x64"
            or package.read(f"{prefix}/VERSION.txt") != f"{version}\n".encode()
            or not package.read(f"{prefix}/FilePilot.exe")
        ):
            raise ValueError("Release version or build metadata is inconsistent.")
        if require_clean and metadata.get("source_dirty") is not False:
            raise ValueError("Published releases require a clean source checkout.")
        if expected_commit is not None and (
            not re.fullmatch(r"[0-9a-f]{40}", expected_commit)
            or metadata.get("commit") != expected_commit
        ):
            raise ValueError("Release bundle was not built from the expected commit.")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("version", "verify"))
    parser.add_argument("--directory", type=Path, default=ROOT / "dist/releases")
    parser.add_argument("--tag")
    parser.add_argument("--commit")
    args = parser.parse_args()
    try:
        version = project_version()
        if args.tag:
            validate_tag(args.tag, version)
        if args.command == "verify":
            verify_bundle(
                args.directory, version, require_clean=bool(args.tag), expected_commit=args.commit
            )
        print(version)
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
