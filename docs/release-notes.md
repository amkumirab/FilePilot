# FilePilot 0.3.0

Save a reviewed batch and apply its exact recorded destinations later:

```powershell
.\FilePilot.exe plan "$env:USERPROFILE\Downloads" --output reviewed-plan.json
.\FilePilot.exe apply reviewed-plan.json
.\FilePilot.exe apply reviewed-plan.json --apply
```

The first command creates a new JSON file with source content hashes. Review its
root and moves before applying it. All files and destinations are checked under
the folder lock before the first move. Changed files, occupied destinations, or
unsafe paths reject the batch. New unrelated files stay in place. Runs use the
existing history and undo commands. Concurrent edits after preflight can still
cause a recoverable partial run; use a quiet folder.

Plans are unsigned local data and are limited to 10 MiB. Existing plan files are
never overwritten. Create a new plan after a stale-plan error.

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
