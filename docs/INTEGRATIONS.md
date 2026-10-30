# Document intake and external integrations

Neuron Flow 0.4.0.dev0 stages documents before handing normalized purchase rows to the existing financial verifier. Optional adapters run only when explicitly invoked.

## Supported inputs

| Format | Behavior | Requirement |
| --- | --- | --- |
| CSV | Preserve original bytes, including a UTF-8 BOM | Existing seven-column contract |
| TSV | Normalize tab-separated records to CSV | The same seven headers |
| JSON | Normalize an array of purchase-row objects | Exactly seven fields per object; duplicate keys rejected |
| Excel `.xlsx` | Read a worksheet and retain its name and row mapping | Select a sheet when several exist; formulas, error cells and macros rejected |
| Text PDF | Extract text by page and retain candidate receipt lines | Reviewed CSV required before processing |
| Scanned PDF | Render pages without extractable text and run local Tesseract | `--ocr`, OCR extra and Tesseract executable |
| PNG, JPEG, TIFF | OCR receipt images, including multi-frame TIFF | `--ocr`; reviewed CSV required |
| TXT | Retain receipt text or text exported from another OCR tool | UTF-8; reviewed CSV required |

PDF OCR processes pages with no extractable text. Inspect the original image as well when a page mixes text and images. The system does not automatically interpret every receipt layout or infer line items, tax, discounts or currency from ambiguous symbols. Receipt `hints` preserve candidate lines with page and line numbers; all extracted text remains in the manifest. Review is a local operator assertion, not an electronic signature or a multi-user approval system.

## Install selected adapters

From this checkout:

```bash
python -m pip install '.[pdf]'
python -m pip install '.[excel]'
python -m pip install '.[ocr]'
python -m pip install '.[s3]'
python -m pip install '.[documents]'
```

