# FilePilot 0.5.0

Quarantine duplicate copies and restore them to their original folders with undo.
Choose one file to keep and list the copies to move. The command previews by
default and checks content before applying the moves.

```powershell
.\FilePilot.exe quarantine .\Photos --keep 2025/photo.jpg --move Backup/photo.jpg
.\FilePilot.exe quarantine .\Photos --keep 2025/photo.jpg --move Backup/photo.jpg --apply
.\FilePilot.exe undo .\Photos --apply
```

Duplicate reports can include matches across subfolders with `--recursive`.

Use FilePilot 0.5.0 or newer to read and undo quarantine history.

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
