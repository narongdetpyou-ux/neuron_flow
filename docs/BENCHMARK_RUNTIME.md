# Full CLI/runtime benchmark

```bash
python -B tools/benchmark_runtime.py --output-dir /tmp/neuron-runtime-benchmark
python -B tools/benchmark_runtime.py --sizes 1 10 100 1000 --repeats 5 --output-dir /tmp/neuron-runtime-large
```

Defaults use 1/10/100 documents, five items per document and five samples per size. Each sample uses a new workspace and real CLI subprocess, including interpreter startup, worker spawn/IPC, SQLite, report checks, fsync and shutdown. The timer wraps the complete command; source generation is excluded and no warmup is subtracted.

JSON retains every sample, environment/source fingerprint, whole-batch p50/p95, median-time documents/second and source/artifact/database/workspace sizes. p50 is the median; p95 is nearest rank ceil(0.95*n), so five samples make it the observed maximum, not a reliable production tail estimate. These are batch timings, not per-document latency or an SLA.

Every sample checks VALID counts, independently generated integer totals and all three artifact hashes/sizes. It removes the upload and times recovery separately, asserting unchanged results, successful steps, attempts, events and artifact bytes/mtime.

The interruption workload defaults to 100 documents, configurable with --recovery-documents. Read-only SQLite polling waits for at least one delivered document and unfinished work, then kills the real controller and resumes without its original upload. Completed results and event prefixes must survive and no step may exceed two attempts. Polling connections always close. Linux also checks observed child PIDs have stopped, counting zombies as stopped; other platforms report that observation as null. A controller that finishes before the intended interruption makes the recovery scenario fail rather than claiming success. Recovery timing begins after the kill; this does not force interruption during calculation. Dedicated regressions separately cover specific hung-worker/kill points.

Linux/macOS resource.RUSAGE_CHILDREN reports maximum reaped-child high-water RSS across the benchmark, not concurrent process-tree memory, incremental allocations or per-sample RAM. Unsupported measurement is null. File sizes are final sizes, not cumulative writes or write amplification; transient WAL may already be checkpointed. Use OS tracing for actual I/O.

--timeout bounds commands/checkpoint waits, default 180 seconds. Errors, wrong results or timeouts return exit 1 with successful=false. Select an empty destination and retain workspaces/logs for inspection. All data is synthetic; this benchmark does not publish or call cloud services.
