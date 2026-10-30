# Historical Neuron Flow 0.2.1 verification

English rendering of the recorded run summary. Original machine evidence and hashes
are unchanged; this translation is not a new test run.

- UTC: 2026-10-28T00:22:19.020357+00:00
- Python: 3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]
- Platform: Linux-6.18.55-x86_64-with-glibc2.41
- Current-at-that-run cases: 102
- Failures: 0; errors: 0; skipped: 0
- Local result: passed

The separate original 38-case baseline and locked 100-document reference
passed. The reference contains 80 VALID/20 INVALID documents. A01–A12 records
include field/total checks, invalid-data no-retry behavior, report traceability,
real hangs/worker deaths/controller interruption, recovery, duplicate delivery
and conflicts. See acceptance_matrix.json, acceptance_evidence/ and samples/.

Publication approval at this run: not approved.
Actual Colab acceptance was not_run; local checks and release approval do not
supply fresh-runtime upload, execution, recovery, confirmed download or restore.

See tests.log and test_results.json for exact cases and recorded results.
These single-machine historical observations do not certify later source,
self-learning behavior, other platforms or production service guarantees.
