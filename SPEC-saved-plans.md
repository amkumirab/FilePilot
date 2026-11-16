# Saved execution plans

Let a local user save the exact moves they reviewed and apply them later without
re-running rules or silently choosing new destinations. Existing scan, organize,
watch, journal, and undo behavior remains compatible. No runtime dependencies.

## Commands and contract

- `filepilot plan FOLDER --output plan.json [--config rules.toml] [--json]`
  creates a new UTF-8 JSON file exclusively; never overwrites one. Exclude the
  output and config from selection. Planning writes no history or category folders.
- `filepilot apply plan.json [--json]` validates the saved batch and prints a
  read-only preview. `--apply` explicitly authorizes execution.
- Format `filepilot-plan`, integer version 1, canonical absolute root, ordered
  moves (source, target, rule, size, modified_ns, SHA-256), and skipped entries.
  Relative paths use `/`. Reject unknown versions/fields, duplicate JSON keys,
  invalid types/hashes, duplicate or conflicting paths, links, and reserved paths.
  Bound input to 10 MiB. A plan is local data, not a signature or an authorization
  token; users must review plans from other people.
- Before the first move, under the existing root lock, verify every source's
  size, timestamp, and full content hash, and every destination's availability.
  Abort the whole batch on a known stale/invalid entry; no run is recorded.
  The lock may create `.filepilot/lock`. Preview creates no state.
- Keep exact recorded order and destinations. New unrelated files are ignored.
  Recheck content at each move and retain exclusive no-overwrite operations.
  Concurrent changes or I/O failures after preflight can produce a recoverable
  partial run; this is not a filesystem transaction. Undo uses existing journals.
- A missing/relocated root, missing source, changed metadata or content, occupied
  destination, unsafe parent, or malformed plan returns exit 2. Execution failures
  after successful preflight retain existing exit 1 / interruption 130 behavior.
  Empty plans preview successfully and create no run even with `--apply`.

## Boundaries and verification

Always validate disk input and preserve user bytes. Do not rebase plans, overwrite
outputs, weaken checks, alter existing journal formats, or add a copy fallback.
GUI, scheduling, recursive scans, cryptographic signing, and changes to release
infrastructure are outside this feature. Package version 0.3.0 using the existing
tagged Windows release pipeline. Follow unittest, Ruff, wheel/sdist, and native
Windows smoke checks. Add tests for round trips, Unicode, stale later entries,
same-size/same-time edits, schema abuse, collisions, links, previews, and undo.
