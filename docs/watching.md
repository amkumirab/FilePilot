# Watching a folder

## Command contract

`filepilot watch FOLDER [--config FILE] [--apply] [--json] [--interval SECONDS]
[--settle SECONDS] [--max-cycles COUNT]`

The command runs in the foreground until Ctrl+C, or until an optional poll limit
is reached. Defaults: one poll per second and two seconds of unchanged metadata.
All timing values must be positive and finite; the poll limit must be positive.
Files already present at startup also wait through the settling interval.

Preview is the default and never writes files or state. Each unchanged file is
reported once per session. Applying watchers serialize through a separate
watcher lock, and each stable batch uses the existing journaled execution engine.
Only one applying watcher can run for a root. Read-only watchers can coexist.

File identity, size, modification time, and change time are compared between
polls and checked again after planning. Changes restart the settling interval.
Only immediate, matching regular files are tracked. Hidden files, links,
incomplete-download suffixes, and the supplied config are excluded.

Failed moves are retried after another settling interval, up to three attempts
per unchanged file. Editing the file or restarting the watcher resets the limit.
Journal write failures stop the watcher; they are not retried as file moves.
Removing or replacing the root stops the watcher with an error.

## Output and recovery

`--json` writes one JSON object per event: `started`, `preview`, `run`, `error`,
or `stopped`. Ordinary commands retain their existing JSON format.
Exit codes: 0 for a normal stop, 1 for remaining failed files at a poll limit,
2 for invalid input or a fatal error, and 130 for Ctrl+C.

Stop the watcher before using undo; a running watcher can see restored files as
new input. Use history to choose a batch, then restore it with the existing undo
command. A crash during a batch retains the same recovery information as an
ordinary organize run.

A quiet interval is a metadata heuristic, not proof that a download or another
writer has finished. Configure a longer interval when needed and keep temporary
suffixes until writers finish. Rules are loaded once at startup; restart the
watcher after editing them. Deduplication is in memory and resets on restart.
