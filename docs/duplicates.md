# Duplicate reports

Available from FilePilot 0.4.0:

```powershell
filepilot duplicates "C:\path\to\folder"
filepilot duplicates "C:\path\to\folder" --json
filepilot duplicates "C:\path\to\folder" --recursive --json
```

Use `.\FilePilot.exe` instead of `filepilot` in the portable Windows build. This
command reports matching content; it never moves, deletes, or writes files and
creates no `.filepilot/` state. Ordinary reads may update OS access timestamps.

## Selection and comparison

The default scan checks immediate regular files of any extension. With
`--recursive`, the scan includes regular files in visible subfolders and groups
matches across the whole tree. Symbolic links, junctions, hidden/dot/internal
entries, and files with incomplete suffixes (`.part`, `.partial`, `.crdownload`,
`.download`, `.tmp`, `.temp`, case-insensitively) are skipped. Paths that fail
portable name validation are reported as errors.

Files are grouped by size. A size seen only once requires no content read. For
repeated sizes, SHA-256 is calculated in chunks of at most 1 MiB. Reading is bounded
by the observed size plus one byte to detect growth without chasing a growing file
indefinitely. Matching size and hash form a duplicate group. Multiple zero-byte
files form a valid group with zero redundant bytes.

Hard links with a shared device/inode are aliases of the same file, not independent
copies. The first eligible name is retained; other aliases appear in `skipped`.
Filesystems that expose no inode cannot support this distinction. The scanner
checks file type, identity, size, and modification timestamps before/after reading
and once more before reporting. It also checks POSIX change times; Windows uses
creation time because Python's Windows `st_ctime` is deprecated and can disagree
between path and handle queries on Python 3.12. Root identity is checked as well.

## JSON contract

The top-level fields are `version` (integer `1`), `root` (canonical absolute path),
`groups`, `summary`, `skipped`, and `errors`.

Each group contains:

| Field | Meaning |
| --- | --- |
| `sha256` | Lowercase SHA-256 digest |
| `size` | Logical size of each file, in bytes |
| `files` | Paths relative to `root`, using `/` and sorted by casefold/name |
| `redundant_bytes` | `size * (number of independent files - 1)` |

Groups are ordered by their first filename. The summary contains:

| Field | Meaning |
| --- | --- |
| `scanned_files` | Eligible independent files observed, including later read failures |
| `hashed_files` | Successful hash reads, including files invalidated in the final pass |
| `duplicate_groups` | Number of reported groups |
| `duplicate_files` | Total independent copies beyond one per group |
| `redundant_bytes` | Sum of the groups' redundant logical bytes |

Skipped entries have `source` and `reason`. Errors have `source` and `message`.
The `source` field uses the same relative path format.
JSON output contains entry errors directly; human output sends their details
to stderr and labels the report incomplete. Keep redirected reports outside the
scanned folder so the report file does not become an input.

## Exit codes and limits

- `0`: Complete report, including an empty folder or no duplicate groups.
- `1`: Partial report after an error with a file or subfolder.
- `2`: Invalid/missing root, root enumeration failure, or replaced root.
  These global errors go to stderr, including with `--json`.
- `130`: Interrupted scan. No files were moved or deleted.

The report is a point-in-time observation. Use a quiet folder: other applications
can still edit paths or content after checks, and metadata-preserving edits during
reading are not guaranteed to be detected. Checks are not an atomic filesystem
snapshot or a sandbox against hostile concurrent path replacement. Hash equality
is a content comparison, not ownership or authorization to delete anything.

Redundant bytes describe logical content, not guaranteed recoverable disk space.
Sparse files, compression, reflinks, snapshots, and filesystems without reliable
identity information can make allocated storage differ from this total.
Memory scales with filenames/metadata plus a fixed read buffer, not file contents.

API reference: [Python 3.12 stat results and timestamp semantics](https://docs.python.org/3.12/library/os.html#os.stat_result).
