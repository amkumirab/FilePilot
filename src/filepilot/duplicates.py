"""Size-first duplicate reports without modifying the selected folder."""

import hashlib
import os
import stat
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import FilePilotError, is_hidden, is_link, root_directory, safe_path
from .planner import INCOMPLETE, Skip

CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DuplicateGroup:
    sha256: str
    size: int
    files: tuple[str, ...]

    @property
    def redundant_bytes(self) -> int:
        return self.size * (len(self.files) - 1)


@dataclass(frozen=True)
class ScanError:
    source: str
    message: str


@dataclass(frozen=True)
class DuplicateReport:
    root: Path
    groups: tuple[DuplicateGroup, ...]
    scanned_files: int
    hashed_files: int
    skipped: tuple[Skip, ...]
    errors: tuple[ScanError, ...]

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "root": str(self.root),
            "groups": [
                {
                    "sha256": group.sha256,
                    "size": group.size,
                    "files": list(group.files),
                    "redundant_bytes": group.redundant_bytes,
                }
                for group in self.groups
            ],
            "summary": {
                "scanned_files": self.scanned_files,
                "hashed_files": self.hashed_files,
                "duplicate_groups": len(self.groups),
                "duplicate_files": sum(len(group.files) - 1 for group in self.groups),
                "redundant_bytes": sum(group.redundant_bytes for group in self.groups),
            },
            "skipped": [asdict(entry) for entry in self.skipped],
            "errors": [asdict(entry) for entry in self.errors],
        }


@dataclass(frozen=True)
class _Candidate:
    source: str
    info: os.stat_result


def _signature(info: os.stat_result) -> tuple[int, ...]:
    # Windows ctime is deprecated and can differ between stat and fstat on 3.12.
    stamp = info.st_birthtime_ns if os.name == "nt" else info.st_ctime_ns
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, stamp


def _check(candidate: _Candidate, info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or _signature(info) != _signature(candidate.info):
        raise FilePilotError(f"File changed during duplicate scan: {candidate.source}")


def _unchanged(root: Path, candidate: _Candidate) -> Path:
    path = safe_path(root, candidate.source)
    _check(candidate, path.stat(follow_symlinks=False))
    return path


def _readonly_open(path: str, flags: int) -> int:
    # Prevent a replaced FIFO from blocking, and refuse final symlinks on POSIX.
    return os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))


def _hash_file(root: Path, candidate: _Candidate) -> str:
    path = _unchanged(root, candidate)
    digest = hashlib.sha256()
    with open(path, "rb", opener=_readonly_open) as stream:
        _check(candidate, os.fstat(stream.fileno()))
        remaining = candidate.info.st_size
        while remaining:
            block = stream.read(min(CHUNK_BYTES, remaining))
            if not block:
                raise FilePilotError(f"File changed during duplicate scan: {candidate.source}")
            digest.update(block)
            remaining -= len(block)
        if stream.read(1):
            raise FilePilotError(f"File changed during duplicate scan: {candidate.source}")
        _check(candidate, os.fstat(stream.fileno()))
    _unchanged(root, candidate)
    return digest.hexdigest()


def find_duplicates(folder: Path) -> DuplicateReport:
    root = root_directory(folder)
    info = root.stat()
    root_id = info.st_dev, info.st_ino
    buckets: dict[int, list[_Candidate]] = defaultdict(list)
    identities: dict[tuple[int, int], str] = {}
    skipped, errors = [], []
    for source in sorted(root.iterdir(), key=lambda path: (path.name.casefold(), path.name)):
        try:
            if is_link(source):
                skipped.append(Skip(source.name, "link or junction"))
                continue
            if is_hidden(source):
                skipped.append(Skip(source.name, "hidden or internal"))
                continue
            info = source.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                skipped.append(Skip(source.name, "directory or non-regular file"))
                continue
            if source.suffix.casefold() in INCOMPLETE:
                skipped.append(Skip(source.name, "incomplete download or temporary file"))
                continue
            safe_path(root, source.name)
            identity = info.st_dev, info.st_ino
            if info.st_ino and identity in identities:
                skipped.append(Skip(source.name, f"hard-link alias of {identities[identity]!r}"))
                continue
            identities[identity] = source.name
            buckets[info.st_size].append(_Candidate(source.name, info))
        except (OSError, FilePilotError) as exc:
            errors.append(ScanError(source.name, str(exc)))
    hashed = []
    for candidates in buckets.values():
        if len(candidates) < 2:
            continue
        for candidate in candidates:
            try:
                hashed.append((candidate, _hash_file(root, candidate)))
            except (OSError, FilePilotError) as exc:
                errors.append(ScanError(candidate.source, str(exc)))
    matches: dict[tuple[int, str], list[str]] = defaultdict(list)
    for candidate, digest in hashed:
        try:
            _unchanged(root, candidate)
        except (OSError, FilePilotError) as exc:
            errors.append(ScanError(candidate.source, str(exc)))
        else:
            matches[candidate.info.st_size, digest].append(candidate.source)
    info = root.stat(follow_symlinks=False)
    if is_link(root) or not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != root_id:
        raise FilePilotError("The folder changed during duplicate scanning.")
    groups = [
        DuplicateGroup(digest, size, tuple(files))
        for (size, digest), files in matches.items()
        if len(files) > 1
    ]
    groups.sort(key=lambda group: (group.files[0].casefold(), group.files[0]))
    errors.sort(key=lambda entry: (entry.source.casefold(), entry.source))
    return DuplicateReport(
        root,
        tuple(groups),
        sum(map(len, buckets.values())),
        len(hashed),
        tuple(skipped),
        tuple(errors),
    )
