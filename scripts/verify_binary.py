"""Exercise the standalone executable outside Python's import and PATH environment."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from release_bundle import ROOT, project_version, verify_bundle


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def exercise(executable: Path, work: Path, environment: dict[str, str], version: str) -> None:
    executable = executable.resolve(strict=True)

    def run(*args, expected=0):
        result = subprocess.run(
            [str(executable), *map(str, args)],
            cwd=work,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        require(result.returncode == expected, f"{args}: exit {result.returncode}: {result.stderr}")
        return result.stdout

    require(run("--version").strip() == f"FilePilot {version}", "Wrong executable version")
    require("watch" in run("--help"), "Watch command missing from executable")
    run("scan", work / "missing", expected=2)
    inbox = work / "inbox با فاصله"
    inbox.mkdir()
    originals = {"گزارش.csv": b"a,b\n1,2\n", "empty.txt": b""}
    for name, content in originals.items():
        (inbox / name).write_bytes(content)
    config = inbox / "rules.toml"
    config.write_text('[[rules]]\nname="all"\ntarget="Sorted"', encoding="utf-8")
    preview = json.loads(run("scan", inbox, "--config", config, "--json"))
    require(len(preview["moves"]) == 2, "Custom rules or Unicode input were not recognized")
    require(not (inbox / ".filepilot").exists(), "Preview wrote state")
    result = json.loads(run("organize", inbox, "--config", config, "--apply", "--json"))
    require(result["status"] == "completed", "Standalone organization failed")
    require(config.is_file(), "The config file was moved")
    recorded = json.loads(run("history", inbox, "--json"))
    require(recorded[0]["id"] == result["id"], "History did not retain the run")
    restore_preview = json.loads(run("undo", inbox, "--json"))
    require(restore_preview["preview"], "Undo preview did not report its mode")
    require(
        json.loads(run("undo", inbox, "--apply", "--json"))["status"] == "undone",
        "Standalone undo failed",
    )
    for name, content in originals.items():
        require((inbox / name).read_bytes() == content, f"Content changed after undo: {name}")
    plan_path = work / "reviewed plan.json"
    saved = json.loads(run("plan", inbox, "--config", config, "--output", plan_path, "--json"))
    require(saved["version"] == 1 and len(saved["moves"]) == 2, "Saved-plan creation failed")
    require(json.loads(run("apply", plan_path, "--json"))["preview"], "Plan preview failed")
    changed = inbox / "گزارش.csv"
    info = changed.stat()
    changed.write_bytes(b"A,B\n1,2\n")
    os.utime(changed, ns=(info.st_atime_ns, info.st_mtime_ns))
    run("apply", plan_path, "--apply", expected=2)
    require(all((inbox / name).is_file() for name in originals), "Stale batch moved a file")
    changed.write_bytes(originals[changed.name])
    os.utime(changed, ns=(info.st_atime_ns, info.st_mtime_ns))
    require(
        json.loads(run("apply", plan_path, "--apply", "--json"))["status"] == "completed",
        "Saved-plan execution failed",
    )
    run("undo", inbox, "--apply")
    for name, content in originals.items():
        require((inbox / name).read_bytes() == content, f"Saved-plan undo changed bytes: {name}")
    duplicates = work / "duplicates با فاصله"
    duplicates.mkdir()
    samples = {
        "a.txt": b"same",
        "نسخه.bin": b"same",
        "different.xyz": b"diff",
        "empty-a": b"",
        "empty-b": b"",
        "unique": b"unique-size",
        "download.PART": b"same",
    }
    for name, content in samples.items():
        (duplicates / name).write_bytes(content)
    os.link(duplicates / "a.txt", duplicates / "alias.txt")
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in duplicates.iterdir()
    }
    duplicate_report = json.loads(run("duplicates", duplicates, "--json"))
    require(duplicate_report["summary"]["duplicate_groups"] == 2, "Wrong duplicate groups")
    require(duplicate_report["summary"]["duplicate_files"] == 2, "Hard links inflated copies")
    require(duplicate_report["summary"]["redundant_bytes"] == 4, "Wrong logical duplicate bytes")
    require(duplicate_report["summary"]["hashed_files"] == 5, "Size-first hashing failed")
    require(not duplicate_report["errors"], "Duplicate scan reported file errors")
    require("Read-only" in run("duplicates", duplicates), "Human duplicate report failed")
    run("duplicates", duplicates, "--apply", expected=2)
    after = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in duplicates.iterdir()
    }
    require(
        before == after and not (duplicates / ".filepilot").exists(), "Duplicate scan wrote data"
    )
    nested = duplicates / "nested"
    nested.mkdir()
    (nested / "copy.txt").write_bytes(b"same")
    recursive = json.loads(run("duplicates", duplicates, "--recursive", "--json"))
    require(not recursive["errors"], "Recursive scan reported errors")
    groups = [group["files"] for group in recursive["groups"]]
    require(
        ["a.txt", "nested/copy.txt", "نسخه.bin"] in groups,
        "Recursive scan did not group files across folders",
    )
    for script in ("demo.py", "watch_demo.py"):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--executable", str(executable)],
            cwd=work,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        require(result.returncode == 0, f"{script}: {result.stdout}\n{result.stderr}")
        print(result.stdout.strip())
    print(
        f"Standalone FilePilot {version}: Unicode paths, custom rules, history, undo, "
        "collisions, previews, saved plans, duplicates, stale-batch refusal, "
        "and live watching passed."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--exe", type=Path)
    source.add_argument("--bundle-dir", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Run standalone Windows tests on Windows.")
    version = project_version()
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() not in {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}
    }
    environment["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    environment["PYTHONIOENCODING"] = "utf-8"
    parent = ROOT / ".demo/windows-smoke"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="portable test فایل-", dir=parent) as temporary:
        work = Path(temporary).resolve()
        if args.bundle_dir:
            verify_bundle(args.bundle_dir.resolve(), version)
            prefix = f"FilePilot-{version}-windows-x64"
            with zipfile.ZipFile(args.bundle_dir / f"{prefix}.zip") as package:
                package.extractall(work)
            executable = work / prefix / "FilePilot.exe"
        else:
            executable = args.exe
        exercise(executable, work, environment, version)


if __name__ == "__main__":
    main()
