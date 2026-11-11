# FilePilot 0.2.1

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
