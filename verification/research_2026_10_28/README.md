# Historical research implementation — 28 October 2026

Work was pushed on fix/research-hardening-20261028 from main d5a72ab.
See the [implementation plan](../../docs/RESEARCH_IMPLEMENTATION.md) and
[proposal/status backlog](../../docs/RESEARCH_BACKLOG.json). The report supplied
recommendations, not publication approval or experimental results. Its source
SHA-256 is retained in events_edge_summary.json.

## Recorded source 9b0ffd8 on Linux/Python 3.12.14

- All 38 baseline + 117 current cases passed with zero failures/errors/skips.
- Ten release guards, the locked 100-document fixture and report examples passed.
- All 1,608 prior edge cases passed, including the three earlier cursor crashes;
  no timeout occurred.
- The quality run's 155 cases are the same baseline/current suite, not 155
  additional cases. Line/branch coverage was 91.86%/83.73%, including real CLI and
  spawn workers. Package E9,F lint and strict inspection.py mypy passed.
- Wheel/sdist installed into clean environments outside the checkout; CSV gave
  2 VALID / 412.70 THB, checked artifact hashes/sizes and unchanged recovery.
- The candidate ZIP verified 223 manifest entries and passed a fresh full verifier.
- API examples and backup/restore passed, including damaged backup and occupied
  destination cases.

[summary.json](summary.json) binds source, fingerprint and commands to runs.
coverage.json contains measured gaps; no 100% coverage is claimed. quality_initial.json
and events_regression_results.json are intermediate results. Prior v0_2_0/v0_2_1
machine evidence was not overwritten.

## Runtime benchmark

Three samples per size, five items per document, used real CLI startup/IPC/SQLite/
fsync/delivery. Whole-batch p50 for 1/10/100 documents was about 0.17/0.54/4.24
seconds. A real controller interruption and 100-document resume took about 4.10
seconds without repeating completed work; see benchmark_runtime.json.
These environment-specific three-sample results are not reliable tail-latency/SLA
estimates, aggregate process-tree RAM, write-amplification measurements or a claim
of comprehensive worker-PID visibility.

## Historical external state

[Candidate artifacts](../../release-assets/v0.2.1-research-candidate/) contained
ZIP/wheel/sdist, hashes, CycloneDX inventory and unsigned local provenance. They
were not a GitHub Release or signed attestation.

At that time Git access worked through the platform proxy while GitHub API access
returned Forbidden. Adding api.github.com to an environment settings draft did
not establish that it had been applied. PR/issue/milestone creation, branch Actions
inspection and ruleset apply/read-back remained unavailable in that run. Git
connectivity alone did not establish API/admin rights or a need for a new token.
Windows/macOS CI had been added but runner results were not yet observed. Actual
Colab remained not_run, and 0.2.1 had no approval/publication at that point.
Later publication is recorded separately in the verification index.
