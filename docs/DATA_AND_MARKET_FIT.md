# Data suitability and target users

Neuron Flow is a local, supervised validation component for purchase data. Its
job is to expose field errors, inconsistent totals and processing failures while
retaining the input and traceable results. The fit assessments below are product
positioning based on implemented contracts, not market-size or adoption evidence.

## The input model

| Field | Meaning | Required shape |
| --- | --- | --- |
| `document_id` | Groups a purchase document's rows | Nonempty text, at most 500 characters |
| `item_id` | Identifies an item within that document | Nonempty text, at most 500 characters; unique within the document |
| `description` | Preserves the supplied item description | Nonempty UTF-8 text, at most 500 characters |
| `quantity` | Number of items | ASCII integer from 1 to 1,000,000 |
| `unit_price` | Price per item | Nonnegative numeric text; maximum 10^12; currency precision applies |
| `declared_total` | Document total to check | Consistent across its rows; nonnegative numeric text, maximum 10^22 |
| `currency` | Unit for all amounts in the document | One exact uppercase supported code per document |

The calculation is the sum of `quantity × unit_price` across a document's rows.
The independent integer-minor-unit result must agree with the Decimal result and
the declared total. The [currency guide](CURRENCIES.md) lists all 46 supported
codes and precision rules. There is no exchange-rate conversion or silent rounding.

Prefer exact decimal strings in JSON and values-only worksheet cells. Format
support does not imply arbitrary schema understanding: names such as `invoiceNo`,
`netAmount` or nested objects need explicit mapping before structured intake.

## Suitability by source

| Source or workload | Fit | Preparation or missing capability |
| --- | --- | --- |
| Purchase line-item exports in CSV, TSV, JSON or `.xlsx` | Strong | Map the seven fields and make the declared total refer to the same line-item scope |
| Values-only Sheets purchase tables | Strong after mapping | Select a finite header/data range; source formulas are rejected |
| Text PDF invoices/receipts | Assisted | Extract text, inspect the original, then supply confirmed reviewed rows |
| Scanned PDFs and supported receipt images | Assisted | Run local OCR with installed language data, then review against the original |
| Drive, Dropbox or S3 documents | Depends on contents | Fetch the object, then follow its format's mapping/review requirements |
| Bank statements and payment transactions | Separate model needed | Their balance/debit/credit relationships do not implement the purchase-line contract |
| Contracts, legal/medical documents and general prose | Outside the supplied workflow | Extractable text alone does not provide purchase-validation semantics |
| `.xls`, `.xlsm`, HEIC and e-invoice XML | Unsupported formats | Convert externally to a supported format and confirm preserved meaning |
| Refunds, credit notes, negative/fractional quantities | Outside the current numeric contract | Explicit adjustment and quantity rules are needed |
| Totals with tax, discounts or shipping adjustments | Upstream business rules needed | Reconcile adjustments explicitly; never silently discard them to make a check pass |

The receipt route is `original → extraction/OCR → operator review → reviewed
purchase rows → financial checks → reports`. `REVIEW_REQUIRED` is a staging
state. `READY` means structured data is available to run. Neither state means
the document has passed financial validation.

## Worked examples

### A purchase export that fits directly

```csv
document_id,item_id,description,quantity,unit_price,declared_total,currency
INV-101,A,Notebook,2,10.00,25.00,USD
INV-101,B,Pen,1,5.00,25.00,USD
```

The two lines total USD `25.00`. With valid fields this is `VALID`. Repeating a
declared total of `26.00` instead gives `INVALID` with `TOTAL_MISMATCH` and
`difference: -1.00`, because difference is computed minus declared.

### An invoice with additional tax

If the items subtotal `25.00` and tax adds `1.75`, the payable total is `26.75`.
Using that payable total as `declared_total` produces a mismatch: the current
verifier has no tax engine. A separately governed preparation step may check the
subtotal here and reconcile tax/payable amounts elsewhere. Preserve both source
meanings; a subtotal check is not approval of the full bill.

### A receipt image

Intake retains original bytes, OCR text and candidate hints. An operator confirms
the items, quantities, prices, currency and intended total against the original,
then submits reviewed CSV. The verifier checks those rows; it does not independently
prove that a transcription matches the image. An incorrect but internally
consistent transcription can pass arithmetic checks, so review remains necessary.

## Target markets and the useful job

| Priority and group | Recurring problem | Value available now | Boundary |
| --- | --- | --- | --- |
| Primary: small finance/accounts-payable teams | Prepared purchase exports have malformed fields or unexplained totals | Repeatable local checks, per-document reasons and recoverable reports | An operator maps input and decides what to accept; no unattended payment approval |
| Primary: bookkeeping/accounting services | Different client files need consistent checking and source references | One explicit contract, retained sources, row references and review revisions | Client mapping and accounting interpretation remain external |
| Secondary: procurement/operations | Line-item errors need investigation | Traceable arithmetic checking | No two-/three-way matching across orders, goods receipts and invoices |
| Secondary: software vendors/integrators | A larger workflow needs a local verification/recovery component | Experimental APIs, explicit intake/connectors and structured reports | Caller supplies application UI, access control, scheduling and external transactions |
| Conditional: retail/distribution and receipt-heavy operations | Paper/PDF purchases need a path to a checked table | Local extraction, review evidence and verified row arithmetic | Review effort and unsupported adjustment layouts determine practicality |

The common use case is **checking prepared purchase data reproducibly with an
inspectable result**. Neuron Flow implements deterministic checks and trusted
Python Agents. It does not learn invoice layouts or select accounting policies.

## What the evidence establishes

| Capability | Establishes | Does not establish |
| --- | --- | --- |
| `VALID` and certified totals | Supplied rows passed the configured data/arithmetic contract | Supplier authenticity, fraud absence, compliance or authorization to pay |
| Source bytes and SHA-256 | Which bytes were retained and whether checked bytes changed | A digital signature or proof of who created the document |
| Reports and row references | Inspectable results and lineage to processed rows | A statutory audit opinion or third-party immutable audit trail |
| Recovery and artifact reuse | Compatible completed work can resume without repeating successful steps | An always-on service or cross-service exactly-once transaction |
| Per-currency totals | Separate checked amounts for supported codes | FX conversion or cash-rounding rules |
| OCR hints and review records | Extracted material and a local operator assertion | Automatic interpretation of every layout or multi-user approval signatures |

## A first pilot

Choose one operator, one local workspace and one prepared purchase-export type.
Map the fields, retain originals and run a representative batch with known answers.
Include a normal document, a field error and an intentional total mismatch. Inspect
every `INVALID`, `ERROR` and ungrouped row before accepting the output.

For structured input, measure preparation time, manual checks avoided and
differences found. For receipts, also measure review time, transcription corrections
and unsupported adjustment cases. These are suggested pilot measures; no measured
productivity saving or extraction-accuracy percentage is claimed.

The current envelope is sequential document scheduling, one controller per
workspace, 16 MiB source files and 1 MiB engine messages/individual job reports.
The locked 100-document fixture is a regression workload, not a document-count
limit or production SLA. Live cloud authorization and actual Colab acceptance
need separate evidence. See [integrations](INTEGRATIONS.md), the [runbook](MAINTAINER_RUNBOOK.md)
and the [verification index](../verification/README.md).
