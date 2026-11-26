"""Plan reversible moves for explicitly selected duplicate copies."""

import stat
from pathlib import Path

from .engine import source_digest, validate_plan
from .paths import FilePilotError, quarantine_target, root_directory, safe_path
from .planner import Move, Plan


def plan_quarantine(
    folder: Path, keep: str, copies: list[str]
) -> tuple[Plan, Move, tuple[str, ...]]:
    root = root_directory(folder)
    if not copies or len({name.casefold() for name in (keep, *copies)}) != len(copies) + 1:
        raise FilePilotError("Select distinct paths for the kept file and each copy.")
    identities = set()
    candidates = []
    for relative in (keep, *copies):
        destination = quarantine_target(relative)
        path = safe_path(root, relative)
        if path.resolve(strict=True).relative_to(root).as_posix() != relative:
            raise FilePilotError(f"Use the exact relative path reported for this file: {relative}")
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise FilePilotError(f"Not a regular file: {relative}")
        identity = info.st_dev, info.st_ino
        if info.st_ino and identity in identities:
            raise FilePilotError(f"Hard-link aliases are not independent copies: {relative}")
        identities.add(identity)
        candidates.append(Move(relative, destination, "quarantine", info.st_size, info.st_mtime_ns))

    keeper, *moves = candidates
    if any(move.size != keeper.size for move in moves):
        raise FilePilotError("Selected copies must have the same content as the kept file.")
    plan = Plan(root, tuple(moves), ())
    digest = source_digest(root, keeper)
    hashes = (digest,) * len(moves)
    validate_plan(plan, hashes)
    return plan, keeper, hashes