The last command installs every optional Python adapter dependency. OCR also requires Tesseract and language data. On a Debian/Ubuntu environment with package-install permission:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng
tesseract --list-langs
```

Use `--language eng` by default or another installed Tesseract language code; multiple installed languages can be joined with `+`. Unicode input remains supported. CSV/TSV/JSON/TXT and the Drive, Dropbox and Sheets HTTP adapters need no extra Python dependencies. Missing extras produce `DEPENDENCY_MISSING`.

## Stage, review and process

```bash
python -m neuron_flow adapters
python -m neuron_flow intake examples/intake/purchases.json --workspace batch_workspace
python -m neuron_flow intake purchases.xlsx --sheet Purchases --workspace batch_workspace
python -m neuron_flow intake receipt.pdf --ocr --language eng --workspace batch_workspace
```

Intake returns `intake_id`, `batch_id`, `bundle`, `status` and source/normalized SHA-256 values. Structured tables become `READY`; PDF, TXT and image receipts become `REVIEW_REQUIRED`. Staging does not start a batch or make additional network calls.

Replace `INTAKE_ID` with the returned identifier:

```bash
python -m neuron_flow intake-status INTAKE_ID --workspace batch_workspace
python -m neuron_flow intake-review INTAKE_ID examples/intake/receipt_reviewed.csv --reviewer operator --workspace batch_workspace
python -m neuron_flow intake-run INTAKE_ID --workspace batch_workspace
```

Inspect `original.bin` using the original extension recorded in `manifest.json`. Check page text and hints, then fill in `review_template.csv` using information actually confirmed against that source. The supplied reviewed example is valid only for the synthetic example receipts. Reviewed rows can still be INVALID when financial validation runs. A changed review creates a new intake ID; use the returned ID to process that revision. Original evidence and earlier batch reports remain intact.

Use `intake-run --submit-only` to persist queued work, then `batch-resume` with the returned batch ID. Repeated processing reuses the same batch, completed steps and verified artifacts.

## Supported services

The initial set covers widely used storage and spreadsheet services with official APIs. Accounts are not connected automatically.

| Service | Import | Export | Credentials |
| --- | --- | --- | --- |
| Google Drive | Download a stored file by ID | None | OAuth access token |
| Google Sheets | Snapshot an explicit values-only range as CSV | Overwrite an exactly sized range using RAW values | OAuth access token |
| Dropbox | Download an absolute path or `id:` | None | OAuth access token |
| Amazon S3 | Download an object, optionally pinning VersionId | None | AWS SDK credential chain |

Provide `GOOGLE_ACCESS_TOKEN` or `DROPBOX_ACCESS_TOKEN` through the operator's environment or secret manager. Use `--token-env CUSTOM_VARIABLE` to select another variable. Token acquisition, expiry and refresh are managed outside this version. Do not put token values in command arguments, project files or public evidence. AWS uses its normal SDK credential chain.

Drive requires a scope that can download the selected file, such as `drive.readonly`; Sheets reads use `spreadsheets.readonly` and writes use `spreadsheets`; Dropbox requires `files.content.read`; S3 requires `s3:GetObject` or `s3:GetObjectVersion` for a pinned version.

```bash
python -m neuron_flow connector-fetch google-drive FILE_ID --filename receipt.pdf --workspace batch_workspace
python -m neuron_flow connector-fetch dropbox /receipts/receipt.pdf --filename receipt.pdf --workspace batch_workspace
python -m neuron_flow connector-fetch s3 receipts/receipt.pdf --bucket EXAMPLE_BUCKET --version-id VERSION_ID --filename receipt.pdf --workspace batch_workspace
python -m neuron_flow connector-fetch google-sheets SPREADSHEET_ID --range 'Purchases!A1:G100' --filename purchases.csv --workspace batch_workspace
```

Drive downloads stored files; native Docs/Slides must be exported first. Sheets uses FORMULA rendering to reject source formulas instead of silently trusting calculated or cached financial values. The selected range must contain the seven headers and values-only rows. Provenance records the provider, locator and the SHA-256 of the snapshot actually processed. Changed cloud bytes produce a new identity.

Explicit export writes real destination cells when the operator invokes it:

```bash
python -m neuron_flow sheets-publish report.csv SPREADSHEET_ID --range 'Report!A1:G2'
```

The finite, sheet-qualified range must match the exact CSV dimensions, including its header. `A1:G2` is appropriate only for seven columns and two rows. RAW values remain literal strings, including descriptions beginning with `=`. Repeating the same write has the same effect; there is no automatic append. Cells outside the range are untouched, so an operator changing report dimensions must handle any obsolete trailing area. Export is separate from batch processing and is not a cross-service transaction.

## Evidence, recovery and limits

`workspace/intakes/<id>/` contains `original.bin`, `manifest.json`, and either `normalized.csv` or a review template plus `approval.json`. Bundles use complete temporary directories followed by rename; review files use exclusive atomic linking. Source and normalized hashes are checked on reuse. Review binds the manifest and reviewed CSV hashes. Batch IDs use `intake_<id>`.

Batch artifacts remain `summary.csv`, `details.json` and `source.csv`. For non-CSV imports, `source.csv` is the normalized/reviewed data, not the original PDF or workbook. The intake manifest maps normalized rows back to JSON indexes, worksheet rows or source-record ordinals. Back up the entire workspace, including `intakes/`; a SQLite-only backup omits originals and reviews.

Limits: source/normalized CSV 16 MiB; converted tables 100,000 data rows; PDF/images 50 pages/frames; rendered images 25 million pixels; extracted text two million characters; expanded XLSX 64 MiB and 2,000 ZIP members; OCR timeout 30 seconds per page; HTTP timeout 30 seconds. JSON decimal expansion is checked before fixed-point strings are allocated. HTTP redirects are refused, tokens are not forwarded across hosts, and errors report status/retryability without provider response bodies. There are no automatic network retries; inspect destination state after an uncertain export. Internally created S3 clients also have explicit timeouts and no hidden retries.

Parsers/OCR run locally without a security sandbox or separate memory/process isolation. These limits are not production SLAs. Tax/discount/FX interpretation, `.xls`, `.xlsm`, HEIC and e-invoice XML are outside this implementation. API contract tests use fake transports/clients; live cloud-account authorization and actual Colab acceptance remain `not_run`.

## Extension API

```python
from neuron_flow.connectors import fetch_source
from neuron_flow.intake import stage_document, review_document, run_document

data, origin = fetch_source("dropbox", "/receipts/receipt.pdf")
staged = stage_document("batch_workspace", data, "receipt.pdf", origin=origin)
# Inspect the original and prepare reviewed rows before review_document/run_document.
```

`prepare_document()` is a network-free format boundary. `fetch_source()` returns bytes and provenance and accepts an injected transport/client for tests. `stage_document()` persists evidence before batch execution. These Python APIs remain experimental; pin the tested version or commit.

## Official references

- [Drive files.get](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/get)
- [Sheets values.get](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get) and [values.update](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/update)
- [Dropbox SDK download protocol](https://github.com/dropbox/dropbox-sdk-python/blob/main/dropbox/dropbox_client.py)
- [S3 get_object](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html)
- [pypdf](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), [openpyxl](https://openpyxl.readthedocs.io/en/stable/tutorial.html), [pypdfium2](https://pypdfium2.readthedocs.io/en/stable/python_api.html), [Tesseract](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)
