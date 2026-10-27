"""A controller killed after report read-back and before batch receipt commit."""

from pathlib import Path
import sys
import time

from neuron_flow.batch import BatchRuntime
from tests.batch_fault_agents import purchase_source


def delivery_source():
    return purchase_source([("GOOD-FIRST", "รายงานก่อน receipt"),
                            ("GOOD-LAST", "เก็บงานที่สำเร็จแล้ว")])


def main():
    workspace = Path(sys.argv[1])
    with BatchRuntime(workspace) as runtime:
        runtime.submit(delivery_source(), "delivery-window")

        def stop_before_receipt(batch_id, receipt):
            # BatchTerminal has already atomically written and read back all
            # artifacts when BatchRuntime calls this persistence boundary.
            marker = workspace / "delivery.ready"
            temporary = marker.with_suffix(".tmp")
            temporary.write_text("ready", encoding="utf-8")
            temporary.replace(marker)
            while True:
                time.sleep(0.02)

        runtime._save_receipt = stop_before_receipt
        runtime.deliver("delivery-window")


if __name__ == "__main__":
    main()
