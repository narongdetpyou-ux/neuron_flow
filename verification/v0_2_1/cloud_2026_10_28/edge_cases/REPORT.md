# Edge-case test results

Python 3.12.14; deterministic seed 20261028; 1,500 CSV mutations.

| Suite | Cases | Handled as expected | Unexpected failures |
| --- | ---: | ---: | ---: |
| Direct CSV functions | 1,554 | 1,554 | 0 |
| Real CLI subprocesses | 54 | 51 | 3 |
| Total new cases | 1,608 | 1,605 | 3 |

No timeouts. Of the CSV cases, 124 rejected malformed files with CsvInputError;
1,430 were processed as VALID/INVALID/ungrouped data. Expected invalid inputs and
structured document ERROR due to message limits are counted as handled, not crashes.
Validated boundaries include 10,000 lines at the maximum quantity and price
(total 10^22 THB), 10,001 lines, Unicode/control characters, bad CSV/JSON,
source size limits and isolation of oversized documents.

## Confirmed bug: events cursor overflows SQLite INTEGER

The three failing CLI cases use --after values -9223372036854775809,
9223372036854775808 and 10^100. They exit 1 with an uncaught OverflowError
instead of rejecting invalid input with a structured JSON error (exit 2).
Both signed int64 endpoints were tested successfully. The CLI accepts unbounded
Python integers, then storage.py passes them into SQLite's signed int64 binding.
This is one defect reproduced by three inputs. Production code has not been changed.

Reproduce from the project directory:

```bash
.venv/bin/python -B -m neuron_flow events nonexistent \
  --after 9223372036854775808 --workspace /tmp/neuron-events-overflow
```

Run the reusable mock generator and test harness with a new output directory:

```bash
.venv/bin/python -B tools/edge_cases.py --output-dir /tmp/neuron-edge-cases
```

The harness currently exits 1 because it detects the confirmed failures. It does
not suppress them or redefine crashes as success. Its timeout cleanup, wrong-expectation
detection and refusal to overwrite existing evidence were checked separately.

## Existing regression suite

38 runtime baseline + 102 current + 10 release-guard cases: all 150 passed,
with no failures, errors or skips. Fixture lock and report-example checks passed.
These existing tests do not cover the out-of-range events cursor.

## Evidence files

- manifest.json: mock input filenames, expectations, sizes and SHA-256 hashes.
- results.json: all new case results, exact CLI commands, stdout and stderr.
- failures.json: full reproductions and tracebacks for the three failing cases.
- mock-data/: generated CSV and JSON files (including deliberately invalid bytes).
- mock-data.zip: mock inputs, manifest and reports; excludes workspace databases.

This bounded test set does not prove absence of all possible defects.
