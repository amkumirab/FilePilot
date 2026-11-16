"""Versioned, strictly validated snapshots of reviewed file moves."""

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .engine import validate_plan
from .paths import FilePilotError, root_directory, safe_path
from .planner import Move, Plan, Skip

MAX_PLAN_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class SavedPlan:
    plan: Plan
    hashes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "format": "filepilot-plan",
            "version": 1,
            **self.plan.to_dict(),
            "moves": [
                {**asdict(move), "sha256": digest}
                for move, digest in zip(self.plan.moves, self.hashes, strict=True)
            ],
        }


def _fields(value, fields: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise FilePilotError("Invalid saved-plan fields.")


def _check_location(plan: Plan, path: Path) -> None:
    resolved = path.expanduser().resolve()
    if not resolved.is_relative_to(plan.root):
        return
    relative = resolved.relative_to(plan.root).as_posix().casefold()
    if relative == ".filepilot" or relative.startswith(".filepilot/"):
        raise FilePilotError("Plans cannot be stored in the reserved history directory.")
    if any(
        relative == move.source.casefold()
        or relative == move.target.casefold()
        or move.target.casefold().startswith(relative + "/")
        for move in plan.moves
    ):
        raise FilePilotError("The plan file conflicts with a planned source or destination.")


def save_plan(plan: Plan, output: Path) -> SavedPlan:
    _check_location(plan, output)
    saved = SavedPlan(plan, validate_plan(plan))
    content = (json.dumps(saved.to_dict(), ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    if len(content) > MAX_PLAN_BYTES:
        raise FilePilotError("Saved plans must not exceed 10 MiB.")
    # Exclusive creation also rejects an existing symlink; never replace user data.
    with output.expanduser().open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return saved


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise FilePilotError(f"Duplicate JSON key in saved plan: {key!r}")
        result[key] = value
    return result


def _parse(document) -> SavedPlan:
    _fields(document, {"format", "version", "root", "moves", "skipped"})
    if (
        document["format"] != "filepilot-plan"
        or type(document["version"]) is not int
        or document["version"] != 1
    ):
        raise FilePilotError("Unsupported saved-plan format or version.")
    root_text = document["root"]
    if not isinstance(root_text, str) or not Path(root_text).is_absolute():
        raise FilePilotError("A saved plan requires an absolute root directory.")
    root = root_directory(Path(root_text))
    if str(root) != root_text:
        raise FilePilotError("The saved-plan root is not canonical; create a new plan.")
    if not isinstance(document["moves"], list) or not isinstance(document["skipped"], list):
        raise FilePilotError("Saved-plan moves and skipped entries must be arrays.")
    moves, hashes, skipped = [], [], []
    sources, targets = set(), set()
    for entry in document["moves"]:
        _fields(entry, {"source", "target", "rule", "size", "modified_ns", "sha256"})
        source, target, digest = entry["source"], entry["target"], entry["sha256"]
        safe_path(root, source)
        safe_path(root, target)
        if (
            "/" in source
            or "/" not in target
            or source.casefold() in sources
            or target.casefold() in targets
            or not isinstance(entry["rule"], str)
            or not entry["rule"]
            or type(entry["size"]) is not int
            or entry["size"] < 0
            or type(entry["modified_ns"]) is not int
            or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise FilePilotError("Invalid or duplicate saved-plan move.")
        sources.add(source.casefold())
        targets.add(target.casefold())
        moves.append(Move(source, target, entry["rule"], entry["size"], entry["modified_ns"]))
        hashes.append(digest)
    for move in moves:
        parts = move.target.casefold().split("/")
        if parts[0] in sources or any(
            "/".join(parts[:index]) in targets for index in range(1, len(parts))
        ):
            raise FilePilotError("A planned file is also a destination directory.")
    for entry in document["skipped"]:
        _fields(entry, {"source", "reason"})
        if not all(isinstance(entry[key], str) and entry[key] for key in ("source", "reason")):
            raise FilePilotError("Invalid skipped entry in saved plan.")
        skipped.append(Skip(entry["source"], entry["reason"]))
    return SavedPlan(Plan(root, tuple(moves), tuple(skipped)), tuple(hashes))


def load_plan(path: Path) -> SavedPlan:
    path = path.expanduser()
    if not path.is_file():
        raise FilePilotError(f"Not a regular saved-plan file: {path}")
    with path.open("rb") as stream:
        content = stream.read(MAX_PLAN_BYTES + 1)
    if len(content) > MAX_PLAN_BYTES:
        raise FilePilotError("Saved plans must not exceed 10 MiB.")
    try:
        document = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise FilePilotError("Unreadable saved-plan JSON.") from exc
    saved = _parse(document)
    _check_location(saved.plan, path)
    return saved
