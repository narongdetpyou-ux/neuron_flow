# Full selected-pattern integration — 0.4.0

This record covers the full selected ABC/Black Swan reuse-pattern adaptation,
based on commit `061cfb85ad5911cbda5b5eb7a2346eadca772d1f`. The mapping and usage
are in [the operations guide](../../docs/OPERATIONS.md). Original unrelated
models, resource-allocation controllers and domain-specific solvers are excluded.

The tested source fingerprint in `validation.json` matches the canonical package
verifier. Verification records are excluded from that fingerprint to avoid a
circular record. This is local evidence; exact-source remote CI and observed
publication are recorded separately in GitHub.

| Check | Observed result |
| --- | --- |
| Complete regression suite | 261 passed; zero skipped |
| Release guards | 10 passed, separately |
| Locked original 100-document fixture | Unchanged and reproduced |
| Quality line / branch coverage | 95.29% / 89.92% |
| Worker and HTTP-thread measurement | Both required and observed |
| Clean wheel and sdist installation | Passed; operations, report review, backup and receipts checked |
| ZIP build and fresh extraction suite | Passed; 429 manifest-covered files in this local build |
| Seeded actual-runtime replay | 8 admissions, 6 unique jobs, 2 idempotent retries; expected results match |
| Historical notebook restore | Original 0.2.0 backup compatibility passed offline |
| English documentation and links | Passed |

The full suite includes new hard-deadline/descendant cleanup, real worker death,
running cancellation, recovery budget exhaustion, immutable policy binding,
actual PDF-text-to-OCR fallback, paired-population leakage, hidden group regression,
review-bound case memory, HTTP roles/capacity and non-destructive integrity cases.
The original exact money, receipt, compatibility and fault-injection gates remain.

`validation.json` records reproduction commands and corrected failures/fixtures.
`quality_results.json`, `distribution_checks.json`, `test_results.json`,
`delivery_checks.json` and `operations_probe.json` contain measured results.
The probe ran after the final verification jobs completed. Its small synthetic
burst and cache timings are observations, not a sustained-capacity benchmark.

The owner explicitly requested publication of the integrated version. The
committed request uses `publish=true`; the publication workflow requires all nine
CI jobs on the exact source, an immutable matching tag and the existing
version-specific approval/asset guards. Build-time `published=false` is preserved
as an honest observation until a remote release is independently checked.

Actual fresh-runtime Colab acceptance, live cloud-account authorization,
production capacity and automatically learned accuracy remain unestablished.
