# Read-only duplicate detection

Add `filepilot duplicates FOLDER [--json]` without runtime dependencies. Identify
same-size, same-SHA-256 content across differently named files, independent of
organization rules. This command never creates history, locks, or category folders
and never moves or deletes files. Normal reads may update OS access timestamps.

## Selection and comparison

- Scan immediate entries only, in deterministic casefold/name order. Skip links,
  junctions, hidden/internal entries, directories/nonregular files, and the existing
  incomplete-download suffixes. Reject unsafe portable names as per-file errors.
- Coalesce hard-link aliases by device/inode when an inode is available. Aliases
  are listed as skipped and do not inflate duplicate counts or logical bytes.
- Group unique eligible files by size. Hash only buckets with at least two files.
  Read in chunks of at most 1 MiB with a bound of the observed size plus one byte;
  a continuously growing file cannot make hashing run indefinitely.
- Compare regular-file type, identity, size, modification time, and POSIX change
  time (Windows creation time, because ctime is deprecated on Windows)
  before/after opening, reading, and a final report pass. Exclude unstable files
  with per-file errors. Check root identity as well. Use no-follow/nonblocking
  open flags where available, without claiming descriptor-relative sandboxing.
- Group by `(size, sha256)` and retain groups with at least two valid independent
  files. A report is a point-in-time observation, not authorization to delete.

## Output and errors

Version-1 JSON fields: `version`, canonical absolute `root`, `groups`, `summary`,
`skipped`, `errors`. A group contains `sha256`, `size`, ordered relative `files`,
and `redundant_bytes = size * (len(files) - 1)`. Summary has `scanned_files`
(eligible independent files), `hashed_files` (successful hash reads, even if later
invalidated), `duplicate_groups`, `duplicate_files` (copies beyond one per group),
and `redundant_bytes`. Skip records have `source` and `reason`; errors have `source`
and `message`. Human output includes hashes, names, logical bytes, and scan totals;
per-file error details go to stderr. JSON errors are in the document.

Exit 0 means a completed scan, including no matches. Per-file I/O/change errors
return a partial report with exit 1. Invalid roots or enumeration/root-identity
failures return exit 2 on stderr. Ctrl+C returns 130. No `--apply`, delete flag,
recursive scan, scheduling, or persisted-report import is part of this feature.

## Verification and shipping

Cover different filenames/extensions, same-size different bytes, empty files,
chunked large reads, filtering, hard links, partial failures, changes during/after
hashing, replacements, root changes, deterministic JSON and read-only CLI behavior.
Reuse the current Ruff/unittest, isolated wheel, Windows smoke, and CI gates.
Package additive version 0.4.0 through the existing tagged release workflow.
