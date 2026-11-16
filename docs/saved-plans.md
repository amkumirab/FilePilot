# Saved plans

Use `plan` when you want to review a batch now and execute that exact batch later.
`organize --apply` continues to generate a fresh plan from the current rules.
Saved plans are available from FilePilot 0.3.0.

## Workflow

```powershell
filepilot plan "C:\path\to\inbox" --config rules.toml --output reviewed-plan.json
filepilot apply reviewed-plan.json
filepilot apply reviewed-plan.json --apply --json
filepilot history "C:\path\to\inbox"
filepilot undo "C:\path\to\inbox" --apply
```

For the portable Windows build, replace `filepilot` with `.\FilePilot.exe`.
`--config` is optional and only used when creating the plan. Built-in rules apply
otherwise. `--output` is required; its parent directory must already exist. The
command refuses to replace an existing plan. Use a new filename to replan.
The chosen config and output file are excluded from selection. Store the plan
outside `.filepilot/` and outside its own planned source/destination paths.

Open the JSON and review `root`, `source`, and `target`. `apply` without `--apply`
validates the batch and shows a read-only preview. Both commands support `--json`:
`plan` prints the same document it writes; an apply preview adds `"preview": true`.
An applied batch prints the normal run object with an ID for `history` and `undo`.

## What is checked

Creating a plan reads every selected file to record its SHA-256 content hash.
Applying a plan checks all source sizes, nanosecond modification times, hashes,
and destination paths before the first move, while holding the existing folder
lock. Same-size edits with a preserved timestamp are still detected by hashing.
An occupied destination is rejected, including case-insensitive filename matches.
No new collision suffix is chosen. Directory spelling changes require a new plan.

New unrelated files stay where they are. Rules can change after planning without
changing the saved moves. The recorded move order is preserved. Empty plans are
successful no-ops and create no journal, including when `--apply` is supplied.

A stale or invalid batch returns exit 2 before moving files or recording a run.
An applying check may create `.filepilot/lock`; a preview creates no state.
Unknown formats, versions, fields, duplicate JSON keys, invalid hashes/types,
duplicate paths, conflicting file/directory paths, traversal, reserved history
paths, symbolic links, and junctions are rejected. The absolute root must still
exist at its recorded canonical path; plans are not rebased to another folder.

## File format

The UTF-8 JSON document has exactly these top-level fields:

| Field | Meaning |
| --- | --- |
| `format` | The string `filepilot-plan` |
| `version` | Integer `1`, independent of the application version |
| `root` | Canonical absolute path to the organized directory |
| `moves` | Ordered array of the move records below |
| `skipped` | Array of display-only `{source, reason}` records |

Each move has exactly `source`, `target`, `rule`, `size`, `modified_ns`, and
`sha256`. Source is one portable filename; target is a nested relative path using
`/`. Size is a nonnegative integer number of bytes; modification time is an
integer number of nanoseconds since the epoch. The hash is 64 lowercase hex
characters. Rule is the nonempty matching rule name. Input and generated output
are limited to 10 MiB. A partially written output after a disk error is invalid;
inspect it and choose a new filename before planning again.

## Limits and recovery

Hashing costs a full read of each selected file when saving and during preflight.
Execution rechecks each file's content again before moving it. The lock coordinates
FilePilot processes; it cannot lock out every editor or downloader. Use a quiet
folder and stop applying watchers before applying a reviewed plan.

Preflight is not a filesystem transaction. Concurrent changes or I/O errors after
it passes can leave a partial run (exit 1), and Ctrl+C returns 130. Successful
moves remain in the usual journal and can be undone; check `history` first.
Undo checks file contents and never restores earlier edits or overwrites an
occupied original path. Keep `.filepilot/` with the original root.

A saved plan is unsigned local data. Hashes detect source changes; they do not
prove who wrote the plan. Applying a plan authorizes the root and moves recorded
in it. Review plans from other people before execution. Do not manually change
hashes or timestamps to bypass a stale-plan error; create and review a new plan.
