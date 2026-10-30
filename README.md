# Neuron Flow 0.4.0

**Supervised purchase-document validation with traceable reports and recoverable batches.**

Neuron Flow checks whether purchase line items are well formed and whether their
quantity × unit-price totals agree with a document's declared total. It calculates
money with `Decimal`, verifies it independently with integer minor units, and
retains source evidence, processing history and report hashes.

Use it as a local checking step before an operator accepts data into an accounting
or procurement workflow. The core CSV workflow uses Python 3.10+ and the standard
library on one trusted machine, without an AI model or API keys.

Saved batch reports can also be explained with source-row evidence and compared
across candidate runtimes using `report-explain` and `report-compare`. See the
[read-only report review guide](docs/REPORT_REVIEW.md).

## Suitable data

| Input | What the system does | Preparation needed |
| --- | --- | --- |
| Purchase line items in CSV or TSV | Group documents, validate fields and verify totals | Map to the seven required fields in the data contract below |
| JSON purchase-row arrays | Normalize rows to the same CSV contract | Exactly seven fields per object; arbitrary JSON schemas are not accepted |
| Values-only Excel `.xlsx` | Normalize a selected worksheet and retain row provenance | Install the Excel extra; select a sheet when several exist; export formulas as values |
| Text PDFs or UTF-8 receipt text | Extract page text and candidate lines for review | Confirm the original and provide reviewed CSV before financial validation |
| Scanned PDFs and PNG/JPEG/TIFF receipts | Run optional local Tesseract OCR and retain evidence | Install OCR/language dependencies, then confirm and provide reviewed CSV |
| Drive, Dropbox, S3 files or a Sheets range | Fetch a snapshot through an explicit connector command | Credentials plus a supported format; Sheets requires the expected headers and literal values |

The strongest fit is **prepared purchase data with integer quantities,
nonnegative prices, one currency per document and a declared total equal to its
line-item sum**. Different documents may use different supported currencies.
Tax, discounts, shipping, refunds and fractional quantities need separate business
rules; Neuron Flow does not infer or calculate those adjustments.

PDF/OCR output is review material. It does not automatically turn every receipt
layout into verified line items. See [data suitability and market fit](docs/DATA_AND_MARKET_FIT.md)
for preparation rules, concrete examples and unsuitable workloads.

## Target users and markets

| Group | Useful job | Current fit |
| --- | --- | --- |
| Small finance and accounts-payable teams | Check prepared purchase exports before acceptance or posting | Primary fit for an operator-run local pilot |
| Bookkeeping and accounting service providers | Apply consistent checks to client-prepared purchase files and retain evidence | Primary fit when an operator maps and reviews client data |
| Procurement and operations teams | Investigate malformed items and declared-total differences | Supporting check; order/receipt/invoice matching needs separate rules |
| Developers and workflow integrators | Embed staging, validation, recovery and reports in a larger application | Extension use; Python APIs remain experimental during 0.x |
| Retail, distribution and other receipt-heavy businesses | Prepare receipt evidence and verify reviewed purchase rows | Conditional fit; human transcription/review remains necessary |

These are proposed matches to implemented capabilities, not claims of customer
adoption or measured market demand. The current scope is one operator/controller
per workspace on one machine. Shared accounting platforms, unattended invoice
approval and enterprise multi-user operations need additional capabilities.

Only `VALID` documents enter `certified_total` or `certified_totals`. Here,
**certified means verified by the configured data and arithmetic checks**. It
does not establish supplier authenticity, absence of fraud, tax compliance,
permission to pay or an accounting audit opinion. Duplicate item IDs are checked
within a document; duplicate-invoice detection across suppliers/batches is not implemented.

## Source and published versions

**Version 0.4.0:** document intake now accepts CSV/TSV/JSON/Excel,
text PDFs and scanned/image receipts with optional local Tesseract OCR. Receipt
extraction requires reviewed CSV before financial verification. Connectors fetch
from Google Drive, Google Sheets, Dropbox and Amazon S3; an explicit command can
write literal report values to Google Sheets. Optional dependencies and credentials
are needed only for the selected adapters. See the [integration guide](docs/INTEGRATIONS.md)
and run `python -m neuron_flow adapters`. These changes are not in the published 0.3.0 ZIP.
Supported 0.2.0/0.2.1/0.3.0 and 0.4.0.dev0 CSV workspaces retain their original
creation version, source and reports; new batches record 0.4.0. The owner has
authorized publication of this version. The Colab notebook demonstrates the core
CSV workflow; actual fresh-runtime acceptance remains separately unrun.

