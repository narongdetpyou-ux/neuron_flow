# In-memory performance benchmark

```bash
python -B tools/benchmark.py --output-dir /tmp/neuron-benchmark
```

Python 3.10+ and the standard library suffice. Defaults measure read_csv_bytes, validate_document, compute_document, verify_document and the combined in-memory csv_pipeline at 10, 100, 1,000 and 10,000 items. Synthetic inputs are checked against independently generated integer-minor-unit totals before and after measurement. Source generation and interpreter startup are outside function timing.

Each function/size pair runs in a fresh subprocess with two warmups. Repetitions target roughly 25 ms per sample, capped at 1,000; seven samples use perf_counter_ns without tracemalloc. Median/min/max describe per-invocation averages within samples, not individual-request latency percentiles. Cyclic GC stays enabled; explicit collection before samples is outside the timer.

Memory is measured separately: Python KiB is the maximum of three tracemalloc incremental-allocation measurements while retaining the result; RSS MiB is whole-worker high-water memory including interpreter, imports, input and timing runs. Unsupported RSS measurement is null/n/a. 1 KiB=1,024 bytes and 1 MiB=1,048,576 bytes. These checks exclude Runtime workers, IPC, SQLite and report I/O. Direct-function input size does not prove it fits engine messages.

```bash
python -B tools/benchmark.py --sizes 100 1000 --cases compute_document csv_pipeline --repeats 9 --memory-repeats 3 --output-dir /tmp/neuron-benchmark-selected
```

Results are benchmark.txt, benchmark.csv and benchmark.json with samples, settings and environment. Choose a fresh output directory. Compare only like-for-like environments/settings; use [full-runtime measurements](BENCHMARK_RUNTIME.md) for the actual CLI path.
