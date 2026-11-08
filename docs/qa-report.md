# FilePilot QA report

Date: 2026-11-08. Local environment: Windows, CPython 3.12.10.

## Results

- 76 unittest cases passed, with no skipped tests.
- Ruff lint and formatting checks passed.
- Coverage.py 7.17.2 measured the library and CLI subprocesses together:
  475/485 executable lines (97.94%), 165/178 branches (92.70%), and 96.53%
  combined coverage. No lines were excluded from measurement.
- Wheel and source archive builds are validated separately, followed by
  installation of the wheel into an isolated environment and a full test/demo run.
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

## Defects reproduced and fixed

1. The initial remote run failed on Windows 3.12 and 3.13 because the lock helper
   compared a resolved candidate against an unresolved root. Resolve roots before
   locking; a relative-root regression test also reproduces this locally.
2. The dense-collision round trip exposed a Windows access/sharing error while
   replacing the journal. Retry only the relevant Windows errors, bounded to
   six attempts; persistent failure preserves the previous journal and stops.
3. Out-of-range timestamps could escape as raw date-conversion exceptions.
   Convert these into an explicit FilePilotError before mutating files.

## Limits

Tests cannot prove absence of all bugs. This report does not claim power-loss
durability, support for every filesystem/network share, protection against
adversarial concurrent path changes, or restoration of edited content/ACLs.
Use a quiet directory; retain `.filepilot/` and independent backups. A real crash
in the POSIX link/unlink gap may leave both paths and requires manual inspection;
the tested behavior preserves both rather than guessing which one to remove.

Remaining unexecuted branches in the local coverage run include native POSIX
locking and defensive path/state checks; CI exercises the POSIX implementation
separately. No coverage exclusions or lowered thresholds were used.
