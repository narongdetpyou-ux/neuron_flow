# Supervised local document operations

Version 0.4.0 adds an optional operations layer around the existing purchase
contracts. Core runtime dependencies remain Python's standard library. Install
document extras and Tesseract only for the formats that need them.

## Start with a durable job

```bash
python -m neuron_flow ops submit examples/purchases_international.csv --key example-001 --workspace ops_workspace
python -m neuron_flow ops work --once --workspace ops_workspace
python -m neuron_flow ops status JOB_ID --workspace ops_workspace
python -m neuron_flow ops events JOB_ID --after 0 --workspace ops_workspace
python -m neuron_flow ops metrics --workspace ops_workspace
```

Use the returned `job_id`. Submission returns `QUEUED`, an acceptance receipt.
Only the worker attempts extraction and processing. `work` without `--once`
continues until interrupted. `--stage-only` on submission stops after intake;
`ops cancel JOB_ID` requests cancellation. Completed results retain artifact
receipts and source identities. Unknown IDs are errors.

The SQLite admission transaction binds an idempotency key to the exact source,
settings and adapter environment. Reusing a key with different input is a
conflict; repeating an identical accepted request returns its existing result.
The default active capacity is 100, and the retained-record limit is 10,000.
Records are not silently evicted: the limit rejects new admissions. Limits count
jobs, and each original source is bounded by the existing 16 MiB limit. They are
not a complete disk or process-RAM reservation.

One OS-locked operations worker owns a workspace. The existing runtime lock still
protects batch execution. An interrupted worker's running job can be reclaimed,
with at most two total worker claims. An adapter/environment change fails the old
admission explicitly. Completed intake and batch artifacts are reused through
their existing integrity checks. This does not provide exactly-once arbitrary
external writes.

## Deadlines, extraction choices and review

`--timeout SECONDS` sets an admission-to-completion budget, including queue time;
expired queued jobs do not run. Running trusted operations use separate Python
processes and bounded JSON files. On POSIX, cancellation kills the operation
process group, including OCR descendants. Parent death is monitored. Cleanup has
its own bounded wait and may extend elapsed wall time beyond the processing
budget. This is trusted-code failure isolation, not a hostile-code sandbox.

Terminal job states are `COMPLETED`, `REVIEW_REQUIRED`, `FAILED`, `TIMED_OUT`,
`CANCELLED` and `EXPIRED`. An exhausted budget cannot certify a new result.
Cancellation can preserve already-written immutable intake or batch artifacts;
it does not roll them back. Events and failure details retain the intake ID for
inspection/recovery when available.

```bash
python -m neuron_flow ops stage receipt.pdf --strategy pdf-text --strategy pdf-ocr --timeout 90 --workspace ops_workspace
```

The fixed methods are `native`, `pdf-text` and `pdf-ocr`. The latter two are
different configurations of the existing PDF/Tesseract adapters. An empty text
page permits the next configured method; arbitrary methods are not invented.
There are at most three unique alternatives and one total extraction deadline.
Attempt records include method/version, parameter identity, source/candidate
hashes, duration, cache use and terminal reason. The policy/environment binding
is part of intake identity. No method changes amounts to make checks pass.

PDF/text/image outputs remain review drafts. Use `intake-review` with explicit
reviewed CSV and `--reviewer`, then `intake-run` as documented in the
[integration guide](INTEGRATIONS.md). A corrected review creates a new revision.

The operations worker also isolates each controller validator with a five-second
validation budget, in addition to the whole-job deadline. Python callers can set
`validation_timeout_s` on `Runtime` or `BatchRuntime`; validators must then be
importable top-level functions. The budget is durably bound to Agent identities,
so changing it requires compatible original settings or a new job/batch ID.
Legacy callers retain their existing execution mode and persisted bindings.

## Monitoring and cache

Metrics retain a bounded window of actual phase samples, while total counters
continue increasing. Queue, extraction, CSV parsing, validation, calculation,
verification, controller contract validation, report delivery and whole-batch
durations are distinct. Worker execution durations are measured by the controller;
the supervised batch returns its actual samples for aggregation. Percentiles are
computed from retained raw samples, not averages of process percentiles.

