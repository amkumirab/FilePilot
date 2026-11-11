# Windows builds and releases

Target: Windows x64 console application. A one-file PyInstaller build embeds the
Python interpreter and standard library. The ZIP includes the executable, offline
instructions, example rules, license, version, and build metadata. Application
behavior and the journal format remain unchanged.

Build with `python scripts/build_windows.py` in a dedicated Windows x64 build
environment installed from `requirements-build.txt`. Output is under
`dist/windows/` and `dist/releases/`. Build tools are not runtime dependencies.

`python scripts/verify_binary.py --exe PATH` runs the actual executable with
Python-related environment variables removed and a minimal Windows system PATH.
It uses disposable data and checks version, help, previews, collisions, Unicode
names, organization, history, undo, custom rules, and folder watching.

CI builds and tests the executable on every branch change. A `vX.Y.Z` tag invokes
the same quality matrix and Windows job. The release job checks that the tag,
package version, executable metadata, archive contents, and checksum agree.
It uploads the tested artifact to a draft, downloads it again to verify the
uploaded bytes, and publishes only after those checks pass.
The pinned Windows build requirements are audited in a separate environment.

Existing releases are not overwritten. If publication fails, inspect the draft
and the Actions logs before retrying. A source tag can be inspected or checked
out independently; there are no automatic data migrations or remote services.

The release is unsigned. Do not change OS security settings to run it. Published
checksums detect corruption; they do not replace code signing. Linux/macOS users
can continue installing the Python package from source.

References:
- [PyInstaller options](https://pyinstaller.org/en/stable/usage.html)
- [GitHub release CLI](https://cli.github.com/manual/gh_release_create)
- [Upload artifacts](https://github.com/actions/upload-artifact)
- [Download artifacts](https://github.com/actions/download-artifact)
