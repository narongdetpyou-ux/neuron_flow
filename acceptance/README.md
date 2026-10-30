# Locked Neuron Flow 0.2.0 reference fixture

This fixture was locked before implementation of the CSV receiver and verifier.
It contains **100 documents: 80 VALID and 20 INVALID**, with no input-only ERROR.
That ratio is an acceptance-test design, not an estimate of real data quality or
a system document-count limit. Its original UTF-8 descriptions remain test data;
the English documentation migration does not change fixture bytes or hashes.

| File | Purpose |
| --- | --- |
| `input.csv` | UTF-8 without BOM, using the seven-column contract |
| `expected_results.json` | Per-document answers and individual reasons |
| `cases.json` | Case titles, coverage and expected reason codes |
| `fixture_lock.json` | SHA-256, byte sizes and reviewed lock history |

```bash
python tools/build_acceptance_fixture.py
python tools/build_acceptance_fixture.py --check
```

The generator imports neither neuron_flow nor Decimal/float arithmetic. It uses
integer minor units to calculate answers; INVALID reasons are set in advance,
not obtained from the implementation being tested. INV-001 is the original
310.70 THB example. Cases include quantity/price boundaries, zero prices,
Unicode, commas/quotes and multiline records. Legacy currency rules are replayed
explicitly: USD is invalid in this frozen THB-only contract.

## Answer contract

Documents retain first-appearance order. Money is two-decimal text; difference is
computed_total minus declared_total. source_rows and errors[].row_number identify
the first physical CSV line of a record, counting the header as line 1. Multiline
records therefore shift following row numbers by more than one.

INVALID computed_total/difference values are null except for TOTAL_MISMATCH,
where the computed amount and difference are independently known. declared_total
uses the first row's normalized valid value, or null when missing/inconsistent.
Each error has row_number, field, reason_code, expected and actual; actual keeps
the source text. An empty currency gives REQUIRED only. A USD row conflicting
with an initial THB row produces both CURRENCY_UNSUPPORTED and CURRENCY_CONFLICT.

| Reason code | Meaning under the locked legacy contract |
| --- | --- |
| REQUIRED | Required field is empty |
| QUANTITY_FORMAT | Quantity is not an unsigned 1–7 digit integer |
| QUANTITY_RANGE | Quantity is outside 1–1,000,000 |
| PRICE_FORMAT | Price is not unsigned numeric text with at most two decimal places |
| PRICE_RANGE | Price exceeds 1,000,000,000,000 THB |
| DUPLICATE_ITEM_ID | Item ID repeats within a document |
| CURRENCY_UNSUPPORTED | Currency is not THB |
| CURRENCY_CONFLICT | Currency differs from the first row |
| DECLARED_TOTAL_CONFLICT | Declared total differs from the first row |
| TOTAL_MISMATCH | Declared and calculated totals disagree |

The fixture supplies input cases for A01 and A03–A07. Invalid headers (A02),
missing document IDs (A08), BOM, no-retry behavior and system interruption/recovery/
conflict cases (A09–A12) need separate execution evidence. A frozen answer set
alone does not establish that an implementation passes acceptance.

Changes require review of affected cases and reasons, followed by:

```bash
python tools/build_acceptance_fixture.py --update-lock --reason 'Reviewed reason for this change'
```

The generator retains previous hashes in lock history; an ordinary run refuses
to overwrite files that conflict with the lock. No lock update is part of the
English documentation migration.

## Historical pre-implementation check

Generation and --check passed for 201 CSV records, 100 documents, 80 VALID,
20 INVALID, zero ERROR and no ungrouped rows. An independent csv.DictReader plus
Decimal calculation matched integer-minor-unit answers for every VALID document
and TOTAL_MISMATCH case, including INV-001 at 310.70 THB. Physical row references,
error ownership, null invalid-data amounts, case counts, hashes and sizes also
matched. This checked the reference's consistency, not the later implementation.

Locked expected_results.json SHA-256:

```text
f72f753bb474b4e94743f3c917227625c5a8b0eb556e50c91fe6f3a90dd20b26
```