RSS is the current reporting process on supported Linux hosts; unavailable
measurements are `null`. Child RSS is not summed or guessed. There is no GPU or
model drift claim. `ops drift reference.json current.json` describes changes in
explicit `{format,status,currency,source_bytes}` profiles; it changes no policy.

`ExtractionCache` is a bounded LRU/TTL pure-result cache. Keys bind original bytes,
format, method/version, sheet, OCR/language settings, source/dependency versions,
schema, monetary policy and review scope. Values are detached copies. Errors,
verification results, receipts and OCR outputs are not cached. OCR is excluded
because the complete binary/language-data identity is not captured. Cache byte
limits measure encoded payloads rather than full RAM. Existing durable intake
reuse often avoids extraction already; extra speed benefits depend on workload.

## Candidate comparisons and policy releases

`report-compare` compares existing reports. `ops shadow REPORT_DIRECTORY` actually
runs the current CSV pipeline in a temporary workspace and compares its result.
`--candidate-factory package:function` may supply trusted local Agent definitions.
This is not a security sandbox; the built-in shadow runner makes no connector
writes, while custom trusted Python remains responsible for its own effects.

`ops gate population.json` evaluates explicit paired records with these fields:

```json
{
  "reference": [{"case_id":"case-001","cluster_id":"layout-a","split":"holdout","format":"csv","report_directory":"reference/report","latency_ms":10,"attempts":1,"first_method_success":true}],
  "candidate": [{"case_id":"case-001","cluster_id":"layout-a","split":"holdout","format":"csv","report_directory":"candidate/report","latency_ms":9,"attempts":1,"first_method_success":true}],
  "training_clusters": []
}
```

Freeze population identities and optional efficiency tolerances before tuning.
The gate requires matching case IDs, source bytes, contracts, clusters and split
metadata. It rejects training/evaluation cluster overlap, clusters crossing
validation/holdout, identical source bytes crossing those splits, changed
semantic results and worse first-method success. `--max-p95-ratio` and
`--max-attempt-ratio` enable explicit overall and format/currency-group efficiency checks. Timing metrics in an
imported population are supplied observations, not authenticated measurements.
Groups report format/currency regressions; no statistical significance is claimed.
`route_variant` assigns whole explicit clusters deterministically for experiments.

`ops policy-accept population.json accepted.json --strategy native` additionally
requires final holdout cases. Candidate records must include `intake_workspace`
and `intake_id`; their checked intake policy, normalized/reviewed source and
report batch must bind the proposed configuration. Plain report agreement cannot
authorize an unrelated method. Policy files are created exclusively, carry a
content hash, and refuse incompatible adapter environments. Use the accepted
file explicitly with `ops stage SOURCE --policy accepted.json`.
Use `--timeout` when accepting a non-default extraction budget; stage, admission
and policy acceptance share a 120-second default, which is a configurable budget
rather than a latency guarantee. Keep the evaluation budget identical to the
configuration being accepted. The accepted file controls subsequent staged runs.

Keep older
accepted files selectable for rollback. No policy activates automatically.

## Reviewed structural case memory

`ops memory-learn INTAKE_ID candidate.csv --workspace WORKSPACE --profile '[0,1,0,0,0,1]' --policy-version POLICY_ID --method native --cluster-id layout-a`

The six fixed process-vector positions are operator-defined normalized features
in `[0,1]`; use the same documented feature definition across a memory version.
Equal dimensions, finite values and policy versions are enforced. The referenced
intake must contain an explicit operator review. Outcome labels are computed by
exact comparison with that reviewed CSV; callers cannot pass their own truth
label. Both matches and mismatches are retained with original/review/candidate
identities. Only `train` records can be learned; exclude evaluation clusters when
retrieving through the Python API. The bounded store deduplicates identical
evidence and rejects capacity overflow or invalid stored identities.

`ops memory-retrieve --workspace WORKSPACE --profile '[0,1,0,0,0,1]' --policy-version POLICY_ID`
returns similar process cases. Retrieval is advisory, and reviewer names are
not authenticated identities. It cannot certify a new invoice or claim an
automatically learned accuracy improvement.

