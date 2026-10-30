# Python extension API

The public package exports Runtime, AgentDefinition, SpecError, PermanentAgentError and TransientAgentError. Python APIs remain experimental: pin a version/commit and run integration checks before upgrading. CLI/data contracts and workspace compatibility are documented in README.md and CURRENCIES.md.

## Batch and currency APIs

`BatchRuntime(workspace, *, max_workers=3, agents=None, timeout_s=5, legacy_thb=False)` is a context manager. submit(source_bytes, batch_id=None) persists source/identity; deliver(batch_id) processes or recovers and returns verified delivery results; status(batch_id) reads progress under the runtime lock. Non-THB intake selects the multicurrency contract. certified_totals is per currency; a multi-currency batch has no single certified_total. legacy_thb=True explicitly replays the original fixture contract.

```python
from pathlib import Path
from neuron_flow.batch import BatchRuntime


def main():
    with BatchRuntime("batch_workspace") as runtime:
        submitted = runtime.submit(Path("examples/purchases_international.csv").read_bytes(), "international")
        delivered = runtime.deliver(submitted["batch_id"])
        assert delivered["certified_totals"] == {
            "EUR": "25.50", "JPY": "1500", "KWD": "3.702", "USD": "21.50",
        }


if __name__ == "__main__":
    main()
```

validate_document(document, multicurrency=True) accepts a grouped CSV document. csv_workflow(document, job_id, timeout_s=5, multicurrency=True) binds the selected mode into its validation step. Set multicurrency=False for legacy replay. Persisted legacy work keeps its original contract. Invoice extract/calculate/verify Agents use version 2; old version-1 invoice jobs require the prior runtime or new workspaces/jobs.

## Runtime and AgentDefinition

Runtime(workspace, max_workers=3, agents=None) holds one workspace lock until close/context exit; capacity is 1-32. Providing agents replaces the registry. submit(spec) persists without execution; run(job_id) executes/recovers; status(job_id) inspects state; ingest(raw_input, job_id=None) chooses the built-in invoice workflow, not arbitrary plugin discovery. Inspect status, steps and receipt: a returned function call does not certify success.

AgentDefinition(name, entrypoint, validator, version="1") is frozen. entrypoint must be an importable module:function in a spawn worker. Validators run in the controller and must validate without mutating output, returning None/True or raising on failure. Increase the Agent version when behavior/contracts change and use a new ID for changed identity.

Messages contain work_id, job_id, step_id, attempt, input, params and declared dependencies. Messages/results must be finite JSON within the 1 MiB engine bound. TransientAgentError requests a bounded retry; other failures are not retried with identical input. Keep independent monetary verification separate from calculation.

## Runnable custom Agent example

Create sample_agent.py and run_example.py in the same directory, such as /tmp/neuron-api-example. Spawn requires importable functions and an if __name__ == "__main__" guard, not lambdas/local functions defined only in notebook cells.

```python
from neuron_flow import PermanentAgentError


def normalize_name(message):
    value = message["input"].get("name")
    if not isinstance(value, str) or not value.strip():
        raise PermanentAgentError("name must be nonempty text")
    return {"normalized": value.strip().upper()}


def validate_name(message, output):
    value = message["input"].get("name")
    if not isinstance(value, str) or output != {"normalized": value.strip().upper()}:
        raise ValueError("Name normalization result does not match input")
```

```python
import hashlib
from pathlib import Path
import sys

from neuron_flow import AgentDefinition, Runtime
from sample_agent import validate_name


def main():
    workspace = Path(sys.argv[1]).resolve()
    agents = [AgentDefinition("name", "sample_agent:normalize_name", validate_name, "1")]
    spec = {"job_id": "name_demo", "input": {"name": "  Ada  "},
            "steps": [{"id": "normalize", "agent": "name"}]}
    with Runtime(workspace, max_workers=1, agents=agents) as runtime:
        runtime.submit(spec)
        first = runtime.run("name_demo")
        assert first["status"] == "SUCCEEDED", first
        assert first["steps"]["normalize"]["output"] == {"normalized": "ADA"}
        artifact = Path(first["receipt"]["path"])
        original = artifact.read_bytes()
        modified = artifact.stat().st_mtime_ns
        assert hashlib.sha256(original).hexdigest() == first["receipt"]["sha256"]
    # Reopen with the same Agent identity and absolute workspace path.
    with Runtime(workspace, max_workers=1, agents=agents) as runtime:
        assert runtime.submit(spec)["created"] is False
        second = runtime.run("name_demo")
        assert second["status"] == "SUCCEEDED", second
        assert second["steps"]["normalize"]["attempts"] == 1
        assert artifact.read_bytes() == original
        assert artifact.stat().st_mtime_ns == modified
    print("custom Agent and idempotent recovery: passed")


if __name__ == "__main__":
    main()
```

```bash
PYTHONPATH="$PWD:/tmp/neuron-api-example" .venv/bin/python -B \
  /tmp/neuron-api-example/run_example.py /tmp/neuron-api-example/workspace
```

The historical Linux/Python 3.12.14 example verified a real execution, report hash and unchanged attempts/artifacts after reopening. This does not establish another platform or actual Colab acceptance.

Agents and validators are trusted Python code with the operator's process permissions. Workers provide failure isolation, not a security sandbox. External side effects require their own idempotency and reconciliation. For document staging and injected provider transports see INTEGRATIONS.md. Never put credentials or real financial documents in public examples or CI evidence.
