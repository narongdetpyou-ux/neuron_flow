"""A real batch controller intentionally killed while its worker is hung."""

from pathlib import Path
import sys

from neuron_flow.batch import BatchRuntime
from tests.batch_fault_agents import controller_source, fault_definitions


def main():
    workspace = Path(sys.argv[1])
    with BatchRuntime(workspace, agents=fault_definitions(), timeout_s=30) as runtime:
        runtime.submit(controller_source(workspace), "controller-recovery")
        runtime.run("controller-recovery")


if __name__ == "__main__":
    main()
