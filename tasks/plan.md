# Saved execution plans

Contract: [SPEC-saved-plans.md](../SPEC-saved-plans.md).

1. Persist content fingerprints and validate the versioned plan schema. Test
   serialization, malformed input, path conflicts, and whole-batch preflight.
2. Execute reviewed plans under the existing lock and expose `plan` / `apply`.
   Test previews, changed files, exact destinations, recovery, and existing CLI.
3. Document the workflow, extend the native executable smoke test, and verify
   source tests, lint, wheel/sdist, installed package, Windows binary, and CI.

Each slice keeps its implementation and tests together in a focused commit.
