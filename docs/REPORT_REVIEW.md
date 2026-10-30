# Explain and compare saved reports

Two standard-library commands inspect the existing `details.json`, `summary.csv`
and `source.csv` in a delivered batch report directory. They do not create a
workspace, run Agents, resume jobs, modify original artifacts or write to cloud
connectors. Existing runtime execution and financial verification are unchanged.

## Evidence-bound explanations

After delivering a batch with `python -m neuron_flow csv`, pass the report folder:

```bash
python -m neuron_flow report-explain batch_workspace/batch_reports/purchases
python -m neuron_flow report-explain batch_workspace/batch_reports/purchases --document-id INV-001
```

Use the actual batch ID or directory returned by your own delivery. The output is
JSON with an English summary for each selected document, recorded reason codes,
source row numbers and claims such as:

```json
{"path":"/documents/0/errors/0/reason_code","value":"TOTAL_MISMATCH"}
```

Paths refer to the checked `details.json`; `/documents/0` is an array position,
not a document identifier. Claims retain exact JSON types, and monetary amounts
remain strings. Negative/ambiguous indices and fields outside the evidence
allowlist are rejected by `score_claims`. No language model is used.

`VALID`, `INVALID` and `ERROR` retain their existing meanings. Missing document
identifiers remain visible in `ungrouped_rows`. A document filter retains batch
claims and ungrouped-row context. A successful explanation describes the checks
recorded in a report; it does not approve a supplier, detect all fraud or authorize
payment. An empty list of claims does not establish evidential support.

## Offline candidate comparison

Generate reference and candidate reports in separate workspaces using their
respective runtime versions, then compare their report directories:

```bash
python -m neuron_flow report-compare reference/batch_reports/purchases candidate/batch_reports/purchases
```

Both reports must use **identical original CSV bytes and the same data contract**.
Even a BOM/line-ending change is a different source. A candidate's different
version or Agent identity is allowed and remains visible in the result.

Comparison checks counts, currency totals and each document's status, currency,
source rows, declared/computed totals, difference, errors and engine status.
Batch/job IDs, version labels, attempt histories and timestamps are not outcome
equality criteria. Artifact SHA-256 values identify both inspected report sets.
Error records, including their typed expected/actual values, are compared exactly.

| Exit code | Meaning |
| --- | --- |
| `0` | Explanation completed, or comparable reports agree |
| `1` | Comparable reports contain different semantic results |
| `2` | Missing, malformed or inconsistent artifacts; unknown document ID; or incomparable sources/contracts |

An invalid source document can be explained with exit code `0`: this is successful
inspection, not a declaration that the document is `VALID`. A forged computed
total is rejected as an inconsistent report with exit code `2`, rather than
counted as a valid candidate result.

This command compares saved outputs. It does not execute candidate code, capture
live traffic, measure speed, select a winner or automatically activate a policy.

## Validation and limits

The loader rejects symlink artifacts/directories and duplicate/non-finite JSON,
reuses the existing source/financial payload checks, and compares the summary CSV
with the checked document results before producing an explanation or comparison.
Each details/summary artifact is bounded at 64 MiB; the existing original CSV
limit remains 16 MiB. These are inspection limits, not new batch runtime limits.

The checks establish internal source/report consistency. Hashes identify the
bytes inspected; they are not authentication of the person who supplied all three
files, and these commands do not read the workspace database's delivery receipt.
Use existing receipt/recovery verification when checking an original delivery.
The inspector also does not independently establish that every recorded invalid
reason is the correct diagnosis; it presents the recorded evidence without
inventing a reason.

Python APIs remain experimental during 0.x:

```python
from neuron_flow.report_review import compare_reports, explain_report, score_claims

explanation = explain_report("batch_workspace/batch_reports/purchases")
comparison = compare_reports("reference/batch_reports/purchases", "candidate/batch_reports/purchases")
assert comparison["agreement"], comparison["differences"]
```

The adapted patterns come from the previously inspected ABC-Causal Service 0.2.0
`evidence.py`, `shadow_runner.py` and `evaluation.py`: structured claims, explicit
comparison fields and separation from state-changing actions. Neuron Flow uses
its own purchase contracts and verifier; no ABC controller, model, HTTP server,
queue or additional runtime dependency is included.
