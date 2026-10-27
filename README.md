# Neuron Flow 0.2.0

Validate multiple purchase documents from UTF-8 CSV, verify money with Decimal and an
independent integer-satang calculation, and deliver reports traceable to original CSV records.
Python 3.10+ and the standard library; THB, one machine, no API keys.
See [the Thai guide](README_TH.md) for the complete data contract and operating instructions.

The user authorized closing and publishing version 0.2.0 with the disclosed limitation that
**actual Google Colab acceptance has not been run**. Steps 1–5 passed local verification:
the original 38 tests remain separate from 65 new tests, and all 100 acceptance documents
match the locked reference. Fresh-runtime Colab upload/run/resume/download acceptance in
step 6 remains open; this release does not claim that all six steps passed.
Authorization is recorded in `RELEASE_APPROVAL.json`; actual results are recorded in
`verification/v0_2_0/test_results.json` and `BUILD_STATUS.json`.

## Quick start

Extract `dist/neuron_flow_v0.2.0.zip` and run from its `neuron_flow` directory:

```bash
python -m neuron_flow csv examples/purchases.csv --batch-id demo --workspace batch_workspace
python -m neuron_flow batch-status demo --workspace batch_workspace
python -m neuron_flow batch-resume demo --workspace batch_workspace
python -m neuron_flow csv examples/purchases_invalid.csv --batch-id mixed --workspace batch_workspace
```

The normal example produces 2 VALID documents totaling 412.70 THB. The mixed example produces
1 VALID, 2 INVALID, no ERROR and one ungrouped row; only its VALID total of 10.00 is certified.
Reports are written to `batch_workspace/batch_reports/<batch_id>/`:

- `summary.csv`: document status, declared/computed totals, difference, error count, source rows, engine status.
- `details.json`: the frozen full report, errors, versions, original source records and job history.
- `source.csv`: the exact original bytes, including a UTF-8 BOM when present.

`receipt.artifacts` contains absolute paths, byte sizes and verified SHA-256 values.
Using the same source and ID reuses completed steps and artifacts without rewriting them.
Changed source, contract, system/Agent versions or workflow settings under an existing ID produce a conflict.
Omitting `--batch-id` derives an ID from the immutable batch identity.

## CSV contract and statuses

```csv
document_id,item_id,description,quantity,unit_price,declared_total,currency
INV-001,A,สมุด,2,125.50,310.70,THB
INV-001,B,ปากกา,3,19.90,310.70,THB
```

All seven headers are required exactly once; column order may differ. UTF-8/BOM, quoted commas
and multiline records are supported. IDs group documents after trimming. Item IDs must be unique
within a document. IDs/descriptions require text of at most 500 characters; quantity is an ASCII
integer from 1 to 1,000,000; price is nonnegative with at most two decimals and at most 10¹² THB.
Declared totals are nonnegative, at most 10²² THB and numerically consistent across each document.
Currency is THB. Each document supports the original 1–10,000 item bounds, subject to engine message limits.

Blank/missing-ID records remain visible in `ungrouped_rows`. Malformed record widths remain
attached to their document or ungrouped entry with errors. Invalid headers, encoding and CSV
syntax reject the file. Source row numbers identify the first physical line of a CSV record,
including records containing quoted newlines.

`document_status` is VALID, INVALID or ERROR. INVALID means incorrect data or a declared-total
mismatch; ERROR means the system could not confirm a result. `engine_status` is separate:
INVALID data can be processed successfully. Only VALID amounts contribute to `certified_total`.
`difference` is computed minus declared. Invalid-data amounts remain null except for a verified
TOTAL_MISMATCH, which includes the actual total and difference.

## Recovery and limits

Resume the same workspace without uploading the source again. SQLite retains source bytes,
step attempts, history and the frozen report payload. Default timeout is 5 seconds after worker
readiness; the attempt limit is 2 including the first attempt. Invalid data does not retry.
A killed/hung worker or interrupted controller consumes an attempt. Exhausted documents remain
ERROR while other documents continue. The user starts recovery; there is no automatic restart service.

Documents are scheduled sequentially while worker processes are reused. `--workers` sets a
capacity bound (1–32; default 3). One controller owns each workspace. CSV input is limited to
16 MiB; engine messages and its individual job report are limited to 1 MiB. Documents exceeding
engine limits become ERROR without blocking other documents. The 100-document fixture (80 valid,
20 invalid) defines this round's acceptance scope, rather than a production proportion or document-count limit.

Publication uses atomic file creation, fsync, full-file conflict preflight and content/SHA-256
read-back. A crash between files resumes only missing artifacts; receipt persistence is the
completion marker. Existing conflicting content is preserved. Workers handle hangs/crashes but
are trusted Python code, not a security sandbox. The package does not implement OCR/PDF parsing,
tax, discounts, autonomous learning or external-service transaction guarantees.

CLI exit codes: 0 for completed delivery/status without ERROR; 1 for document ERROR or a returned
DELIVERY_FAILED state; 2 for invalid setup/input or an exception, including delivery conflicts.
Inspect counts and receipts as well as the process exit code.

## Verification and release packaging

```bash
python tools/verify.py                         # original 38-case baseline
python tools/build_acceptance_fixture.py --check
python tools/verify_v020.py                    # 65 new tests + 100-document comparison/evidence
python tools/build_delivery.py                # build and verify the release ZIP locally
```

New results and A01–A12 local evidence live under `verification/v0_2_0/`; reference answers and
their lock are in `acceptance/`. `build_delivery.py` verifies a fresh local extraction and writes
`dist/neuron_flow_v0.2.0.zip`. Its ZIP hash/check results are stored outside the ZIP in
`verification/v0_2_0/delivery_checks.json` to avoid a self-referencing archive hash.
The legacy JSON demo remains available through `python -m neuron_flow demo`.

## Colab notebook and backups

Open `START_COLAB.ipynb` in a fresh Colab runtime. Upload the version 0.2.0 ZIP, verify every packaged
file against `SHA256SUMS.txt`, upload exactly one CSV, run the CLI, inspect reports, resume,
run the full verifier and download the backup. Notebook code invokes importable project modules
through subprocesses; no agents are defined in notebook cells.

Colab storage is temporary. Download the backup before ending the session. It includes a
consistent SQLite workspace backup, reports, verification evidence and session metadata.
An optional restore cell accepts that backup after loading the same project ZIP in a fresh runtime.
Restore uses the original `/content/neuron_flow_workspace` path because receipts contain absolute paths,
and refuses to overwrite an existing workspace. Offline syntax checks do not establish actual
Colab acceptance. Fresh-runtime upload, execution, resume and completed download evidence remains
in `remaining_acceptance`. `release_ready` reflects local verification and the authorization in
`RELEASE_APPROVAL.json`; `colab_acceptance_complete` remains false until actual Colab acceptance
is completed. Windows/macOS have not been verified in this round.
