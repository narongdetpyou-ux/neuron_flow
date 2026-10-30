# Edge-case and unfamiliar-input checks

```bash
python -B tools/edge_cases.py --output-dir /tmp/neuron-edge-cases
```

The runner creates reproducible synthetic CSV/JSON fixtures and exercises direct functions and isolated CLI processes. It covers malformed headers/record widths, encoding/BOM, quoted commas/newlines, missing IDs, duplicate items, invalid quantity/price/total formats, unsupported currencies, boundary sizes and workflow/runtime setup. Unicode/fuzz data remains intentional input coverage rather than interface language.

Expected input rejection is distinguished from unexpected crashes, timeouts or integrity failures. Unexpected behavior returns exit 1 and preserves source/response/log evidence. Read the current generated report for exact case counts and outcomes; old edge failures remain historical observations, not current results. Size caps are parser/message bounds, not throughput or production-SLA claims. Run --help for supported selectors and settings; use a fresh output directory.
