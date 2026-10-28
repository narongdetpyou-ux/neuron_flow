# Cleanup and release preparation — 28 October 2026

The owner authorized merging, publication of suitable work and repository organization.
PR #10 was already merged at 233d3f8; its actual Linux/Windows/macOS checks passed.

`cleanup.json` records the conservative cleanup: remove regenerable ignored caches,
archive stale root build status, retain the historical 0.2.0 approval, and remove the
byte-identical obsolete root manifest while retaining `release-assets/SHA256SUMS.txt`.
All golden fixtures, historical verification evidence, prior release assets and the
linked research candidate remain unchanged. The source checkout has no package manifest;
actual Colab evidence must be supplied from the verified extracted package, which gets
a freshly generated manifest. A regression checks missing-manifest rejection before work.

Local validation: 38 baseline + 120 current tests, 10 release guards, locked fixture,
report examples and quality gates passed; no failures, errors or skipped tests.
The quality run has 158 tests (the same baseline/current tests, not additional cases).
Actual Colab acceptance remains not_run. Publication approval is separate from acceptance.

The manual release workflow will bind v0.2.1 to the exact merged commit, rebuild,
check a fresh extraction, upload without overwriting assets, verify remote hashes and
publish only after all guards pass. See GitHub Releases/workflow runs for remote publication
outcomes; these preparation results alone do not claim that publication has happened.
