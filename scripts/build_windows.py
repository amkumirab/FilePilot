"""Build the Windows x64 executable and its portable release bundle."""

import importlib.metadata
import os
import platform
import struct
import subprocess
import sys
from pathlib import Path

from release_bundle import create_bundle, project_version, verify_bundle

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if (
        os.name != "nt"
        or struct.calcsize("P") != 8
        or platform.machine().upper() not in {"AMD64", "X86_64"}
    ):
        raise SystemExit("Build FilePilot.exe with an x64 Python installation on Windows.")
    project_version(ROOT)
    destinations = [ROOT / "dist/windows", ROOT / "build/windows", ROOT / "dist/releases"]
    if not all(path.resolve().is_relative_to(ROOT) for path in destinations):
        raise SystemExit("Build output paths must stay within the project.")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onefile",
            "--console",
            "--noupx",
            "--name",
            "FilePilot",
            "--paths",
            str(ROOT / "src"),
            "--distpath",
            str(destinations[0]),
            "--workpath",
            str(destinations[1]),
            "--specpath",
            str(destinations[1]),
            str(ROOT / "scripts/windows_entry.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    metadata = {
        "python": platform.python_version(),
        "pyinstaller": importlib.metadata.version("pyinstaller"),
        "commit": commit,
        "source_dirty": dirty,
    }
    python_notice = (Path(sys.base_prefix) / "LICENSE.txt").read_text(encoding="utf-8")
    distribution = importlib.metadata.distribution("pyinstaller")
    copying = next(path for path in distribution.files if str(path).endswith("COPYING.txt"))
    bootloader_notice = Path(distribution.locate_file(copying)).read_text(encoding="utf-8")
    notices = (
        f"Bundled Python {platform.python_version()}\n\n{python_notice}\n\n"
        f"PyInstaller bootloader\n\n{bootloader_notice}\n"
    )
    archive = create_bundle(
        destinations[0] / "FilePilot.exe", destinations[2], ROOT, metadata, notices=notices
    )
    verify_bundle(destinations[2], project_version(ROOT))
    print(f"Created {archive}")


if __name__ == "__main__":
    main()
