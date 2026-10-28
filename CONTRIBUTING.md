# Contributing to Neuron Flow

Bug reports, documentation improvements, tests and focused code changes are welcome.
Issues and pull requests may be written in English or Thai. The repository is public; issues and pull requests are visible publicly.
Use synthetic data and keep confidential material out of these channels.

Read the [README](README.md), [Code of Conduct](CODE_OF_CONDUCT.md) and
[governance policy](GOVERNANCE.md) before contributing. For usage questions, see
[SUPPORT.md](SUPPORT.md). Report suspected vulnerabilities through
[SECURITY.md](SECURITY.md), rather than an ordinary issue or pull request.

## Development setup

Python 3.10 or newer is required. The application and test suite use the Python
standard library; no third-party runtime packages are required. The package build
requirement is declared separately in `pyproject.toml`.

From a checkout, the following example creates a virtual environment on a POSIX
shell:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -B -m neuron_flow --help
```

Use a focused branch for each change. Discuss substantial changes to the CSV
contract, persistence, recovery behavior, dependencies or project scope in an
issue before implementing them when practical. A proposal does not require a
promise of acceptance or a response deadline.

## Validation

Run the checks relevant to your change and include their commands and results in
the pull request. The full existing regression checks, from the repository root,
are:

```bash
python -B tools/build_acceptance_fixture.py --check
NEURON_EVIDENCE_DIR="$(mktemp -d)" python -B -m unittest discover -s tests -t . -v
python -B .github/workflows/test_release_support.py -v
```

For a comprehensive verification report, choose a new directory outside the
checkout:

```bash
python -B tools/verify_current.py --output-dir "$(mktemp -d)"
```

This verifier includes the legacy runtime baseline, current tests, locked
reference fixture, report examples and release guards. Report failed, skipped and
unrun checks honestly. Documentation-only changes may describe link and content
review instead of running unrelated application tests.

Keep generated workspaces and fresh evidence separate from historical evidence.
Do not rewrite `verification/v0_2_0/` or change locked reference answers just to
make a check pass. A deliberate contract or reference change needs an explanation
and maintainer review. Local notebook tests do not establish actual Google Colab
acceptance.

## Additional development checks

Optional tooling is separate from the standard-library runtime. Follow the pinned-tool
installation and measured scope in [quality gates](docs/QUALITY_TH.md) and
[Python packaging](docs/PACKAGING_TH.md). Run `python -B tools/check_repository_docs.py`
when changing repository status claims. New evidence belongs in a fresh directory.
The [API guide](docs/PYTHON_API_TH.md) and [maintainer runbook](docs/MAINTAINER_RUNBOOK_TH.md)
cover custom Agents, backups and recovery; they do not promise a stable 0.2.x Python API.

## Pull requests

- Explain the problem and resulting behavior, with a minimal synthetic example
  when useful.
- Keep changes focused; add meaningful regression coverage for behavior changes.
- Explain compatibility effects on existing workspaces, CSV contracts and reports.
- Include relevant validation results and any known limitations or remaining
  failures. For performance claims, include workload, environment and measurement
  method.
- Remove credentials, personal data and real financial documents from examples,
  logs, screenshots and attachments. Public contributions must not contain
  sensitive data.

The maintainer makes acceptance and merge decisions under
[GOVERNANCE.md](GOVERNANCE.md). A merged pull request or successful build does not
authorize publication. Preserve the existing version-specific release approval
and manual publication workflow.

## Licensing

Contributions are accepted under the repository's existing [LICENSE](LICENSE).
Only submit material you have the right to contribute under those terms, and
preserve applicable copyright and license notices. No separate contributor
license agreement or copyright assignment is required by this project.
