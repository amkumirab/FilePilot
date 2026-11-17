# Architecture and recovery

## Execution path

`config.py` validates ordered TOML rules. `planner.py` creates immutable move
records from the immediate regular files in the root. Planning never creates
directories. `paths.py` validates portable relative names and rejects symlinks,
junctions, traversal, and access to the reserved `.filepilot/` state directory.

`engine.py` rechecks file size and modification time, calculates a SHA-256 digest,
and persists each operation before moving. `journal.py` writes a temporary JSON
file, flushes and fsyncs it, then replaces the journal atomically. A journal error
stops execution. An OS lock prevents simultaneous cooperating writers; a process
crash releases it automatically, so there is no stale lock-file deletion step.
Lock roots are resolved before containment checks, including relative paths and
Windows short-name aliases. Journal replacement retries Windows error codes
5, 32, and 33 up to six times with bounded exponential delays (0.62 seconds of
total waiting). Other errors stop immediately; a persistent sharing conflict
also stops without discarding the previous journal.

Windows uses `os.rename`, which fails if the destination exists. POSIX uses
exclusive `os.link` followed by source unlink; an ordinary unlink failure attempts
to remove the newly created link. POSIX destinations must support hard links
and be on the source filesystem. There is deliberately no overwrite/copy fallback.

## Duplicate detection

`duplicates.py` owns its read-only report types, selection, and comparison. It
reuses path guards and the planner's temporary-file suffixes but does not invoke
the engine or journal. Device/inode identities coalesce hard links, then size
buckets avoid content reads for unique sizes. Only matching size/hash groups of
independent files are reported. A streaming reader bounds each read and total
bytes, checks the opened descriptor as well as the path, and closes handles on
every exit. A final metadata pass removes invalidated candidates.

Per-file failures remain in a partial report, distinct from global root/listing
errors. No write lock is taken: this is an observation, not a destructive action.
Logical duplicate bytes intentionally do not claim allocated space recovery.
The bounded reader is separate from the engine's digest helper because it must
handle actively changing files without following their growth. See
[the duplicate report contract](duplicates.md).

## Saved-plan execution

`saved_plans.py` persists the planner's immutable moves with SHA-256 fingerprints
in an independent version-1 format. Strict boundary validation rejects unknown
fields, duplicate keys, unsafe/conflicting paths, and unsupported versions. Plans
keep their canonical absolute root. A file size cap bounds JSON reads.

`engine.validate_plan` checks the complete batch without writing state. Snapshot
creation uses it to capture hashes; apply previews use it to validate those hashes.
`engine.execute(plan, hashes=...)` runs it again inside the existing root lock,
before writing a journal or moving a file. The ordinary execution path then
compares each newly read content hash with the saved one. Existing journal formats,
exclusive move operations, and recovery/undo states are shared by both modes.

This avoids rebuilding destinations from potentially changed rules after review.
Replanning and silently choosing a new collision suffix would execute a different
batch from the one the user inspected. Full preflight prevents known stale later
entries from causing earlier moves, but cannot make independent filesystem moves
atomic against other programs. See [saved plans](saved-plans.md).

## State transitions

Organization: `not_started -> pending -> moved` (or `failed`). The pending state,
including the hash, is saved before a filesystem move. A process that terminates
after the move but before the next save leaves enough information for undo to
check whether the destination is present and restore it.

Undo: `moved/pending -> undo_pending -> undone`. Undo saves `undo_pending` before
restoring a file. If interrupted after restoration, retry recognizes the original
file by its hash when the organized path is absent. A missing target for a
`not_started`, `pending`, or `failed` operation with an existing source is treated
as never moved. If both paths exist, a move's outcome is ambiguous, or content
has changed, files are left in place. Undo previews perform the same checks
without writing the journal. Empty directories remain after undo.

Run statuses distinguish completion, partial failure, interruption (`running` or
`undoing`), partial undo, and full undo. Each journal stores its original absolute
root; moving the whole root requires manual recovery rather than silent rebasing.

## Boundaries

The root, filenames, TOML, and journals are all validated at their input boundary.
User templates support named fields only, not attribute access, conversion, or
format specifications. Saved source paths must be single filenames, saved
destinations must be nested relative paths, and duplicate entries are rejected.
No shell commands execute from rule contents. No file contents leave the machine.

The tool is intended for a local user and a quiet directory. Path checks are
best-effort checks, not descriptor-relative sandboxing against another process
replacing paths concurrently. Size/mtime checks cannot prove a file was not
edited; undo hashes verify bytes, not ownership. A POSIX crash between link and
unlink can leave both paths present, requiring manual inspection. Filesystem
directory metadata and the journal are not one transaction; power-loss guarantees,
arbitrary network drives, concurrent editors, and full metadata/ACL restoration
are outside this first version's contract.

## Verified API references

- [Python 3.12 os.rename and os.link](https://docs.python.org/3.12/library/os.html)
- [Windows msvcrt.locking](https://docs.python.org/3.12/library/msvcrt.html#msvcrt.locking)
- [Python Packaging User Guide](https://packaging.python.org/en/latest/tutorials/packaging-projects/)
- [actions/checkout](https://github.com/actions/checkout)
- [actions/setup-python](https://github.com/actions/setup-python)
