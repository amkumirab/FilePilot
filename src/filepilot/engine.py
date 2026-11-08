"""Execute plans and restore moves without replacing existing files."""

import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .journal import history, load_run, locked, save_run
from .paths import FilePilotError, root_directory, safe_path
from .planner import Move, Plan

__all__ = ["execute", "history", "load_run", "preview_undo", "undo"]


def _digest(path: Path) -> str:
    if not path.is_file():
        raise FilePilotError(f"Not a regular file: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _move_no_replace(source: Path, target: Path) -> None:
    if os.name == "nt":
        # Windows rename fails if the destination already exists.
        os.rename(source, target)
    else:
        # POSIX rename would replace an existing file. Link creation is exclusive.
        # Both paths must be on the same hard-link-capable filesystem.
        os.link(source, target, follow_symlinks=False)
        try:
            source.unlink()
        except OSError:
            if os.path.samefile(source, target):
                target.unlink()
            raise


def _unchanged(source: Path, move: Move) -> None:
    info = source.stat()
    if not source.is_file() or (info.st_size, info.st_mtime_ns) != (move.size, move.modified_ns):
        raise FilePilotError(f"File changed since preview: {move.source}")


def execute(plan: Plan) -> dict:
    if not plan.moves:
        raise FilePilotError("Nothing to organize.")
    root = root_directory(plan.root)
    now = datetime.now(UTC)
    run = {
        "version": 1,
        "id": f"{now:%Y%m%dT%H%M%S%fZ}-{uuid.uuid4().hex[:8]}",
        "root": str(root),
        "created": now.isoformat(),
        "status": "running",
        "entries": [
            {
                "source": move.source,
                "target": move.target,
                "rule": move.rule,
                "sha256": None,
                "status": "not_started",
            }
            for move in plan.moves
        ],
    }
    with locked(root):
        save_run(root, run)
        for move, entry in zip(plan.moves, run["entries"], strict=True):
            try:
                source, target = safe_path(root, move.source), safe_path(root, move.target)
                _unchanged(source, move)
                entry["sha256"] = _digest(source)
                _unchanged(source, move)
                target.parent.mkdir(parents=True, exist_ok=True)
                safe_path(root, move.target)
            except (OSError, FilePilotError) as exc:
                entry.update(status="failed", error=str(exc))
                save_run(root, run)
                continue
            entry["status"] = "pending"
            # Persistence errors must stop the run, not be treated as move errors.
            save_run(root, run)
            try:
                _move_no_replace(source, target)
            except OSError as exc:
                entry.update(status="failed", error=str(exc))
            else:
                entry["status"] = "moved"
            save_run(root, run)
        run["status"] = (
            "partial" if any(e["status"] == "failed" for e in run["entries"]) else ("completed")
        )
        save_run(root, run)
    return run


def _restorable(root: Path, entry: dict) -> tuple[Path, Path] | None:
    source, target = safe_path(root, entry["source"]), safe_path(root, entry["target"])
    if not target.exists():
        if source.is_file() and (
            entry["status"] in {"not_started", "pending", "failed"}
            or (entry["status"] == "undo_pending" and _digest(source) == entry["sha256"])
        ):
            return None  # Never moved, or an interrupted undo already finished.
        raise FilePilotError(f"Organized file is missing: {entry['target']}")
    if entry["status"] in {"not_started", "failed"}:
        raise FilePilotError(f"Ambiguous failed move; inspect both paths: {entry['source']}")
    if source.exists():
        raise FilePilotError(f"Original path is occupied: {entry['source']}")
    if _digest(target) != entry["sha256"]:
        raise FilePilotError(f"Organized file changed; leaving it in place: {entry['target']}")
    return target, source


def preview_undo(root: Path, run_id: str | None = None) -> list[dict]:
    root = root_directory(root)
    run = load_run(root, run_id)
    moves = []
    for entry in reversed(run["entries"]):
        if entry["status"] == "undone":
            continue
        move = {"source": entry["target"], "target": entry["source"], "status": "ready"}
        try:
            if _restorable(root, entry) is None:
                move["status"] = "already in place"
        except (OSError, FilePilotError) as exc:
            move.update(status="blocked", reason=str(exc))
        moves.append(move)
    return moves


def undo(root: Path, run_id: str | None = None) -> dict:
    root = root_directory(root)
    # Don't create state when there is nothing to undo.
    run = load_run(root, run_id)
    with locked(root):
        run = load_run(root, run["id"])
        run["status"] = "undoing"
        save_run(root, run)
        for entry in reversed(run["entries"]):
            if entry["status"] == "undone":
                continue
            entry.pop("error", None)
            try:
                paths = _restorable(root, entry)
            except (OSError, FilePilotError) as exc:
                entry["error"] = str(exc)
                save_run(root, run)
                continue
            if paths is None:
                entry["status"] = "undone"
                save_run(root, run)
                continue
            entry["status"] = "undo_pending"
            save_run(root, run)
            try:
                _move_no_replace(*paths)
            except OSError as exc:
                entry["error"] = str(exc)
            else:
                entry["status"] = "undone"
            save_run(root, run)
        run["status"] = (
            "undone" if all(e["status"] == "undone" for e in run["entries"]) else ("undo_partial")
        )
        save_run(root, run)
    return run
