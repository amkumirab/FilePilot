"""Polling and stable-file tracking for foreground folder watching."""

import math
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

from .config import DEFAULT_RULES, Rule
from .engine import execute
from .journal import locked
from .paths import FilePilotError, is_hidden, is_link, root_directory
from .planner import INCOMPLETE, Plan, build_plan


def _positive_seconds(value: float) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise FilePilotError("Watch timing values must be positive, finite numbers.")


@dataclass(frozen=True)
class WatchOptions:
    interval: float = 1.0
    settle: float = 2.0
    max_cycles: int | None = None

    def __post_init__(self) -> None:
        _positive_seconds(self.interval)
        _positive_seconds(self.settle)
        if self.max_cycles is not None and (
            not isinstance(self.max_cycles, int)
            or isinstance(self.max_cycles, bool)
            or self.max_cycles <= 0
        ):
            raise FilePilotError("max_cycles must be a positive integer.")


@dataclass
class _Observed:
    signature: tuple[int, ...]
    since: float
    handled: bool = False
    attempts: int = 0
    retry_at: float = -math.inf


def _signature(source: Path) -> tuple[int, ...]:
    info = source.stat(follow_symlinks=False)
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class FolderWatcher:
    def __init__(
        self,
        root: Path,
        rules: tuple[Rule, ...] = DEFAULT_RULES,
        *,
        settle: float = 2.0,
        exclude: tuple[Path, ...] = (),
        apply: bool = False,
    ):
        _positive_seconds(settle)
        self.root = root_directory(root)
        info = self.root.stat()
        self._root_id = info.st_dev, info.st_ino
        self.rules = rules
        self.settle = settle
        self.apply = apply
        self.exclude = tuple(path.resolve() for path in exclude)
        self._observed: dict[str, _Observed] = {}
        self._scan_errors: set[tuple[str, str]] = set()

    @property
    def has_failures(self) -> bool:
        return bool(self._scan_errors) or any(
            state.attempts and not state.handled for state in self._observed.values()
        )

    def _snapshot(self) -> tuple[dict[str, tuple[int, ...]], list[dict]]:
        info = self.root.stat()
        if is_link(self.root) or (info.st_dev, info.st_ino) != self._root_id:
            raise FilePilotError(
                "The watched folder was replaced; restart with the intended folder."
            )
        snapshot, events, errors = {}, [], set()
        for source in sorted(self.root.iterdir(), key=lambda path: path.name):
            try:
                if (
                    is_link(source)
                    or is_hidden(source)
                    or not source.is_file()
                    or source.suffix.casefold() in INCOMPLETE
                    or source.resolve() in self.exclude
                    or not any(rule.matches(source) for rule in self.rules)
                ):
                    continue
                snapshot[source.name] = _signature(source)
            except FileNotFoundError:
                continue  # A producer may rename a file between directory listing and stat.
            except OSError as exc:
                key = source.name, str(exc)
                errors.add(key)
                if key not in self._scan_errors:
                    events.append({"event": "error", "source": source.name, "message": str(exc)})
        self._scan_errors = errors
        return snapshot, events

    def poll(self, now: float | None = None) -> list[dict]:
        now = monotonic() if now is None else now
        snapshot, events = self._snapshot()
        for name in self._observed.keys() - snapshot.keys():
            del self._observed[name]
        for name, signature in snapshot.items():
            previous = self._observed.get(name)
            if previous is None or previous.signature != signature:
                self._observed[name] = _Observed(signature, now)
        ready = frozenset(
            name
            for name, state in self._observed.items()
            if not state.handled
            and state.attempts < 3
            and now - state.since >= self.settle
            and now >= state.retry_at
        )
        if not ready:
            return events
        plan = build_plan(self.root, self.rules, exclude=self.exclude, include=ready)
        moves = []
        for move in plan.moves:
            try:
                signature = _signature(self.root / move.source)
            except FileNotFoundError:
                self._observed.pop(move.source, None)
                continue
            if signature != self._observed[move.source].signature:
                self._observed[move.source] = _Observed(signature, now)
            else:
                moves.append(move)
        if not moves:
            return events
        selected = Plan(self.root, tuple(moves), plan.skipped)
        if self.apply:
            run = execute(selected)
            for entry in run["entries"]:
                state = self._observed[entry["source"]]
                state.attempts += 1
                state.handled = entry["status"] == "moved"
                state.retry_at = now + self.settle
            events.append({"event": "run", "run": run})
        else:
            for move in moves:
                self._observed[move.source].handled = True
            events.append({"event": "preview", "plan": selected.to_dict()})
        return events


def watch_folder(
    root: Path,
    rules: tuple[Rule, ...] = DEFAULT_RULES,
    *,
    apply: bool = False,
    options: WatchOptions | None = None,
    exclude: tuple[Path, ...] = (),
    emit: Callable[[dict], None] | None = None,
) -> int:
    options = WatchOptions() if options is None else options
    watcher = FolderWatcher(root, rules, settle=options.settle, exclude=exclude, apply=apply)
    guard = locked(watcher.root, name="watch.lock") if apply else nullcontext()
    cycles = batches = moved = 0
    reason = "limit"

    def notify(event: dict) -> None:
        if emit is not None:
            emit(event)

    with guard:
        try:
            notify(
                {
                    "event": "started",
                    "folder": str(watcher.root),
                    "apply": apply,
                    "interval": options.interval,
                    "settle": options.settle,
                }
            )
            while True:
                for event in watcher.poll():
                    if event["event"] == "run":
                        batches += 1
                        moved += sum(
                            entry["status"] == "moved" for entry in event["run"]["entries"]
                        )
                    notify(event)
                cycles += 1
                if options.max_cycles is not None and cycles >= options.max_cycles:
                    break
                sleep(options.interval)
        except KeyboardInterrupt:
            reason = "interrupted"
        notify(
            {
                "event": "stopped",
                "reason": reason,
                "cycles": cycles,
                "batches": batches,
                "moved": moved,
                "failed": watcher.has_failures,
            }
        )
    return 130 if reason == "interrupted" else int(watcher.has_failures)
