# Neuron Flow 0.4.0 release notes

## 0.4.0 — approved release source

- Add supervised CSV/TSV/JSON/Excel intake, PDF and local OCR receipt drafts,
  explicit human review, immutable review revisions and selected Google Drive,
  Sheets, Dropbox and S3 connectors. Receipts require reviewed CSV before exact
  financial verification; connector writes remain explicit.
- Use English in maintained product documentation, notebook instructions,
  examples and issue forms; preserve historical evidence and locked bytes.
- Add report-backed explanations and exact comparison of saved outcomes.
- Add an optional durable SQLite queue, strict loopback HTTP admission with
  separate read/write tokens, bounded ownership/recovery, cancellation and whole
  job deadlines. Bound trusted extraction and controller-validator execution.
- Record immutable extraction attempts, explicit native/PDF text/PDF OCR
  configurations, phase timings and bounded pure extraction cache results.
- Add actual isolated shadow execution, identified paired candidate gates,
  training/validation/holdout separation and evidence-bound frozen policy files.
- Add review-bound structural case retrieval and retain matches/mismatches;
  retrieval remains advisory and does not certify documents or activate policies.
- Share streaming integrity diagnostics and consistent SQLite backup checks
  between CLI and notebook recovery. Preserve non-destructive restore and the
  original absolute workspace path requirement.
- Add a seeded synthetic purchase replay tool using the actual queue/runtime
  and independent integer fixture labels; observed timings are workload-specific.
- Preserve exact currency minor-unit verification, 46 currencies, legacy CSV
  contracts and supported 0.2.0/0.2.1/0.3.0/0.4.0.dev0 workspaces.
- Record explicit 0.4.0 publication approval. A committed request waits for all
  nine exact-source CI jobs, pins an immutable tag and invokes the existing
  guarded release workflow with `publish=true`. Manual publication defaults
  remain unchanged.

Actual fresh-runtime Colab acceptance and live cloud-account authorization remain
separate from local/synthetic verification. Full fault-injection and process-group
cancellation validation are scoped to Linux; Windows/macOS run their documented
smoke subset. This is a single-machine beta without a production SLA, FX/tax
interpretation, arbitrary-layout understanding or authenticated multi-user review.
Refer to dated verification records and the exact tag's workflow for measured
results; publication is observed separately from build-time approval.

## 0.3.0 — published 29 October 2026

- Support 46 currencies in purchase CSV and invoice JSON, with currency-specific
  0/2/3 decimal places. Decimal calculation and independent integer-minor-unit
  verification remain separate.
- Reject excess precision without rounding, including excess trailing zeroes.
- Report certified_totals separately by currency for VALID documents. A mixed
  batch has currency and certified_total set to null; no unlike units are added.
- Include currency in multicurrency document and summary reports and verify
  source amounts/hashes before delivery.
- Preserve THB-only contracts, original frozen answers and saved v1 results.
  Use a new batch ID to process old source under a different contract.
- Add international examples and precision, tampering, CLI and recovery tests.

Every row of one document uses the same currency. Invoice JSON extract/calculate/
verify Agents use version 2; saved version-1 invoice jobs require the original
runtime or new jobs/workspaces. Python APIs remain experimental.

The preparatory 173-case regression run and subsequent exact-source CI/publication
have distinct records. The [post-publication check](verification/publication_v0_3_0_2026_10_29/README.md)
confirms the release, six downloaded assets, hashes and 367 ZIP manifest entries.
All nine main CI jobs passed, including the Windows/macOS smoke matrix. Full
recovery/fault-injection coverage remains scoped to Linux; actual Colab acceptance
is not_run. This release does not include PDF/OCR or the new cloud adapters.

## 0.2.1 — published 28 October 2026

- Add csv --submit-only, persisted batch discovery and resume without the upload.
- Reuse supported 0.2.0 workspaces under explicit schema/contract/Agent rules.
- Report permanent size-limit errors without blocking other documents.
- Reject events --after values outside SQLite signed-int64 range with structured
  errors instead of a traceback or creation of an unnecessary workspace.
- Keep golden fixture bytes stable on Windows.
- Add pinned/hash-locked build tools, isolated wheel/sdist checks, branch
  coverage, correctness lint and scoped strict typing.
- Add full-runtime/recovery benchmarks, API examples and backup/restore runbooks.
- Index evidence and preserve superseded approvals/stage gates in the archive.

The [published-run record](verification/publication_2026_10_29/README.md) identifies
38 baseline, 120 current and 10 release-guard cases. Earlier candidate counts are
historical. Linux verification and Windows/macOS Python 3.10/3.12 smoke passed.
This THB-only CSV/CLI release has no PDF/OCR or production SLA. Actual Colab
acceptance remains not_run; backup restore requires the original absolute path.

## 0.2.0 — historical published release

- Add multi-document UTF-8/BOM CSV grouping with retained malformed/ungrouped rows.
- Separate VALID, INVALID and ERROR from engine_status; calculate with Decimal
  and independently verify integer minor units.
- Limit processing to two attempts, isolate document failures and resume without
  repeating successful steps.
- Atomically deliver summary.csv, details.json and source.csv, verify content/
  SHA-256 before receipt persistence and preserve conflicting files.
- Supply a Colab notebook and a locked 100-document acceptance fixture.

The historical run passed 38 baseline plus 65 current cases with no failures,
errors or skips. All 100 answers matched (80 VALID/20 INVALID), including real
hung-worker, worker-death, interrupted-controller and report-before-receipt tests.
The ZIP was checked again after extraction. Its original documentation languages
and published assets are historical; they are not rewritten by this migration.

The owner authorized publication with disclosed missing real Colab acceptance.
Offline notebook checks and Linux results did not establish fresh-runtime upload,
execution, recovery, download and restore. The original scope was one machine,
THB, a 16 MiB CSV limit and 1 MiB engine messages; Windows/macOS were unverified
at that time. The 100-document fixture was never a document-count limit.

Download versioned ZIPs/checksums from [GitHub Releases](https://github.com/narongdetpyou-ux/neuron_flow/releases)
and verify both archive and internal manifest hashes before using a package.
Publication approval does not turn unrun acceptance checks into passed checks.
