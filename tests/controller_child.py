"""A controller intentionally killed by the integration test."""

from pathlib import Path
import sys

from neuron_flow import Runtime, AgentDefinition
from tests.fault_agents import validate_ok


def main():
    workspace = Path(sys.argv[1])
    definitions = [AgentDefinition(name, f"tests.fault_agents:{name}", validate_ok)
                   for name in ("ok", "hangs_once")]
    with Runtime(workspace, agents=definitions) as runtime:
        runtime.submit({"job_id": "crash_recovery", "steps": [
            {"id": "kept", "agent": "ok"},
            {"id": "recover", "agent": "hangs_once", "depends_on": ["kept"],
             "params": {"pid_file": str(workspace / "child.pid")}, "timeout_s": 30},
        ]})
        runtime.run("crash_recovery")


if __name__ == "__main__":
    main()
