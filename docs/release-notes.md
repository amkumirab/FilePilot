# FilePilot 0.4.0

Report duplicate file content without moving or deleting files:

```powershell
.\FilePilot.exe duplicates "$env:USERPROFILE\Downloads"
.\FilePilot.exe duplicates "$env:USERPROFILE\Downloads" --json
```

The scanner groups immediate regular files by size before calculating SHA-256
in bounded chunks. It reports matching filenames, extra copies, and logical
duplicate bytes. Hard-link aliases count once when identity is available.
Directories, hidden/internal files, incomplete downloads, and links are skipped.

Unreadable or detectably changing files produce a partial report with exit 1;
JSON includes their errors. Use a quiet folder: a report is a point-in-time
observation, and logical bytes are not a disk-space recovery guarantee.
Existing organization, watch, saved-plan, history, and undo commands remain available.

The Windows x64 ZIP contains a standalone `FilePilot.exe`. Python is included;
no separate Python installation is required.

Extract the ZIP, open PowerShell in the extracted folder, and run:

```powershell
.\FilePilot.exe --help
.\FilePilot.exe scan "$env:USERPROFILE\Downloads"
```

Organization and folder watching use previews unless `--apply` is supplied.
Stop watching with Ctrl+C before undoing a batch. Keep the `.filepilot` history
directory in the organized folder.

The release pipeline runs the Python test matrix, builds the executable on
Windows, tests the extracted executable, and verifies uploaded checksums before
publishing. The ZIP includes the license, third-party notices, sample rules,
offline instructions, and build metadata.

Use `SHA256SUMS.txt` to check the download. The executable is unsigned.
