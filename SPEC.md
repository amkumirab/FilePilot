# FilePilot 0.1

## Objective and scope
Build a local, dependency-free Python 3.12+ CLI that organizes the immediate files
in a user-selected folder. The agreed first version includes configurable rules,
preview, optional renaming, collision handling, execution history, and undo.
GUI, scheduling, watching, recursive scanning, and remote publication are later work.

## Acceptance criteria
- Scanning and previews create no files or folders.
- Only `organize --apply` and `undo --apply` move files.
- Rules are ordered TOML records: extension and optional filename substring match;
  first match wins. Directory and filename templates use modification dates.
- Files with colliding names receive deterministic numbered suffixes; no file is
  overwritten. Unmatched files, hidden files, directories, symlinks, junctions,
  and common incomplete-download files are left alone.
- Every attempted move is journaled before execution. Successful moves are
  recoverable through undo, including a process interruption after a move.
- Undo refuses to overwrite an occupied original path or move changed content.
- Both configuration and journal paths must stay within the selected root.
- Cooperating FilePilot processes serialize writes with an OS-released lock.
- Errors have readable messages and nonzero exit codes.

## Structure and implementation plan
`src/filepilot/`: config and path validation -> read-only planner -> journaled
engine -> CLI. `tests/`: isolated temporary-directory unit/integration tests.
`examples/`: custom TOML rules. `docs/`: architecture and safety limitations.
Implement and verify each slice before the next; keep focused Git commits.

## Commands
Install: `python -m pip install -e .`
Test: `python -m unittest discover -s tests -v`
Lint: `python -m ruff check .`
Build: `python -m build`
Run: `filepilot scan PATH`, `filepilot organize PATH --apply`,
`filepilot history PATH`, `filepilot undo PATH --apply`.

## Style and boundaries
Use typed dataclasses, pathlib, small functions, explicit errors, and stdlib only
at runtime. Example: `build_plan(root: Path, rules: tuple[Rule, ...]) -> Plan`.
Always validate paths, keep a durable journal, test failure paths, and preserve
user data. Never overwrite existing files or silently lower test requirements.
Changing the public command contract or adding services requires revisiting
this spec. Tests use real files; mocks inject move/journal failures only.

## Trust and operational limits
Inputs: user paths, TOML, file names, persisted journals. Assets: file bytes and
restorability. Reject traversal, reparse points, invalid portable names, and
unknown config fields. Journals contain local filenames and hashes only; no
network calls or telemetry. This is a local utility, not a security boundary
against other programs modifying the same folder during execution. Use a quiet
folder and back up important files; filesystem power-loss durability is not a
transaction across both the journal and directory metadata.
