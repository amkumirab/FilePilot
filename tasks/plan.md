# Duplicate detection

Contract: [SPEC-duplicates.md](../SPEC-duplicates.md).

1. Implement deterministic, size-first streaming detection and a versioned report.
   Test real content, large files, errors, changing files, filters, and hard links.
2. Expose the read-only `duplicates` command with human/JSON output and exit codes.
   Exercise it through subprocesses and preserve existing CLI contracts.
3. Document the report and its limits, extend native executable smoke checks, and
   verify packages, source coverage, Windows binary, dependency audit, and CI.

Each slice keeps its implementation and tests together in a focused commit.
