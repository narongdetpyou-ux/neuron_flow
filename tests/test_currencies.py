"""Currency precision, independent verification and multi-currency delivery."""

import copy
import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from neuron_flow import Runtime, SpecError
from neuron_flow.agents import calculate_invoice, default_agents, expected_totals, normalize_invoice
from neuron_flow.batch import BatchConflict, BatchRuntime
from neuron_flow.csv_agents import compute_document, validate_document, verify_document
from neuron_flow.csv_input import FIELDS, read_csv_bytes
from neuron_flow.currencies import (
    CURRENCY_MINOR_UNITS, SUPPORTED_CURRENCIES, format_minor, minor_digits, parse_minor,
)
from neuron_flow.model import PermanentAgentError
from neuron_flow.reporting import BatchTerminal, ReportConflict


ZERO_DIGITS = {"JPY", "KRW", "VND", "CLP", "ISK"}
THREE_DIGITS = {"BHD", "KWD", "OMR", "JOD", "TND"}
TWO_DIGITS = set("THB USD EUR GBP CNY HKD SGD AUD CAD CHF NZD SEK NOK DKK INR IDR MYR "
                 "PHP TWD AED SAR QAR ILS TRY ZAR BRL MXN PLN CZK HUF RON BGN EGP PKR "
                 "BDT RUB".split())


def source_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(FIELDS)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def document(currency, price, total, quantity="3"):
    return read_csv_bytes(source_bytes([
        ["DOC", "A", "international purchase", quantity, price, total, currency],
    ]))["documents"][0]


def complete(grouped):
    validated = validate_document(grouped)
    return verify_document(validated, compute_document(validated))


