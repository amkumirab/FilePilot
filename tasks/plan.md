# Folder watching

Add a foreground polling watcher without runtime dependencies. Reuse the existing
planner, journal, collision handling, and undo. Keep existing commands compatible.

1. Track file identity, size, and modification metadata across polls. Wait for a
   quiet interval, reset on changes, and filter the planner to stable files.
2. Execute stable batches through the existing engine. Deduplicate previews,
   bound retries, and coordinate applying watchers with a separate OS lock.
3. Expose `watch`, timing flags, bounded runs, JSON Lines, and graceful Ctrl+C.
4. Document the command, provide an isolated live demo, build the package, and
   verify local tests and the existing Windows/Ubuntu CI matrix.

Each implementation slice includes tests. Verify incomplete downloads, file
changes between polling and planning, disappeared/replaced roots, failed moves,
journal failures, duplicate watchers, and restoration after stopping the watcher.
