"""Build deterministic move plans without changing the filesystem."""

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .config import DEFAULT_RULES, Rule
from .paths import FilePilotError, is_link, root_directory, safe_path

INCOMPLETE = {".part", ".partial", ".crdownload", ".download", ".tmp", ".temp"}


@dataclass(frozen=True)
class Move:
    source: str
    target: str
    rule: str
    size: int
    modified_ns: int


@dataclass(frozen=True)
class Skip:
    source: str
    reason: str


@dataclass(frozen=True)
class Plan:
    root: Path
    moves: tuple[Move, ...]
    skipped: tuple[Skip, ...]

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "moves": [asdict(move) for move in self.moves],
            "skipped": [asdict(skip) for skip in self.skipped],
        }


def _unique_target(root: Path, relative: str, reserved: set[str]) -> str:
    target = safe_path(root, relative)
    original = target
    number = 2
    # Case folding keeps plans portable to Windows, even when built on Linux.
    siblings = (
        {item.name.casefold() for item in target.parent.iterdir()}
        if (target.parent.is_dir())
        else set()
    )
    while (
        target.name.casefold() in siblings
        or target.relative_to(root).as_posix().casefold() in reserved
    ):
        target = original.with_name(f"{original.stem} ({number}){original.suffix}")
        number += 1
    return target.relative_to(root).as_posix()


def build_plan(
    root: Path, rules: tuple[Rule, ...] = DEFAULT_RULES, *, exclude: tuple[Path, ...] = ()
) -> Plan:
    root = root_directory(root)
    excluded = {path.resolve() for path in exclude}
    moves, skipped = [], []
    reserved: set[str] = set()
    for source in sorted(root.iterdir(), key=lambda path: (path.name.casefold(), path.name)):
        reason = ""
        if is_link(source):
            reason = "link or junction"
        elif source.name.startswith("."):
            reason = "hidden or internal"
        elif not source.is_file():
            reason = "directory or non-regular file"
        elif source.resolve() in excluded:
            reason = "configuration file"
        elif source.suffix.casefold() in INCOMPLETE:
            reason = "incomplete download or temporary file"
        rule = next((rule for rule in rules if rule.matches(source)), None) if not reason else None
        if not reason and rule is None:
            reason = "no matching rule"
        if reason:
            skipped.append(Skip(source.name, reason))
            continue
        assert rule is not None
        safe_path(root, source.name)
        info = source.stat()
        date = datetime.fromtimestamp(info.st_mtime)
        fields = dict(
            name=source.name,
            stem=source.stem,
            ext=source.suffix,
            year=f"{date.year:04}",
            month=f"{date.month:02}",
            day=f"{date.day:02}",
        )
        directory = rule.target.format(**fields)
        filename = rule.rename.format(**fields) if rule.rename else source.name
        relative = f"{directory}/{filename}"
        safe_path(root, relative)
        parent = root / directory
        if any(
            path.exists() and not path.is_dir()
            for path in (parent, *parent.parents)
            if path.is_relative_to(root)
        ):
            raise FilePilotError(f"Target directory is occupied by a file: {directory}")
        target = _unique_target(root, relative, reserved)
        reserved.add(target.casefold())
        moves.append(Move(source.name, target, rule.name, info.st_size, info.st_mtime_ns))
    return Plan(root, tuple(moves), tuple(skipped))
