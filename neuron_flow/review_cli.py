"""CLI entry points for read-only report explanations and comparisons."""

from pathlib import Path

from .report_review import compare_reports, explain_report

COMMANDS = {"report-explain", "report-compare"}


def add_commands(commands):
    explain = commands.add_parser("report-explain", help="Explain saved report results with evidence paths")
    explain.add_argument("report_directory", type=Path)
    explain.add_argument("--document-id")
    compare = commands.add_parser("report-compare", help="Compare saved results for the same original CSV")
    compare.add_argument("reference_directory", type=Path)
    compare.add_argument("candidate_directory", type=Path)


def execute(args):
    if args.command == "report-explain":
        return explain_report(args.report_directory, document_id=args.document_id)
    return compare_reports(args.reference_directory, args.candidate_directory)
