# Windows release

- [x] Versioned ZIP, offline guide, build metadata, checksums, and archive tests.
- [x] Build and execute the actual Windows x64 binary in an isolated environment.
- [x] CI artifact and tag-triggered publication with draft upload verification.
- [x] Download instructions and local release verification.

The tagged build and published download are checked through GitHub Actions and
the standalone smoke runner before handoff.
