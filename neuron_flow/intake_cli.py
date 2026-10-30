"""CLI registration kept separate from the original runtime commands."""

from pathlib import Path

from .connectors import PROVIDERS, fetch_source, publish_sheets
from .document_input import FORMATS, read_source
from .intake import intake_status, review_document, run_document, stage_document


COMMANDS = {"intake", "intake-status", "intake-review", "intake-run", "connector-fetch", "sheets-publish", "adapters"}


def add_commands(commands):
    commands.add_parser("adapters", help="List supported formats, services and review requirements")
    for name in sorted(COMMANDS - {"adapters"}):
        command = commands.add_parser(name)
        if name == "sheets-publish":
            command.add_argument("source", type=Path, help="CSV report to write as literal cell strings")
            command.add_argument("spreadsheet_id")
            command.add_argument("--range", required=True, dest="cell_range")
            command.add_argument("--token-env", default="GOOGLE_ACCESS_TOKEN")
            continue
        command.add_argument("--workspace", default="batch_workspace")
        if name in {"intake", "connector-fetch"}:
            command.add_argument("--sheet")
            command.add_argument("--ocr", action="store_true")
            command.add_argument("--language", default="eng")
            if name == "intake":
                command.add_argument("source", type=Path)
            else:
                command.add_argument("provider", choices=PROVIDERS)
                command.add_argument("resource")
                command.add_argument("--filename", required=True, help="Original filename; Sheets snapshots must use .csv")
                command.add_argument("--token-env")
                command.add_argument("--range", dest="cell_range")
                command.add_argument("--bucket")
                command.add_argument("--version-id")
        else:
            command.add_argument("intake_id")
            if name == "intake-review":
                command.add_argument("reviewed_csv", type=Path)
                command.add_argument("--reviewer", required=True)
            if name == "intake-run":
                command.add_argument("--workers", type=int, default=3)
                command.add_argument("--submit-only", action="store_true")


def execute(args):
    if args.command == "adapters":
        return {"formats": list(FORMATS), "sources": ["local", *PROVIDERS],
                "destinations": ["local-reports", "google-sheets"],
                "receipt_policy": "PDF, text and images require reviewed CSV before batch processing",
                "cloud_accounts": "operator-supplied OAuth access tokens or AWS credential chain",
                "automatic_network_calls": False}
    if args.command == "sheets-publish":
        return publish_sheets(read_source(args.source), args.spreadsheet_id, args.cell_range, token_env=args.token_env)
    if args.command == "intake":
        return stage_document(args.workspace, read_source(args.source), args.source.name,
                              sheet=args.sheet, ocr=args.ocr, language=args.language)
    if args.command == "connector-fetch":
        if args.provider == "google-sheets" and Path(args.filename).suffix.lower() != ".csv":
            raise ValueError("SHEETS_FORMAT: use a .csv filename for the values snapshot")
        data, origin = fetch_source(args.provider, args.resource, token_env=args.token_env,
                                    cell_range=args.cell_range, bucket=args.bucket, version_id=args.version_id)
        return stage_document(args.workspace, data, args.filename, sheet=args.sheet,
                              ocr=args.ocr, language=args.language, origin=origin)
    if args.command == "intake-status":
        return intake_status(args.workspace, args.intake_id)
    if args.command == "intake-review":
        return review_document(args.workspace, args.intake_id, read_source(args.reviewed_csv), args.reviewer)
    return run_document(args.workspace, args.intake_id, workers=args.workers, submit_only=args.submit_only)
