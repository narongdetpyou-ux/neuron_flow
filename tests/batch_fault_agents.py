"""Importable, genuinely failing batch agents used only by integration tests."""

from dataclasses import replace
import csv
import io
import os
from pathlib import Path
import time

from neuron_flow.csv_agents import calculate_csv, csv_agent_definitions
from neuron_flow.csv_input import FIELDS


FAULT_VERSION = "0.2.0-fault-test1"


def fault_definitions():
    return [replace(definition,
                    entrypoint="tests.batch_fault_agents:calculate_fault",
                    version=FAULT_VERSION)
            if definition.name == "csv_calculate" else definition
            for definition in csv_agent_definitions()]


def purchase_source(documents):
    """Each entry is (document_id, description), with one valid purchase row."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(FIELDS)
    for identifier, description in documents:
        writer.writerow([identifier, "I1", description, "2", "0.10", "0.20", "THB"])
    return stream.getvalue().encode("utf-8")


def controller_source(workspace):
    return purchase_source([
        ("GOOD-FIRST", "สำเร็จก่อนหยุด"),
        ("RECOVER", str(Path(workspace) / "interrupted-worker")),
        ("GOOD-LAST", "ต้องทำต่อหลังเปิดใหม่"),
    ])


def marker_path(base, attempt):
    return Path(f"{base}.attempt{attempt}.pid")


def _record_worker(message):
    base = message["input"]["rows"][0]["fields"]["description"]
    destination = marker_path(base, message["attempt"])
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(str(os.getpid()), encoding="utf-8")
    temporary.replace(destination)


def calculate_fault(message):
    identifier = message["input"]["document_id"]
    if identifier == "HANG" or (identifier == "RECOVER" and message["attempt"] == 1):
        _record_worker(message)
        while True:
            time.sleep(0.02)
    if identifier == "CRASH":
        _record_worker(message)
        os._exit(23)
    return calculate_csv(message)
