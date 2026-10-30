# Report review integration verification — 2026-10-30

The first integration adds `report-explain` and `report-compare` for existing
saved batch artifacts. It adapts structured evidence and explicit offline
comparison patterns from the previously inspected ABC-Causal Service 0.2.0.
No original Dropbox files or Black Swan implementation are embedded.

The local run is based on commit `273859502efd243f80df73432f6f24178fbe2ec8`.
`validation.json` binds the result to the checked source fingerprint; the
fingerprint excludes this verification directory to avoid a circular record.

## Observed validation

| Check | Result |
| --- | --- |
| New focused regression tests | 15 passed |
| Full regression suite, including the new tests | 218 passed, 0 skipped |
| Release guards | 10 passed |
| Locked 100-document acceptance fixture | Unchanged; check passed |
| Historical 100-document saved report | Explained and compared; bytes and mtimes unchanged |
| Exact-money and real-runtime recovery | THB and multicurrency covered; JPY/KWD strings and delivery receipts preserved |
| Core correctness lint and existing strict typing scope | Passed |
| Overall line / branch coverage | 94.26% / 88.38% |
| New report-review and CLI module line / branch coverage | 100% / 100% |
| Clean installation smoke tests | Wheel and sdist passed, including both new commands |
| Documentation claims and relative links | Passed |

The 15 focused tests are part of the 218-test total. Release guards are separate.
Coverage includes CLI subprocesses and spawned workers; existing quality floors
and exclusions were not weakened. Details are in `quality_results.json` and
`distribution_checks.json`.

## Reproduction

Use Python 3.10 or newer; this local run used Python 3.12. Install the pinned
quality tools, document extras and Tesseract as described in `docs/QUALITY.md`.
Build checks use the hash-locked `requirements-build.txt`. Run the commands
recorded in `validation.json` from the checkout, choosing fresh output folders
outside it for quality and distribution checks.

## Limits

This is local verification, not remote CI, actual Colab acceptance, a signature
of report authorship or release approval. Explanation claims are bound to the
checked saved report; recorded invalid reasons are not independently diagnosed.
Comparison checks saved outcomes for identical source bytes and contract; it
does not run candidates or enable policies. Runtime persistence, money checks,
locked fixtures and release publication settings were not changed.
