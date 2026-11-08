"""Durable per-run JSON journals and process-scoped filesystem locks."""

import json
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from .paths import FilePilotError, root_directory, safe_path

RUN_ID = re.compile(r"\d{8}T\d{12}Z-[0-9a-f]{8}\Z")
ENTRY_STATES = {"not_started", "pending", "moved", "failed", "undo_pending", "undone"}
RUN_STATES = {"running", "completed", "partial", "undoing", "undo_partial", "undone"}


@contextmanager
def locked(root: Path):
    """The OS releases the lock even after process termination."""
    root = root_directory(root)
    state = safe_path(root, ".filepilot", internal=True)
    state.mkdir(exist_ok=True)
    lock_path = safe_path(root, ".filepilot/lock", internal=True)
    with lock_path.open("a+b") as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise FilePilotError("Another FilePilot process is using this folder.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _run_path(root: Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise FilePilotError("Invalid run ID. Use 'filepilot history FOLDER' to list IDs.")
    return safe_path(root, f".filepilot/runs/{run_id}.json", internal=True)


def save_run(root: Path, run: dict) -> None:
    path = _run_path(root, run["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = safe_path(root, f".filepilot/runs/{uuid.uuid4().hex}.tmp", internal=True)
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(run, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate(root: Path, run: dict, run_id: str) -> None:
    if (
        not isinstance(run, dict)
        or run.get("version") != 1
        or run.get("id") != run_id
        or run.get("root") != str(root)
        or not isinstance(run.get("status"), str)
        or run.get("status") not in RUN_STATES
        or not isinstance(run.get("entries"), list)
        or not isinstance(run.get("created"), str)
    ):
        raise FilePilotError(f"Invalid or relocated history journal: {run_id}")
    sources, targets = set(), set()
    for entry in run["entries"]:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("status"), str)
            or entry.get("status") not in ENTRY_STATES
        ):
            raise FilePilotError(f"Invalid history entry in {run_id}")
        source, target, digest = entry.get("source"), entry.get("target"), entry.get("sha256")
        if not isinstance(source, str) or not isinstance(target, str):
            raise FilePilotError(f"Invalid history paths in {run_id}")
        safe_path(root, source)
        safe_path(root, target)
        if (
            "/" in source
            or "/" not in target
            or source.casefold() in sources
            or target.casefold() in targets
        ):
            raise FilePilotError(f"Invalid or duplicate history paths in {run_id}")
        sources.add(source.casefold())
        targets.add(target.casefold())
        if digest is not None and (
            not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise FilePilotError(f"Invalid file hash in {run_id}")
        if entry["status"] in {"pending", "moved", "undo_pending"} and digest is None:
            raise FilePilotError(f"Missing file hash in {run_id}")


def load_run(root: Path, run_id: str | None = None) -> dict:
    root = root_directory(root)
    if run_id is None:
        candidates = [run for run in history(root) if run["status"] != "undone"]
        if not candidates:
            raise FilePilotError("No run available to undo.")
        return candidates[0]
    path = _run_path(root, run_id)
    try:
        with path.open(encoding="utf-8") as stream:
            run = json.load(stream)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise FilePilotError(f"Unreadable history journal: {run_id}") from exc
    _validate(root, run, run_id)
    return run


def history(root: Path) -> list[dict]:
    root = root_directory(root)
    directory = safe_path(root, ".filepilot/runs", internal=True)
    if not directory.exists():
        return []
    return [load_run(root, path.stem) for path in sorted(directory.glob("*.json"), reverse=True)]