## Local HTTP adapter

Set distinct `NEURON_READ_TOKEN` and `NEURON_WRITE_TOKEN` environment variables,
each containing at least 32 ASCII characters, then run:

```bash
python -m neuron_flow ops serve --workspace ops_workspace --port 8765
```

The server binds only `127.0.0.1`. Bearer read tokens can query `/health`,
`/metrics`, `/jobs/ID` and `/jobs/ID/events?after=CURSOR`; write tokens also admit
`POST /jobs` and request `POST /jobs/ID/cancel` with `{}`. Requests are JSON, have
an explicit length and a 24 MiB body limit. Source content is supplied as base64,
not a server filesystem path. Fields outside the versioned model are rejected.

```json
{"idempotency_key":"import-001","filename":"purchases.csv","source_base64":"BASE64_BYTES","timeout_s":120,"run":true}
```

Optional fields are `ocr`, `language`, `sheet` and `strategies`. Acceptance is
HTTP 202; capacity is 429, idempotency conflict is 409, malformed requests are
400, missing/wrong permissions are 403, and unknown jobs/routes are 404. The
adapter is for a trusted local operator, without a production SLA, public TLS
endpoint, distributed consumers, Redis or multi-user approval. It does not
automatically publish accounting/Sheets results.

## Integrity and workload evidence

`ops backup WORKSPACE NEW_BACKUP_DIRECTORY` stages a SQLite online backup under
runtime/worker/admission locks, hashes files by streaming and verifies read-back.
Stop standalone manual intake/review while backing up; a changing file tree is
rejected. `ops integrity BACKUP_DIRECTORY` returns explicit missing/extra/changed
files against the existing `backup_SHA256SUMS.txt` format. Symlinks and unsafe
manifest paths are rejected. `ops restore BACKUP_DIRECTORY ORIGINAL_WORKSPACE`
verifies before restoring and refuses an existing destination. The original
absolute path remains required. Hashes provide integrity against a manifest,
not authorship authentication.

The notebook uses the shared backup/restore checks after its standalone project
ZIP bootstrap verification. Historical 0.2.0 notebook-backup restore remains
tested; actual fresh-runtime Colab acceptance remains separately unrun.

`python -B tools/probe_operations.py --requests 8 --output-dir NEW_DIRECTORY`
replays seeded synthetic valid/invalid purchase inputs through the actual queue,
checks emitted reports against an independent integer fixture generator, and
records real timings, idempotent retries and pure-cache repeat measurements.
These are synthetic-input runtime measurements, not simulated request latencies
or a production capacity estimate.

## Source-pattern coverage

| Inspected source | Adaptation |
| --- | --- |
| ABC R01 evidence | `report_review.py`: typed report claims and verified artifacts |
| ABC R02 monitoring | `telemetry.py`, runtime phase samples and local metrics |
| ABC R03–R04 shadow/evaluation | `evaluation.py`: actual shadow runs, identified paired gates and cluster assignment |
| ABC R05 cache | `extraction.py`: exact-input bounded pure cache |
| ABC R06–R08 journal/jobs/worker | `operations.py`: SQLite transactions, idempotency, bounded admission and one supervised owner |
| ABC R09–R10 API/schemas | `service.py`, strict `request_model` and `operations_cli.py` |
| ABC R11 structural memory | `case_memory.py`: review-bound outcomes and fixed-dimension advisory retrieval |
| ABC R12 synthetic workloads | `tools/probe_operations.py`: seeded real-runtime replay |
| Black Swan A–B deadlines/attempts | `supervision.py`, validator isolation and immutable intake attempt evidence |
| Black Swan C–E gates/memory/strategies | Explicit candidate population identity, frozen policy files, reviewed cases and vetted bounded alternatives |
| Black Swan F integrity | Shared streaming manifest checks, staged backup and non-destructive restore |

These are separate Neuron Flow adaptations of the selected reusable patterns.
They do not embed the original ABC allocation controller, statistical models,
generic float verifier or Black Swan domain-specific solvers.
