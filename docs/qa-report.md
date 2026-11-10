# FilePilot QA report

Date: 2026-11-10. Version: 0.2.0. Local environment: Windows, CPython 3.12.10.

## Results

- 113 unittest cases passed, with no skipped tests.
- Ruff lint and formatting checks passed.
- Coverage.py 7.17.2 measured the library and CLI subprocesses together:
  641/651 executable lines (98.46%), 228/242 branches (94.21%), and 97.31%
  combined coverage. No lines were excluded from measurement.
- The watcher module reached 100% line and branch coverage in the local run.
- The wheel and source archive were built. The wheel was installed in an isolated
  environment, where the full test suite and demo were run.
- The GitHub Actions workflow repeats tests, coverage, building, wheel install,
  and the demo on Windows and Ubuntu, using Python 3.12 and 3.13. Check the
  [Actions results](https://github.com/amkumirab/FilePilot/actions) for the exact
  commit's remote result; the percentages above are the local Windows measurement.

## Tested behavior

| Area | Checks |
| --- | --- |
| Preview | Read-only organization and undo; no state directory on empty/no-op runs |
| Rules | Every built-in extension, case-insensitive matching, ordered matches, custom TOML, catch-all, dates and renaming |
| Paths | Spaces and Persian filenames, traversal, reserved names, links/junctions, occupied target directories, planned file/directory conflicts |
| Collisions | Existing files and directories, planned duplicates, 96 inputs sharing one destination name and 8 preserved sentinel files |
| Content | Empty file, binary file larger than 16 MiB, byte-for-byte round trips and SHA-256 checks |
| Undo | Latest and explicit run IDs, repeated undo, occupied original paths, changed/missing files, destination replaced by a directory, blocked previews |
| Faults | Deleted sources, move permission errors, journal failures before/after moves, transient and persistent Windows sharing failures |
| Recovery | KeyboardInterrupt, real os._exit after moving, terminated lock-holder process, retry after failed undo, ambiguous hard-link state left untouched |
| Native behavior | Windows exclusive file handle blocks moves safely; POSIX open-file rename preserves the open handle's bytes; POSIX unlink rollback and cross-device failure |
| Inputs | Invalid TOML types/templates, malformed JSON/non-UTF-8 journals, duplicate entries, invalid hashes and out-of-root journal paths |
| CLI | All commands, help/version, JSON, human history, missing folders, invalid run IDs, exit codes 0/1/2/130 |
| Watching | Stable metadata, replaced identities, changes during planning, duplicate previews, retries, root removal/replacement, read-only mode, named locks, JSON Lines, bounded runs, and interruption |

## Defects reproduced and fixed

1. The initial remote run failed on Windows 3.12 and 3.13 because the lock helper
   compared a resolved candidate against an unresolved root. The helper now resolves
   roots before locking; a relative-root regression test covers the failure.
2. The dense-collision round trip exposed a Windows access/sharing error while
   replacing the journal. Relevant Windows errors are retried up to six times;
   persistent failure preserves the previous journal and stops execution.
3. Out-of-range timestamps could escape as raw date-conversion exceptions.
   These now produce a FilePilotError before any files are moved.

## Limits

These checks cover the listed scenarios on the tested platforms. Power-loss
durability, arbitrary network shares, concurrent path replacement by other
processes, and restoration of edited content or ACLs are outside the tested scope.
Use a quiet directory and retain `.filepilot/` and independent backups. A crash
between POSIX link and unlink can leave both paths present. FilePilot preserves
both for manual inspection.

Remaining unexecuted branches in the local coverage run include native POSIX
locking and defensive path/state checks; CI exercises the POSIX implementation
separately. No executable lines were excluded from coverage measurement.
