# FilePilot 0.2

## Objective and scope
FilePilot is a local Python 3.12+ CLI with no runtime dependencies. It organizes
the immediate files in a selected folder. The first version includes configurable rules,
preview, optional renaming, collision handling, execution history, undo, and
foreground folder watching. GUI, scheduling, and recursive scanning are outside
this version's scope. The watch command is specified in [watching.md](docs/watching.md).

## Acceptance criteria
- Scanning and previews create no files or folders.
- Only `organize --apply`, `watch --apply`, and `undo --apply` move files.
- Rules are ordered TOML records: extension and optional filename substring match;
  first match wins. Directory and filename templates use modification dates.
- Files with colliding names receive deterministic numbered suffixes; no file is
  overwritten. Unmatched files, hidden files, directories, symlinks, junctions,
  and common incomplete-download files are left alone.
- Every attempted move is journaled before execution. Successful moves are
  recoverable through undo, including a process interruption after a move.
- Undo refuses to overwrite an occupied original path or move changed content.
- Destination and journal paths must stay within the selected root.
- Cooperating FilePilot processes serialize writes with an OS-released lock.
- Errors have readable messages and nonzero exit codes.

## Structure
`src/filepilot/`: config and path validation -> read-only planner -> journaled
engine -> CLI. `tests/`: isolated temporary-directory unit/integration tests.
`examples/`: custom TOML rules. `docs/`: architecture and safety limitations.
Keep changes small, verify each change, and use focused Git commits.

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
Validate paths, keep a durable journal, test failure paths, and preserve user data.
Existing files must not be overwritten. Keep all test requirements intact.
Changing the public command contract or adding services requires revisiting
this spec. Tests use real files; mocks exercise filesystem, timestamp, and journal
failure paths.

## Trust and operational limits
Inputs: user paths, TOML, file names, persisted journals. Assets: file bytes and
restorability. Reject traversal, reparse points, invalid portable names, and
unknown config fields. Journals contain local filenames and hashes only; no
network calls or telemetry. This is a local utility, not a security boundary
against other programs modifying the same folder during execution. Use a quiet
folder and back up important files; filesystem power-loss durability is not a
transaction across both the journal and directory metadata.
