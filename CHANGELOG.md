# Changelog

## Unreleased

### Fixed
- Normalize lock roots so relative paths and Windows short-path aliases work.
- Retry transient Windows journal access/sharing conflicts without replacing
  the previous journal on persistent failure.
- Explain unsupported file modification timestamps without a traceback.

### Changed
- Expand verification to 76 tests, including real process termination, native
  open-file behavior, dense collisions, binary round trips, and corrupted input.
- Measure line and branch coverage across CLI subprocesses in CI.
- Group filesystem tests into organization, recovery, native filesystem, and
  input validation suites, preserving all 76 cases.

## 0.1.0 - 2026-11-08

### Added
- Read-only previews and explicit application of file organization plans.
- Built-in file categories and ordered TOML rules with date/rename templates.
- Collision suffixes, source rechecks, path validation, and process locks.
- Per-run JSON journals, execution history, content-checked undo, and recovery
  of interrupted moves and restores.
- Machine-readable output, isolated demo, tests, and CI workflow.