The [operations guide](docs/OPERATIONS.md) covers the supervised local queue,
HTTP admission, deadlines, extraction alternatives, phase metrics, pure cache,
reviewed case memory, candidate gates and shared integrity tools. The committed
publication request enables `publish=true` only for its matching approved version
after all nine exact-source CI jobs succeed. Published assets and observed state
are available from [GitHub Releases](https://github.com/narongdetpyou-ux/neuron_flow/releases).

Version 0.3.0 adds **46 currencies**, including USD, EUR, GBP, CNY, JPY and SGD,
with currency-specific 0, 2 or 3 decimal places and separate certified totals per currency.
Release [v0.3.0](https://github.com/narongdetpyou-ux/neuron_flow/releases/tag/v0.3.0) was published on 29 October 2026 at 16:49:18 Bangkok time (09:49:18 UTC).
The [post-publication check](verification/publication_v0_3_0_2026_10_29/README.md) verifies all six assets and 367 ZIP manifest entries.
The older 0.2.1 assets do not contain this addition. See the
[currency contract](docs/CURRENCIES.md) for all codes, precision and compatibility rules.

The previously published 0.2.1 added submit-only intake, live batch discovery, supported 0.2.0 workspace reuse,
structured size-limit failures, bounded event cursors and byte-stable Windows fixture checkouts.
Version 0.2.1 was published on 28 October 2026 at 16:17:10 UTC; obtain downloads and their
checksums from [release v0.2.1](https://github.com/narongdetpyou-ux/neuron_flow/releases/tag/v0.2.1).
The [post-publication check](verification/publication_2026_10_29/README.md) records successful
downloads of all six assets, their hashes and the distinction between source and workflow commits.
Read the [evidence index](verification/README.md) for dated test results and their scope.

Actual Colab acceptance remains `not_run`. The historical 0.2.0 approval is preserved in
[the archive](verification/archive/RELEASE_APPROVAL_0_2_0.json); neither local tests nor
publication approval substitute for actual Colab acceptance.

## Intended use and operating envelope

For operators, developers and reviewers checking prepared purchase data on one trusted local machine.
The locked acceptance workload contains 100 documents; parser limits are not a throughput
or production SLA. Agents are trusted code, documents run sequentially, and users control
workspace access, backups and retention. Python library APIs are experimental during 0.x;
see [API examples](docs/PYTHON_API.md) and the [maintainer runbook](docs/MAINTAINER_RUNBOOK.md).

Development checks: [branch coverage and static gates](docs/QUALITY.md),
[wheel/sdist installation](docs/PACKAGING.md), and
[full-runtime benchmark](docs/BENCHMARK_RUNTIME.md). Historical 0.2.1 Windows/macOS smoke checks passed on Python 3.10/3.12 in
[the Windows-fix CI run](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40717586187).
The [0.3.0 main CI](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40852073574) passed all nine jobs, including Windows/macOS smoke on Python 3.10/3.12.
Full fault-injection validation remains scoped to Linux.

## Quick start

Run from this checkout, or download the approved `neuron_flow_v0.4.0.zip` from [GitHub Releases](https://github.com/narongdetpyou-ux/neuron_flow/releases), verify its `.sha256` and run from its extracted `neuron_flow` directory:

```bash
python -m neuron_flow csv examples/purchases.csv --batch-id demo --workspace batch_workspace
python -m neuron_flow batch-list --workspace batch_workspace
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

Try a batch containing USD, EUR, JPY and KWD documents:

```bash
python -m neuron_flow csv examples/purchases_international.csv --batch-id international --workspace batch_workspace
```

The result has `certified_totals` of EUR `25.50`, JPY `1500`, KWD `3.702` and USD
`21.50`. Mixed-currency batches have `currency: null` and `certified_total: null`;
they do not combine unlike units or convert exchange rates. Their document results
and `summary.csv` include `currency`.

`receipt.artifacts` contains absolute paths, byte sizes and verified SHA-256 values.
Using the same source and ID reuses completed steps and artifacts without rewriting them.
Changed source, incompatible contracts/Agents or workflow settings under an existing ID produce a conflict.
Omitting `--batch-id` derives or reuses a compatible batch identity. If multiple compatible batches
match, list them and supply an explicit ID instead of selecting one silently.

## Submit first, run or recover later

```bash
python -m neuron_flow csv examples/purchases.csv --submit-only --batch-id queued --workspace batch_workspace
python -m neuron_flow batch-list --workspace batch_workspace
python -m neuron_flow batch-resume queued --workspace batch_workspace
```

`--submit-only` persists source/identity and returns the batch ID and its actual status before
starting Agents. A new batch has no attempts yet; resubmission can return an already completed
status. If the controller stops before returning its final CLI result, `batch-list` discovers
the persisted ID without the CSV or notebook session metadata. Listing is read-only, does not
start workers or take the controller lock, and works while the controller runs. `batch-status`
still uses the Runtime workspace lock.

## Supported 0.2.0 workspace compatibility

Version 0.4.0 can reuse supported 0.2.0/0.2.1/0.3.0/0.4.0.dev0 schema-1 CSV workspaces, including the markerless 0.2.0 format,
when the CSV contract, Agent definitions/versions and workflow settings match the compatibility
policy. Existing identity, creation-version provenance, frozen payloads and reports stay unchanged.
Old results retain their creation version; new work identifies 0.4.0. Compatibility does not
implicitly accept every patch version or changed contract. Backup restoration still requires
the original absolute workspace path; relocation support is outside this release.

## CSV contract and statuses

```csv
document_id,item_id,description,quantity,unit_price,declared_total,currency
INV-001,A,Notebook,2,125.50,310.70,THB
INV-001,B,Pen,3,19.90,310.70,THB
```

Documentation and interface text use English; original UTF-8 business data remains unchanged.
All seven headers are required exactly once; column order may differ. UTF-8/BOM, quoted commas
and multiline records are supported. IDs group documents after trimming. Item IDs must be unique
within a document. IDs/descriptions require text of at most 500 characters; quantity is an ASCII
integer from 1 to 1,000,000; price is nonnegative and at most 10¹² in its currency.
Declared totals are nonnegative, at most 10²² in that currency and numerically consistent across each document.
Use an exact uppercase supported currency code, identical on every row of a document.
JPY, KRW, VND, CLP and ISK allow no fraction; BHD, KWD, OMR, JOD and TND allow up
to three decimals; the other supported codes allow up to two. Extra precision is
rejected without rounding, including trailing zeroes. Each document supports the
original 1–10,000 item bounds, subject to engine message limits.

THB-only intake retains `purchase-csv-v1` and its original report format. Intake
with any non-THB currency selects `purchase-csv-multicurrency-v1`. Existing v1 batches
resume under their saved rules; a currency rejected in a saved v1 batch stays INVALID.
Use a new batch ID to process that source under the new contract. The locked
100-document fixture is replayed explicitly under legacy rules, preserving its
80 VALID / 20 INVALID historical answers; under the new contract its USD document
can be accepted. See [currency compatibility](docs/CURRENCIES.md).

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

`MessageSizeError` records the phase, `observed_bytes`, `limit_bytes` and `retryable: false`.
A permanently oversized individual job report becomes a visible document ERROR in the final
batch report, without endlessly retrying delivery of identical oversized content. Successful
batch-artifact delivery does not remove that ERROR.

Report delivery uses atomic file creation, fsync, full-file conflict preflight and content/SHA-256
read-back. A crash between files resumes only missing artifacts; receipt persistence is the
completion marker. Existing conflicting content is preserved. Workers handle hangs/crashes but
are trusted Python code, not a security sandbox. Optional document adapters have
their own [limits and review requirements](docs/INTEGRATIONS.md); parsers/OCR
are not a security sandbox. The package does not implement tax, discounts,
autonomous learning or external-service transaction guarantees.

CLI exit codes: 0 for completed delivery/status without ERROR; 1 for document ERROR or a returned
DELIVERY_FAILED state; 2 for invalid setup/input or an exception, including delivery conflicts.
Submit-only returns 0 for accepted intake and batch-list returns 0 for successful inspection;
neither certifies that documents are VALID. Inspect processing counts and receipts as well as the exit code.

## Verification and packaging

```bash
python -B tools/check_repository_docs.py
python tools/verify.py --output-dir /tmp/neuron-flow-verification-new/baseline
python tools/build_acceptance_fixture.py --check
python tools/verify_current.py --output-dir /tmp/neuron-flow-verification-new
python tools/build_delivery.py --candidate --verification-dir /tmp/neuron-flow-verification-new --output-dir dist
```

`verify.py` runs the legacy baseline separately; `verify_current.py` discovers current-version
tests and compares the locked 100-document reference. These POSIX examples use a new temporary
output directory; choose another unused path when needed and keep new results separate from
historical evidence. The [0.3.0 publication record](verification/publication_v0_3_0_2026_10_29/README.md) links the exact source, successful CI/release runs and downloaded hashes.
The historical [0.2.1 published-run reports](verification/publication_2026_10_29/README.md)
contain 38 baseline and 120 current cases, plus 10 release guards. Older sibling reports in
`verification/v0_2_1/` describe earlier runs; its [stage gates](verification/v0_2_1/stage_gates.json)
now summarize the exact published release and link to the corresponding reports.
`verify_v020.py` is retained for historical 0.2.0 use, rather than current-version verification.
Reference answers and their lock remain in `acceptance/`.

The package builder verifies a fresh extraction and writes a version-named ZIP, its
`.sha256`, the Notebook, `SHA256SUMS.txt`, `BUILD_STATUS.json` and `delivery_checks.json` to
the chosen output directory. Inspect these current output files instead of historical 0.2.0
build-status files. `BUILD_STATUS.json` and `delivery_checks.json` describe the build before
publication, so their `published:false` values are preserved in the immutable release assets.
Use the [0.3.0 post-publication check](verification/publication_v0_3_0_2026_10_29/README.md) for the observed remote release state. Building does not publish.
Without `--candidate`, matching approval for
the exact package version is required; older approvals cannot satisfy that requirement.
The legacy JSON demo remains available through `python -m neuron_flow demo`.

CI is configured for Python 3.10/3.12. The manual release workflow defaults to `publish=false`.
The 28 October 2026 research snapshot reports a successful main CI run for
`d5a72ab64a7439c999faf7ba47f77239d1238a11`; see the [implementation record](docs/RESEARCH_IMPLEMENTATION.md).
This historical observation does not establish the outcome of later runs. Subsequently,
[Manual release run #3](https://github.com/narongdetpyou-ux/neuron_flow/actions/runs/40723991028)
completed both build and publication. The post-publication check confirms the native assets
are downloadable with matching hashes. The earlier HTTP 401 describes the historical upload
attempt, not the outcome of release 0.2.1. Actual Colab acceptance remains `not_run`.

## Local performance benchmark

```bash
python -B tools/benchmark.py --output-dir /tmp/neuron-benchmark
```

Measure the five core in-memory CSV operations at 10–10,000 items using only the
standard library. Timing and memory tracing run separately; JSON, CSV and text
results distinguish extra Python allocations from total worker-process peak RSS.
See [benchmark methodology and options](docs/BENCHMARK.md).

## Edge cases and mock inputs

```bash
python -B tools/edge_cases.py --output-dir /tmp/neuron-edge-cases
```

Generate reproducible CSV/JSON fixtures and run direct-function and isolated CLI
checks. Unexpected crashes, timeouts, or integrity failures produce exit code 1;
expected invalid data remains distinct. See [coverage and known findings](docs/EDGE_CASES.md).

## Colab notebook and backups

Use a notebook and ZIP from the same version. Open `START_COLAB.ipynb` in a fresh Colab runtime, verify every packaged
file against `SHA256SUMS.txt`, upload exactly one CSV, submit/run the CLI, inspect reports, resume,
run the full verifier and download the backup. Notebook code invokes importable project modules
through subprocesses; no agents are defined in notebook cells.

Colab storage is temporary. Download the backup before ending the session. It includes a
consistent SQLite workspace backup, reports, verification evidence and session metadata.
An optional restore cell accepts that backup after loading the same project ZIP in a fresh runtime.
Restore uses the original `/content/neuron_flow_workspace` path because receipts contain absolute paths,
and refuses to overwrite an existing workspace. Offline syntax checks do not establish actual
Colab acceptance. Follow the [Colab acceptance checklist](docs/COLAB_ACCEPTANCE.md) and
[evidence template](docs/colab_acceptance_TEMPLATE.json), initially `not_run` with false checks.
Supply completed actual evidence through `verify_current.py --colab-evidence path/to/evidence.json`.
The validator checks a user-supplied assertion against package/fixture identity and local
consistency; it is not automatic remote attestation. Its synthetic unit tests are not actual
Colab evidence. Supplied inconsistent/incomplete evidence is `invalid` and makes verification
exit unsuccessfully; omitted evidence remains `not_run`.

Actual fresh-runtime upload, execution, resume, manually confirmed receipt of the download and
restore in a second runtime remain required for complete Colab acceptance. Release approval
does not supply those facts. See [the 0.2.1 development scope](docs/DEVELOPMENT_0_2_1.md).
The 0.3.0 Windows/macOS smoke matrix passed in its own CI run; no smoke subset certifies the full fault-injection suite.

## Project policies

See [contributing](CONTRIBUTING.md), [code of conduct](CODE_OF_CONDUCT.md),
[security reporting](SECURITY.md), [support](SUPPORT.md) and [governance](GOVERNANCE.md).
Maintained documentation, examples, issue forms and notebook instructions use English.
Frozen source fixtures and archived release evidence preserve their original bytes and hashes.
See the [English documentation index](docs/README.md) for all guides.
[Repository policy notes](docs/REPOSITORY_POLICIES.md) distinguish proposed
protections from GitHub settings that could actually be applied.
