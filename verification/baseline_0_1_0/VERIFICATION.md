# Historical Neuron Flow 0.1.0 verification

English rendering of the recorded run summary. Original machine evidence and hashes
are unchanged; this translation is not a new test run.

- UTC: 2026-10-27T23:02:56.786317+00:00
- Python: 3.12.14
- Platform: Linux-6.18.55-x86_64-with-glibc2.41
- Original baseline cases: 38
- Failures: 0; errors: 0; skipped: 0
- Local result: passed

The original 38-case suite covers Decimal calculation, independent integer
verification, report SHA-256, invalid inputs/results, real worker hangs/deaths,
controller interruption, worker reuse/capacity, bounded retries, identity
conflicts, workspace locking, event routing and interrupted report delivery.

The review distinguished worker completion time from controller collection,
excluded worker startup from execution timeout, preserved JSON types, rejected
validators returning False or mutating output, rejected duplicate/nonfinite
JSON and recorded separate delivery attempts.

Recorded CLI/integrity checks:

- syntax_compiles: passed
- fresh_cli_run_succeeds: passed
- independent_check_total_310_70: passed
- report_hash_matches_receipt: passed
- second_run_does_not_repeat_steps: passed
- second_run_does_not_rewrite_report: passed

Recorded test duration: 9.011 seconds; this is
correctness verification, not a performance benchmark.

See tests.log and test_results.json for exact cases and recorded results.
These single-machine historical observations do not certify later source,
self-learning behavior, other platforms or production service guarantees.
