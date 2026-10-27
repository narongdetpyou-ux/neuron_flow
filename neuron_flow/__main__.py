"""CLI: python -m neuron_flow demo | run | resume | status | events."""

import argparse
import json
import multiprocessing
from pathlib import Path
import sqlite3
import sys

from . import Runtime
from .model import MAX_MESSAGE_BYTES, decode


DEMO_DOCUMENT = {"document_id": "INV-001", "currency": "THB", "items": [
    {"item_id": "A", "description": "สมุด", "quantity": 2, "unit_price": "125.50"},
    {"item_id": "B", "description": "ปากกา", "quantity": 3, "unit_price": "19.90"},
]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Neuron Flow supervised workflow prototype")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "invoice", "run", "resume", "status", "events"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", default="neuron_workspace")
        command.add_argument("--workers", type=int, default=3)
        if name == "run":
            command.add_argument("workflow", type=Path)
        if name == "invoice":
            command.add_argument("document", type=Path)
            command.add_argument("--job-id")
        if name in {"resume", "status", "events"}:
            command.add_argument("job_id")
        if name == "events":
            command.add_argument("--recipient", default="monitor")
            command.add_argument("--after", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        with Runtime(args.workspace, max_workers=args.workers) as runtime:
            if args.command == "demo":
                runtime.ingest(DEMO_DOCUMENT, "invoice_demo")
                result = runtime.run("invoice_demo")
            elif args.command == "run":
                with args.workflow.open("rb") as stream:
                    spec = decode(stream.read(MAX_MESSAGE_BYTES + 1))
                submitted = runtime.submit(spec)
                result = runtime.run(submitted["job_id"])
            elif args.command == "invoice":
                with args.document.open("rb") as stream:
                    document = decode(stream.read(MAX_MESSAGE_BYTES + 1))
                submitted = runtime.ingest(document, args.job_id)
                result = runtime.run(submitted["job_id"])
            elif args.command == "resume":
                result = runtime.run(args.job_id)
            elif args.command == "events":
                result = runtime.synapse.events_for(args.recipient, args.job_id, args.after)
            else:
                result = runtime.status(args.job_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if isinstance(result, dict) and result.get("status") in {"FAILED", "DELIVERY_FAILED"}:
            return 1
        return 0
    except (ValueError, KeyError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
