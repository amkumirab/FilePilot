# Changelog

## 0.2.1 - 2026-11-11

### Added
- Standalone Windows x64 executable with an offline guide, sample rules,
  application and third-party licenses, version information, and build metadata.
- ZIP checksums and tests of the actual extracted executable with a minimal PATH.
- Automated tag releases that verify the source commit and downloaded draft
  assets before publication.

### Changed
- Extend CI with a Windows executable build and smoke tests.
- Expand verification to 128 tests, including release archive and version checks.

## 0.2.0 - 2026-11-10

### Added
- Foreground folder watching with configurable polling and settling intervals.
- Preview deduplication, bounded move retries, a single applying watcher per root,
  journaled batches, JSON Lines events, and graceful Ctrl+C shutdown.
- An isolated live watcher demo and animated README example.

### Changed
- Extend CI to exercise the installed watch command and subsequent undo.
- Expand verification to 113 tests, including native file sharing, stable-file
  tracking, duplicate suppression, retry limits, and interrupted watches.
- Measure line and branch coverage across CLI subprocesses in CI.
- Group filesystem tests into organization, recovery, native filesystem, and
  input validation suites.

### Fixed
- Normalize lock roots so relative paths and Windows short-path aliases work.
- Retry transient Windows journal access/sharing conflicts without replacing
  the previous journal on persistent failure.
- Explain unsupported file modification timestamps without a traceback.

## 0.1.0 - 2026-11-08

### Added
- Read-only previews and explicit application of file organization plans.
- Built-in file categories and ordered TOML rules with date/rename templates.
- Collision suffixes, source rechecks, path validation, and process locks.
- Per-run JSON journals, execution history, content-checked undo, and recovery
  of interrupted moves and restores.
- Machine-readable output, isolated demo, tests, and CI workflow.
