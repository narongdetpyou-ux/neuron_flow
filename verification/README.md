# Verification evidence index

Evidence is retained by source version and run. Similar CSVs or reports can be
intentional fixtures and provenance; matching contents alone do not make them junk.
Never overwrite old evidence to make a new run appear successful.

| Location | Purpose |
| --- | --- |
| `original_0_1_0/`, `baseline_0_1_0/` | Original implementation and early baseline runs |
| Root JSON/log/report files | Historical baseline and delivery evidence; not current release status |
| `v0_2_0/` | Immutable 0.2.0 acceptance, fault and delivery evidence |
| `v0_2_1/` | Historical candidate reports; `stage_gates.json` is now a published-release summary with explicit report links |
| `publication_2026_10_29/` | Observed v0.2.1 publication/download/hash check and unchanged reports copied from its exact released ZIP |
| `research_2026_10_28/` | Research implementation, intermediate and final results before Windows fix |
| `maintenance_2026_10_28/` | Cleanup inventory and release preparation validation |
| `archive/` | Preserved superseded root status, historical release approval and the original pre-publication 0.2.1 stage gates |

Current published files belong on [GitHub Releases](https://github.com/narongdetpyou-ux/neuron_flow/releases).
The [post-publication record](publication_2026_10_29/README.md) confirms v0.2.1 is published;
the [current summary](v0_2_1/stage_gates.json) points to the released run's 38 baseline,
120 current and 10 release-guard results, rather than the earlier 102-current-case snapshot.
The original stage gates remain byte-for-byte in
[`archive/stage_gates_0_2_1_pre_publication.json`](archive/stage_gates_0_2_1_pre_publication.json).
The immutable assets' `published:false` fields are build-time observations, not a live release query.

The `SHA256SUMS.txt` generated inside each package identifies that exact package,
not a continuously changing source checkout. To supply actual Colab evidence, run
the verifier from the verified extracted package. Source checkouts deliberately
do not retain a misleading old root package manifest.

Full Linux regressions, Windows/macOS smoke tests, local notebook checks and actual
Colab acceptance have separate scopes. A release approval does not turn `not_run`
Colab evidence into a pass. Old absolute workspace paths inside records are
historical observations, not required directories to create in a new checkout.
