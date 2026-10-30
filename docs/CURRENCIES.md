# Currencies and exact minor units

The CSV and invoice JSON workflows support 46 currency codes. The core remains standard-library-only and does not call exchange-rate services. Use exact uppercase codes, not symbols or whitespace-normalized aliases. `usd`, ` USD`, `XXX` and `BTC` are rejected. The application table in [currencies.py](../neuron_flow/currencies.py) defines the supported scope.

| Maximum decimal places | Supported codes |
| --- | --- |
| 0 | CLP, ISK, JPY, KRW, VND |
| 2 | AED, AUD, BDT, BGN, BRL, CAD, CHF, CNY, CZK, DKK, EGP, EUR, GBP, HKD, HUF, IDR, ILS, INR, MXN, MYR, NOK, NZD, PHP, PKR, PLN, QAR, RON, RUB, SAR, SEK, SGD, THB, TRY, TWD, USD, ZAR |
| 3 | BHD, JOD, KWD, OMR, TND |

These are accounting minor units, not national cash-rounding rules. `unit_price` and `declared_total` use unsigned ASCII numeric text without grouping, signs or exponent notation. Quantity is an integer from 1 to 1,000,000. Maximum unit price is 10^12 and declared total is 10^22 in the document currency. Excess precision is rejected without rounding: USD `1.001`, JPY `1.0` and KWD `1.0001` are invalid, even when excess digits are zero.

| Currency | Unit price x quantity | Computed total |
| --- | --- | --- |
| USD | `10.75` x 2 | `21.50` |
| EUR | `8.50` x 3 | `25.50` |
| JPY | `500` x 3 | `1500` |
| KWD | `1.234` x 3 | `3.702` |

Decimal calculation and independent integer-minor-unit verification remain separate. No float arithmetic certifies money. `difference` is computed minus declared, formatted with the same currency precision.

Every row of one document must have the same currency; mixed currencies produce CURRENCY_CONFLICT and INVALID. Different documents in a batch may use different currencies. Only VALID amounts contribute to `certified_totals`, separately by known currency. A known currency with only INVALID/ERROR documents has a formatted zero total; an unidentified currency creates no bucket. When multiple currencies or no identifiable currency exist, `currency` and `certified_total` are null. Never interpret this null as a cross-currency zero or combined total.

```bash
python -m neuron_flow csv examples/purchases_international.csv --batch-id international --workspace batch_workspace
```

The example has four VALID documents and certified totals EUR `25.50`, JPY `1500`, KWD `3.702`, USD `21.50`. There is no exchange conversion. Multicurrency document/summary reports include `currency`; the exact source bytes remain in `source.csv`.

THB-only sources retain `purchase-csv-v1`; sources containing another currency select `purchase-csv-multicurrency-v1`. Persisted legacy batches keep their original results and contracts. Use a new batch ID to process the same source under a different contract. The 100-document fixture deliberately replays the legacy contract using `legacy_thb=True`: its USD cases remain INVALID. The original fixture bytes, Unicode descriptions, hashes and expected answers remain unchanged; these are frozen test inputs rather than interface text.

`validate_document()` and `csv_workflow()` default to multicurrency mode; use `multicurrency=False` for explicit legacy replay. Invoice extract/calculate/verify Agents use version 2; old version-1 invoice jobs require their original runtime or a new job/workspace. Echo remains version 1 and CSV Agents retain their contract-bound identities. See [Python API](PYTHON_API.md).
