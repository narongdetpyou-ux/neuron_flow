# Python distribution verification

The package supports Python 3.10+. Core runtime dependencies remain empty; optional document/cloud extras are declared in pyproject.toml. Build and development tools have separate requirements.

```bash
python -m pip install --require-hashes -r requirements-build.txt
python -B tools/check_distribution.py --output-dir /tmp/neuron-distribution-new
```

Use a new output directory outside the checkout. The checker verifies pinned tool versions, downloads hash-locked build wheels when needed, builds wheel/sdist from copied source, and installs each into a clean venv outside the checkout. It proves imports resolve to the installation, checks dependencies, executes CSV processing/recovery, and verifies adapters plus JSON intake/run through the installed CLI. Receipts, hashes, file sizes and artifact modification times are checked. Use --wheelhouse with predownloaded locked wheels for an offline run.

Outputs include distribution_checks.json, command logs, wheel/sdist, a local unsigned CycloneDX inventory and provenance.json. These are not signed remote attestations. The base-install inventory excludes optional adapter dependencies that are not installed by the smoke test; deployment inventories must include the extras actually used.

For the complete user-facing bundle:

```bash
python -B tools/verify_current.py --output-dir /tmp/neuron-verification-new
python -B tools/build_delivery.py --candidate --verification-dir /tmp/neuron-verification-new --output-dir /tmp/neuron-package-new
```

The builder validates the source fingerprint, creates a complete SHA256SUMS.txt, extracts a fresh ZIP and reruns verification. It writes the ZIP, ZIP checksum, notebook, manifest, BUILD_STATUS.json and delivery_checks.json. Without --candidate, version-matching publication approval and successful local verification are required. Building does not publish. Historical verification snapshots and fresh current-run evidence are included. The original frozen runtime compatibility fixture remains available for regression tests.
