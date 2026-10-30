# Synthetic document intake examples

Every example describes two notebooks at USD 12.50 each, total USD 25.00.
No real receipt, account, token or personal data is included.

| File | Purpose |
| --- | --- |
| `purchases.json`, `purchases.tsv`, `purchases.xlsx` | Structured input normalized to the purchase CSV contract |
| `receipt.txt`, `receipt.pdf` | Text receipt evidence requiring review |
| `receipt.png`, `receipt_scan.pdf` | Local OCR examples requiring review |
| `receipt_reviewed.csv` | Manually checked rows for these synthetic receipts only |

From the repository root, install the selected extras, then run:

```bash
python -m neuron_flow intake examples/intake/purchases.json --workspace batch_workspace
python -m neuron_flow intake examples/intake/receipt.pdf --workspace batch_workspace
python -m neuron_flow intake examples/intake/receipt_scan.pdf --ocr --workspace batch_workspace
```

Use the returned ID with `intake-status`, `intake-review`, and `intake-run`.
See [the Thai integration guide](../../docs/INTEGRATIONS_TH.md) for the full sequence.
