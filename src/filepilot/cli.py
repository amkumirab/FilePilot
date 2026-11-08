"""FilePilot command-line interface; moving files always requires --apply."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_RULES, EXAMPLE_CONFIG, load_rules
from .engine import execute, history, load_run, preview_undo, undo
from .paths import FilePilotError
from .planner import Plan, build_plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="FilePilot: preview, organize, and undo file moves.",
        epilog="Only immediate files are scanned. Moves require --apply.",
    )
    parser.add_argument("--version", action="version", version=f"FilePilot {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "organize", "undo", "history"):
        command = commands.add_parser(
            name,
            help={
                "scan": "Preview file organization without changing anything.",
                "organize": "Preview organization, or move files with --apply.",
                "undo": "Preview restoration, or restore files with --apply.",
                "history": "List saved runs for a folder.",
            }[name],
        )
        command.add_argument("folder", type=Path, help="Folder to organize (not recursive).")
        command.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
        if name in ("scan", "organize"):
            command.add_argument("--config", type=Path, help="Use custom TOML rules.")
        if name in ("organize", "undo"):
            command.add_argument("--apply", action="store_true", help="Actually move files.")
        if name == "undo":
            command.add_argument("--run", help="Run ID; defaults to latest run not fully undone.")
    initialize = commands.add_parser(
        "init", help="Write an example TOML config without overwriting."
    )
    initialize.add_argument("--output", type=Path, default=Path("filepilot.toml"))
    return parser


def _json(value) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2))


def _print_plan(plan: Plan, *, as_json: bool) -> None:
    if as_json:
        _json(plan.to_dict())
        return
    print(f"FilePilot | {plan.root}")
    print(f"Preview: {len(plan.moves)} move(s), {len(plan.skipped)} skipped")
    for move in plan.moves:
        print(f"  {move.source!r} -> {move.target!r} [{move.rule!r}]")
    for skipped in plan.skipped:
        print(f"  SKIP {skipped.source!r}: {skipped.reason}")
    print("No files changed. Use 'filepilot organize FOLDER --apply' with the same --config.")


def _print_run(run: dict, *, as_json: bool, restoring: bool = False) -> int:
    if as_json:
        _json(run)
    else:
        print(f"Run: {run['id']} | {run['status']}")
        for entry in run["entries"]:
            source, target = entry["source"], entry["target"]
            if restoring:
                source, target = target, source
            print(f"  {entry['status']}: {source!r} -> {target!r}")
            if entry.get("error"):
                print(f"    {entry['error']}")
    return 1 if run["status"] in {"partial", "undo_partial"} else 0


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(EXAMPLE_CONFIG)
        print(f"Created {args.output}. Use --config {args.output} with scan or organize.")
    elif args.command in ("scan", "organize"):
        rules = load_rules(args.config) if args.config else DEFAULT_RULES
        plan = build_plan(args.folder, rules, exclude=(args.config,) if args.config else ())
        if args.command == "organize" and args.apply and plan.moves:
            return _print_run(execute(plan), as_json=args.json)
        _print_plan(plan, as_json=args.json)
    elif args.command == "history":
        runs = history(args.folder)
        if args.json:
            _json(runs)
        elif not runs:
            print("No saved runs for this folder.")
        else:
            for run in runs:
                print(f"{run['id']} | {run['status']} | {len(run['entries'])} file(s)")
    elif args.command == "undo":
        if args.apply:
            return _print_run(undo(args.folder, args.run), as_json=args.json, restoring=True)
        run = load_run(args.folder, args.run)
        preview = preview_undo(args.folder, run["id"])
        if args.json:
            _json({"id": run["id"], "preview": True, "moves": preview})
        else:
            print(f"Undo preview | {run['id']}")
            for move in preview:
                print(f"  {move['status']}: {move['source']!r} -> {move['target']!r}")
                if move.get("reason"):
                    print(f"    {move['reason']}")
            print("No files changed. Add --apply to restore this run.")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    args = _parser().parse_args(argv)
    try:
        return _dispatch(args)
    except (FilePilotError, OSError, UnicodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted. Check history and use undo to recover saved moves.", file=sys.stderr)
        return 130
