# Quality checks and branch coverage

Install development tools plus optional adapters and Tesseract for full format/OCR coverage:

```bash
python -m pip install -r requirements-dev.txt '.[documents]'
python -B tools/check_quality.py --output-dir /tmp/neuron-quality-new
```

Use a fresh directory outside the checkout. The helper stores logs, quality_results.json, coverage.json and coverage.xml and fails if lint, typing, tests, data combination or any coverage floor fails. A core-only environment explicitly skips unavailable optional-format tests; complete release verification requires them to run.

Ruff E9,F checks correctness across neuron_flow/. Strict mypy currently gates inspection.py; imported modules and the whole package are not claimed to be strictly typed. Coverage runs the entire unittest suite with branch measurement, CLI subprocess tracing and multiprocessing spawn workers. `.coveragerc` enables concurrency=multiprocessing, subprocess/_exit patches and SIGTERM collection. The helper verifies execution of the first worker statement by AST, so controller-only measurement cannot pass. SIGKILL and Windows TerminateProcess can lose coverage data; Linux is the measured coverage platform.

| Scope | Minimum line coverage | Minimum branch coverage |
| --- | ---: | ---: |
| Entire package | 91% | 83% |
| csv_agents.py | 97% | 93% |
| reporting.py | 89% | 80% |
| engine.py | 90% | 78% |

The combined coverage floor is 89%. Do not lower floors or exclude modules merely to pass. Add meaningful failure-path tests and review any deliberate scope/baseline change. Independent financial verification must stay separate from calculation. The initial 28 October 2026 baseline measured 91.93% lines and 83.73% branches over 150 tests; subsequent results and counts belong to their dated reports. Coverage is evidence about exercised code, not proof of all state combinations or production readiness.

Development versions are pinned in requirements-dev.txt separately from runtime extras. English documentation and notebook checks run through tools/check_repository_docs.py.