class CurrencyArithmeticTests(unittest.TestCase):
    def test_supported_codes_and_iso_minor_unit_scales(self):
        expected = {**dict.fromkeys(ZERO_DIGITS, 0), **dict.fromkeys(TWO_DIGITS, 2),
                    **dict.fromkeys(THREE_DIGITS, 3)}
        self.assertEqual(dict(CURRENCY_MINOR_UNITS), expected)
        self.assertEqual(set(SUPPORTED_CURRENCIES), set(expected))
        for currency, digits in expected.items():
            with self.subTest(currency=currency):
                self.assertEqual(minor_digits(currency), digits)
                price = {0: "7", 2: "7.13", 3: "7.123"}[digits]
                total = {0: "21", 2: "21.39", 3: "21.369"}[digits]
                grouped = document(currency, price, total)
                before = copy.deepcopy(grouped)
                result = complete(grouped)
                self.assertEqual(result["document_status"], "VALID")
                self.assertEqual(result["computed_total"], total)
                self.assertEqual(result["difference"], {0: "0", 2: "0.00", 3: "0.000"}[digits])
                self.assertEqual(grouped, before)

    def test_integer_units_round_trip_zero_negative_and_large_values(self):
        for currency in ("USD", "JPY", "KWD"):
            digits = minor_digits(currency)
            for value in (0, 1, 10 ** 22 * 10 ** digits):
                with self.subTest(currency=currency, value=value):
                    rendered = format_minor(value, currency)
                    self.assertEqual(parse_minor(rendered, currency), value)
                    if value:
                        self.assertEqual(format_minor(-value, currency), "-" + rendered)

    def test_extra_precision_is_rejected_without_rounding_even_trailing_zeroes(self):
        for currency, price in (("USD", "1.001"), ("JPY", "1.0"), ("KWD", "1.0001")):
            for field in ("unit_price", "declared_total"):
                with self.subTest(currency=currency, field=field):
                    grouped = document(currency, "1", "3")
                    grouped["rows"][0]["fields"][field] = price
                    result = complete(grouped)
                    self.assertEqual(result["document_status"], "INVALID")
                    self.assertIsNone(result["computed_total"])
                    self.assertTrue(any(error["field"] == field for error in result["errors"]))
            with self.assertRaises(ValueError):
                parse_minor(price, currency)

    def test_minor_unit_mismatch_is_visible_with_currency_specific_precision(self):
        for currency, price, total, difference in (
                ("JPY", "7", "22", "-1"), ("KWD", "7.123", "21.368", "0.001"),
                ("USD", "7.13", "21.40", "-0.01")):
            with self.subTest(currency=currency):
                result = complete(document(currency, price, total))
                self.assertEqual(result["document_status"], "INVALID")
                self.assertEqual(result["difference"], difference)
                self.assertEqual(result["errors"][0]["reason_code"], "TOTAL_MISMATCH")

    def test_currency_and_decimal_input_are_strict(self):
        for currency in ("usd", " USD", "XXX", "BTC", "", "US$"):
            with self.subTest(currency=currency):
                with self.assertRaises(ValueError):
                    minor_digits(currency)
                result = complete(document(currency, "1", "3"))
                self.assertEqual(result["document_status"], "INVALID")
                self.assertIsNone(result["computed_total"])
        for price in ("-1", "+1", "1e2", "NaN", "Infinity", "１", "1,000", " 1", "1."):
            with self.subTest(price=price):
                with self.assertRaises(ValueError):
                    parse_minor(price, "USD")
        for value in (True, 1.0, "1", None):
            with self.subTest(minor_unit_type=type(value).__name__), self.assertRaises(ValueError):
                format_minor(value, "USD")

    def test_price_and_total_limits_apply_in_major_units_for_every_scale(self):
        for currency in ("USD", "JPY", "KWD"):
            with self.subTest(currency=currency):
                result = complete(document(currency, "1000000000000", "1000000000000000000",
                                           quantity="1000000"))
                self.assertEqual(result["document_status"], "VALID")
                too_large = {"USD": "1000000000000.01", "JPY": "1000000000001",
                             "KWD": "1000000000000.001"}[currency]
                result = complete(document(currency, too_large, "3"))
                self.assertEqual(result["document_status"], "INVALID")
                self.assertIn("PRICE_RANGE", {error["reason_code"] for error in result["errors"]})
                grouped = document(currency, "1", "10000000000000000000001")
                result = complete(grouped)
                self.assertIn("DECLARED_TOTAL_RANGE", {error["reason_code"] for error in result["errors"]})

    def test_mixed_currencies_within_one_document_are_invalid(self):
        grouped = read_csv_bytes(source_bytes([
            ["DOC", "A", "one", "1", "1", "2", "USD"],
            ["DOC", "B", "two", "1", "1", "2", "EUR"],
        ]))["documents"][0]
        result = complete(grouped)
        self.assertEqual(result["document_status"], "INVALID")
        self.assertIsNone(result["computed_total"])
        self.assertIn("CURRENCY_CONFLICT", {error["reason_code"] for error in result["errors"]})

    def test_decimal_result_is_checked_against_integer_minor_units(self):
        for currency, price, total, forged in (
                ("JPY", "7", "21", "21.00"), ("KWD", "7.123", "21.369", "21.370")):
            with self.subTest(currency=currency):
                validated = validate_document(document(currency, price, total))
                calculated = compute_document(validated)
                calculated["total"] = forged
                with self.assertRaises(PermanentAgentError):
                    verify_document(validated, calculated)

    def test_json_invoice_workflow_uses_same_scales(self):
        for currency, price, total in (("JPY", "12", "24"), ("KWD", "1.234", "2.468")):
            with self.subTest(currency=currency):
                invoice = normalize_invoice({"document_id": "json", "currency": currency,
                                             "items": [{"description": "example", "quantity": 2,
                                                        "unit_price": price}]})
                result = calculate_invoice({"params": {"source": "invoice"},
                                            "dependencies": {"invoice": invoice}})
                self.assertEqual(result, expected_totals(invoice))
                self.assertEqual(result["total"], total)

    def test_pending_json_invoice_from_old_agent_versions_is_not_reinterpreted(self):
        invoice = {"document_id": "old-yen", "currency": "JPY", "items": [
            {"description": "legacy invoice", "quantity": 2, "unit_price": "125"},
        ]}
        old_agents = [replace(agent, version="1") for agent in default_agents()]
        with tempfile.TemporaryDirectory() as workspace:
            with Runtime(workspace, agents=old_agents) as legacy:
                legacy.ingest(invoice, "old-yen")
                before = legacy.status("old-yen")
            with Runtime(workspace) as current:
                with self.assertRaisesRegex(SpecError, "Agent version changed"):
                    current.run("old-yen")
                self.assertEqual(current.status("old-yen"), before)
                self.assertEqual(current.soma.peak_workers, 0)
                current.ingest(invoice, "new-yen")
                result = current.run("new-yen")
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(result["steps"]["verify"]["output"]["total"], "250")


