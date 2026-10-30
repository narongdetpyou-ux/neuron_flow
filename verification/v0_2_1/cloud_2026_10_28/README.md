# Historical cloud test run — 28 October 2026

This record describes the original Linux/Python 3.12.14 run. JSON timestamps are
UTC; the original narrative date used Asia/Bangkok. Evidence remains unchanged.

| Work | Recorded result |
| --- | --- |
| Dependencies | No third-party runtime packages; setuptools 84.2.1 installed for build; pip check passed |
| Regressions | 38 baseline + 102 current + 10 release guards = 150 passed, no failures/errors/skips |
| Benchmark | 20 cases: five functions at 10/100/1,000/10,000 items |
| Edge cases | 1,608 cases: 1,605 expected outcomes, three crashes, no timeout |
| Mock inputs | 1,577 files with manifest/SHA-256 in ZIP |

## Finding at that run

All three crashes shared one bug: events --after accepted values outside SQLite's
signed-int64 range and raised OverflowError. Inputs -9223372036854775809,
9223372036854775808 and 10^100 crashed; -2^63 and 2^63-1 worked. This run recorded
and reproduced the issue without fixing application code. The edge runner exited
1 rather than changing expected answers to make a crash pass. Invalid CSV/data
and expected document ERROR were distinguished from unexpected crashes. Later
research work fixed the cursor issue; this record preserves its original finding.

At 10,000 items the in-memory pipeline median was 103.90 ms/invocation, additional
Python allocation peak 17.38 MiB and process peak RSS 35.94 MiB. Timing is the
median of seven sample averages; memory was measured separately. RSS includes
interpreter/inputs; timed work excludes Runtime, SQLite, IPC and report I/O.
These are the recorded environment/settings, not a promise for another machine.

## Evidence and reproduction

- [Benchmark](benchmark/benchmark.json), [CSV](benchmark/benchmark.csv), [table](benchmark/benchmark.txt).
- [Edge report](edge_cases/REPORT.md), [all cases](edge_cases/results.json), [crashes](edge_cases/failures.json).
- [Mock ZIP](edge_cases/mock-data.zip), [manifest](edge_cases/manifest.json).
- [Regression](regression/test_results.json), [baseline](regression/baseline/test_results.json), [guards](regression/release_workflow_tests.log).
- [Dependency check](dependencies/dependency-check.json), [pip check](dependencies/pip-check.log).
- [Provenance](provenance.json), [checksums](ARTIFACT_SHA256SUMS.txt).

Acceptance evidence and sample reports are retained. SQLite workspaces, process/
lock files, virtualenvs and caches were excluded. Absolute paths in raw reports
are original observations, not directions to create those locations. The mock
corpus stays in ZIP instead of adding thousands of files to Git.

From the project, run tools/benchmark.py, tools/edge_cases.py and
tools/verify_current.py with separate unused output directories. Reproduction of
the original crash requires that historical source; current code has the fix.
Actual Colab execution and publication are outside this run's evidence.
Run sha256sum -c ARTIFACT_SHA256SUMS.txt from this evidence directory to check
the original retained artifacts.
