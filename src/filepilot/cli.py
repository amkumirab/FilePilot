"""FilePilot command-line interface; moving files always requires --apply."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_RULES, EXAMPLE_CONFIG, load_rules
from .duplicates import DuplicateReport, find_duplicates
from .engine import execute, history, load_run, preview_undo, undo, validate_plan
from .paths import FilePilotError
from .planner import Plan, build_plan
from .saved_plans import load_plan, save_plan
from .watcher import WatchOptions, watch_folder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="FilePilot: preview, organize, and undo file moves.",
        epilog="Only immediate files are scanned. Moves require --apply.",
    )
    parser.add_argument("--version", action="version", version=f"FilePilot {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "organize", "watch", "plan", "duplicates", "undo", "history"):
        command = commands.add_parser(
            name,
            help={
                "scan": "Preview file organization without changing anything.",
                "organize": "Preview organization, or move files with --apply.",
                "watch": "Watch for stable files; preview unless --apply is supplied.",
                "plan": "Save exact moves and content hashes for later review and execution.",
                "duplicates": "Report same-size, same-SHA-256 files without changing them.",
                "undo": "Preview restoration, or restore files with --apply.",
                "history": "List saved runs for a folder.",
            }[name],
        )
        command.add_argument("folder", type=Path, help="Folder to inspect (not recursive).")
        command.add_argument(
            "--json",
            action="store_true",
            help=(
                "Print JSON Lines events." if name == "watch" else "Print machine-readable JSON."
            ),
        )
        if name in ("scan", "organize", "watch", "plan"):
            command.add_argument("--config", type=Path, help="Use custom TOML rules.")
        if name == "plan":
            command.add_argument(
                "--output", type=Path, required=True, help="Create a new JSON plan."
            )
        if name in ("organize", "undo", "watch"):
            command.add_argument("--apply", action="store_true", help="Actually move files.")
        if name == "undo":
            command.add_argument("--run", help="Run ID; defaults to latest run not fully undone.")
        if name == "watch":
            command.add_argument(
                "--interval", type=float, default=1.0, help="Seconds between polls (default: 1)."
            )
            command.add_argument(
                "--settle",
                type=float,
                default=2.0,
                help="Seconds of unchanged file metadata before processing (default: 2).",
            )
            command.add_argument(
                "--max-cycles",
                type=int,
                help="Stop after this many polls; otherwise run until Ctrl+C.",
            )
    apply_saved = commands.add_parser(
        "apply", help="Validate a saved plan; move only with --apply."
    )
    apply_saved.add_argument("plan", type=Path, help="Saved JSON plan to review or execute.")
    apply_saved.add_argument(
        "--apply", action="store_true", help="Actually move the planned files."
    )
    apply_saved.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    initialize = commands.add_parser(
        "init", help="Write an example TOML config without overwriting."
    )
    initialize.add_argument("--output", type=Path, default=Path("filepilot.toml"))
    return parser


def _json(value) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2))


def _print_plan(plan: Plan, *, as_json: bool, saved: bool = False) -> None:
    if as_json:
        _json(plan.to_dict())
        return
    print(f"FilePilot | {plan.root}")
    print(f"Preview: {len(plan.moves)} move(s), {len(plan.skipped)} skipped")
    for move in plan.moves:
        print(f"  {move.source!r} -> {move.target!r} [{move.rule!r}]")
    for skipped in plan.skipped:
        print(f"  SKIP {skipped.source!r}: {skipped.reason}")
    if saved:
        print("No files moved. Add --apply to execute this saved plan.")
    else:
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


def _print_duplicates(report: DuplicateReport, *, as_json: bool) -> int:
    document = report.to_dict()
    if as_json:
        _json(document)
    else:
        summary = document["summary"]
        print(f"FilePilot duplicates | {report.root}")
        print(
            f"{summary['duplicate_groups']} group(s) | {summary['duplicate_files']} extra file(s)"
            f" | {summary['redundant_bytes']} redundant logical bytes"
        )
        for group in report.groups:
            print(f"SHA-256: {group.sha256} | {group.size} bytes each")
            for name in group.files:
                print(f"  {name!r}")
        if not report.groups:
            print("No duplicate file groups found among the successfully checked files.")
        print(f"Scanned: {report.scanned_files} | Hashed: {report.hashed_files}")
        for entry in report.skipped:
            print(f"  SKIP {entry.source!r}: {entry.reason}")
        if report.errors:
            print(f"Scan incomplete: {len(report.errors)} file error(s); see stderr.")
        for entry in report.errors:
            print(f"  ERROR {entry.source!r}: {entry.message}", file=sys.stderr)
        print("Read-only report. No files moved or deleted.")
    return 1 if report.errors else 0


def _print_watch_event(event: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(event, ensure_ascii=True), flush=True)
        return
    kind = event["event"]
    if kind == "started":
        mode = "apply" if event["apply"] else "preview"
        print(f"Watching {event['folder']} | {mode} | Ctrl+C to stop")
    elif kind == "preview":
        print(f"Preview: {len(event['plan']['moves'])} stable file(s)")
        for move in event["plan"]["moves"]:
            print(f"  {move['source']!r} -> {move['target']!r}")
    elif kind == "run":
        _print_run(event["run"], as_json=False)
    elif kind == "error":
        print(f"Watch error for {event['source']!r}: {event['message']}", file=sys.stderr)
    elif kind == "stopped":
        print(
            f"Stopped: {event['reason']} | {event['cycles']} polls | "
            f"{event['moved']} moved | pending failures: {event['failed']}"
        )
        if event["reason"] == "interrupted":
            print("Check history for any interrupted batch before using undo.")
    sys.stdout.flush()


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(EXAMPLE_CONFIG)
        print(f"Created {args.output}. Use --config {args.output} with scan or organize.")
    elif args.command == "duplicates":
        return _print_duplicates(find_duplicates(args.folder), as_json=args.json)
    elif args.command == "plan":
        rules = load_rules(args.config) if args.config else DEFAULT_RULES
        exclude = (args.output, args.config) if args.config else (args.output,)
        saved = save_plan(build_plan(args.folder, rules, exclude=exclude), args.output)
        if args.json:
            _json(saved.to_dict())
        else:
            print(f"Saved {len(saved.plan.moves)} move(s) to {str(args.output)!r}.")
            print("Review the JSON, then use 'filepilot apply PLAN --apply'. No files moved.")
    elif args.command == "apply":
        saved = load_plan(args.plan)
        if args.apply and saved.plan.moves:
            return _print_run(execute(saved.plan, hashes=saved.hashes), as_json=args.json)
        validate_plan(saved.plan, saved.hashes)
        if args.json:
            _json({**saved.to_dict(), "preview": True})
        else:
            _print_plan(saved.plan, as_json=False, saved=True)
    elif args.command == "watch":
        options = WatchOptions(
            interval=args.interval, settle=args.settle, max_cycles=args.max_cycles
        )
        rules = load_rules(args.config) if args.config else DEFAULT_RULES
        return watch_folder(
            args.folder,
            rules,
            apply=args.apply,
            options=options,
            exclude=(args.config,) if args.config else (),
            emit=lambda event: _print_watch_event(event, as_json=args.json),
        )
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
        if args.command == "duplicates":
            print("Interrupted. No files were moved or deleted.", file=sys.stderr)
        else:
            print(
                "Interrupted. Check history and use undo to recover saved moves.", file=sys.stderr
            )
        return 130