class MultiCurrencyBatchTests(unittest.TestCase):
    def test_foreign_v1_pending_and_completed_batches_retain_original_contract(self):
        source = source_bytes([["US", "A", "legacy dollars", "1", "2.00", "2.00", "USD"]])
        for completed in (False, True):
            with self.subTest(completed=completed), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory) / "workspace"
                with BatchRuntime(workspace, legacy_thb=True) as legacy:
                    legacy.submit(source, "legacy")
                    old_receipt = legacy.deliver("legacy") if completed else None
                with sqlite3.connect(workspace / "state.sqlite3") as database:
                    before = database.execute("SELECT identity,source,manifest FROM csv_batches WHERE id='legacy'").fetchone()
                reports_before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                                  for folder in ("reports", "batch_reports")
                                  for path in (workspace / folder).rglob("*") if path.is_file()}
                with BatchRuntime(workspace) as current:
                    old_payload = current.run("legacy")
                    delivered = current.deliver("legacy")
                    self.assertEqual(old_payload["contract_version"], "purchase-csv-v1")
                    self.assertEqual(old_payload["documents"][0]["document_status"], "INVALID")
                    self.assertNotIn("currency", old_payload["documents"][0])
                    self.assertIsNone(old_payload["documents"][0]["computed_total"])
                    self.assertEqual(old_payload["certified_total"], "0.00")
                    with self.assertRaises(BatchConflict):
                        current.submit(source, "legacy")
                    current.submit(source, "international")
                    new_payload = current.run("international")
                    self.assertEqual(new_payload["documents"][0]["document_status"], "VALID")
                    self.assertEqual(new_payload["currency"], "USD")
                    self.assertEqual(new_payload["certified_total"], "2.00")
                with sqlite3.connect(workspace / "state.sqlite3") as database:
                    after = database.execute("SELECT identity,source,manifest FROM csv_batches WHERE id='legacy'").fetchone()
                self.assertEqual(before, after)
                if completed:
                    self.assertEqual(delivered, old_receipt)
                    for path, state in reports_before.items():
                        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state)

    def test_mixed_batch_certifies_separate_totals_and_resume_preserves_artifacts(self):
        source = source_bytes([
            ["US", "A", "dollars", "3", "0.10", "0.30", "USD"],
            ["JP", "A", "yen", "2", "100", "200", "JPY"],
            ["KW", "A", "dinars", "2", "0.123", "0.246", "KWD"],
            ["BAD", "A", "invalid", "1", "1.00", "2.00", "EUR"],
        ])
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            with BatchRuntime(workspace) as runtime:
                runtime.submit(source, "international")
                receipt = runtime.deliver("international")
                payload = runtime.run("international")
            self.assertEqual(payload["counts"], {"documents": 4, "VALID": 3, "INVALID": 1, "ERROR": 0})
            self.assertIsNone(payload["currency"])
            self.assertIsNone(payload["certified_total"])
            self.assertEqual(payload["certified_totals"],
                             {"USD": "0.30", "JPY": "200", "KWD": "0.246", "EUR": "0.00"})
            self.assertEqual([item["currency"] for item in payload["documents"]], ["USD", "JPY", "KWD", "EUR"])
            self.assertEqual(payload["contract_version"], "purchase-csv-multicurrency-v1")
            summary_path = Path(receipt["receipt"]["artifacts"]["summary.csv"]["path"])
            with summary_path.open(newline="", encoding="utf-8") as stream:
                summary = list(csv.DictReader(stream))
            self.assertEqual([item["currency"] for item in summary], ["USD", "JPY", "KWD", "EUR"])
            self.assertEqual([item["computed_total"] for item in summary], ["0.30", "200", "0.246", "1.00"])
            paths = [Path(item["path"]) for item in receipt["receipt"]["artifacts"].values()]
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
            with BatchRuntime(workspace) as resumed:
                self.assertFalse(resumed.submit(source, "international")["created"])
                self.assertEqual(resumed.deliver("international"), receipt)
                self.assertEqual(resumed.run("international"), payload)
            self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths})
            self.assertEqual(json.loads((summary_path.parent / "details.json").read_bytes()), payload)

            mutations = [
                lambda changed: changed["certified_totals"].update(USD="1.30"),
                lambda changed: changed.update(certified_total="200.546", currency="USD"),
                lambda changed: changed["documents"][0].update(currency="EUR"),
                lambda changed: changed["documents"][1].update(computed_total="200.00"),
                lambda changed: changed["documents"][2].update(difference="0.00"),
            ]
            for index, mutate in enumerate(mutations):
                changed = copy.deepcopy(payload)
                mutate(changed)
                output = Path(directory) / f"tampered-{index}"
                with self.subTest(index=index), self.assertRaises(ReportConflict):
                    BatchTerminal(output).deliver(changed, source)
                self.assertFalse(output.exists())

    def test_single_foreign_currency_retains_convenient_total(self):
        source = source_bytes([["EU", "A", "euros", "2", "1.01", "2.02", "EUR"]])
        with tempfile.TemporaryDirectory() as workspace:
            with BatchRuntime(workspace) as runtime:
                runtime.submit(source, "euros")
                delivered = runtime.deliver("euros")
                payload = runtime.run("euros")
            self.assertEqual(payload["currency"], "EUR")
            self.assertEqual(payload["certified_total"], "2.02")
            self.assertEqual(payload["certified_totals"], {"EUR": "2.02"})
            self.assertEqual(delivered["currency"], "EUR")
            self.assertEqual(delivered["certified_total"], "2.02")

    def test_cli_mixed_currency_csv_and_resume_preserve_separate_totals(self):
        source = source_bytes([
            ["US", "A", "dollars", "3", "0.10", "0.30", "USD"],
            ["JP", "A", "yen", "2", "100", "200", "JPY"],
            ["KW", "A", "dinars", "2", "0.123", "0.246", "KWD"],
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            path.write_bytes(source)
            workspace = Path(directory) / "workspace"
            first = subprocess.run([sys.executable, "-B", "-m", "neuron_flow", "csv", str(path),
                                    "--batch-id", "cli-currencies", "--workspace", str(workspace)],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            result = json.loads(first.stdout)
            self.assertEqual(result["counts"], {"documents": 3, "VALID": 3, "INVALID": 0, "ERROR": 0})
            self.assertEqual(result["certified_totals"], {"USD": "0.30", "JPY": "200", "KWD": "0.246"})
            self.assertIsNone(result["certified_total"])
            self.assertIsNone(result["currency"])
            path.unlink()
            resumed = subprocess.run([sys.executable, "-B", "-m", "neuron_flow", "batch-resume",
                                      "cli-currencies", "--workspace", str(workspace)],
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(json.loads(resumed.stdout), result)

    def test_cli_json_invoice_uses_zero_digit_yen(self):
        invoice = {"document_id": "yen", "currency": "JPY", "items": [
            {"description": "notebook", "quantity": 2, "unit_price": "125"},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.json"
            path.write_text(json.dumps(invoice), encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", "-m", "neuron_flow", "invoice", str(path),
                                     "--workspace", str(Path(directory) / "workspace")],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "SUCCEEDED")
            output = receipt["steps"]["verify"]["output"]
            self.assertEqual(output["currency"], "JPY")
            self.assertEqual(output["total"], "250")


if __name__ == "__main__":
    unittest.main()
