import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from neuron_flow import AgentDefinition, PermanentAgentError, Runtime
from neuron_flow.csv_agents import (
    calculate_csv, calculate_csv_output, compute_document, csv_agent_definitions,
    csv_workflow, validate_csv, validate_csv_output, validate_document,
    verify_csv, verify_csv_output, verify_document,
)
from neuron_flow.csv_input import FIELDS, parse_csv, read_csv_bytes


PROJECT = Path(__file__).resolve().parents[1]


def grouped(rows=None):
    rows = rows or [["DOC", "A", "Notebook", "2", "125.50", "310.70", "THB"],
                    ["DOC", "B", "Pen", "3", "19.90", "310.70", "THB"]]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(FIELDS)
    writer.writerows(rows)
    return read_csv_bytes(stream.getvalue().encode("utf-8"))["documents"][0]


def complete(document, *, multicurrency=True):
    validated = validate_document(document, multicurrency=multicurrency)
    return verify_document(validated, compute_document(validated))


def faulty_calculation(message):
    result = calculate_csv(message)
    result["total"] = "0.00"
    return result


def wrong_type_calculation(message):
    result = calculate_csv(message)
    result["total"] = float(result["total"])
    return result


def wrong_type_validation(message):
    result = validate_csv(message)
    result["invoice"]["items"][0]["quantity"] = float(result["invoice"]["items"][0]["quantity"])
    return result


def forged_verification(message):
    result = verify_csv(message)
    result["document_status"] = "VALID"
    return result


class CsvAgentTests(unittest.TestCase):
    def test_all_100_pure_results_match_locked_reference_and_leave_input_untouched(self):
        expected = json.loads((PROJECT / "acceptance/expected_results.json").read_text())
        documents = parse_csv(PROJECT / "acceptance/input.csv")["documents"]
        original = copy.deepcopy(documents)
        lock = json.loads((PROJECT / "acceptance/fixture_lock.json").read_text())
        for document, reference in zip(documents, expected["documents"]):
            with self.subTest(document_id=document["document_id"]):
                # The immutable fixture describes the original THB-only v1
                # contract (including USD as unsupported), not new intake.
                self.assertEqual(complete(document, multicurrency=False), reference)
        self.assertEqual(documents, original)
        for name, metadata in lock["files"].items():
            self.assertEqual(hashlib.sha256((PROJECT / "acceptance" / name).read_bytes()).hexdigest(),
                             metadata["sha256"])

    def test_validation_never_certifies_valid_before_calculation_and_verification(self):
        validated = validate_document(grouped())
        self.assertIsNone(validated["document_status"])
        self.assertIsNone(validated["computed_total"])
        self.assertIsNone(validated["difference"])
        self.assertEqual(validated["declared_total"], "310.70")
        result = verify_document(validated, compute_document(validated))
        self.assertEqual(result["document_status"], "VALID")
        self.assertEqual(result["computed_total"], "310.70")
        self.assertNotIn("invoice", result)
        self.assertNotIn("declared_total_raw", result)

    def test_invalid_data_does_not_call_any_money_calculation_or_raise_retry_error(self):
        document = grouped()
        document["rows"][1]["fields"]["item_id"] = "A"
        validated = validate_document(document)
        with patch("neuron_flow.csv_agents.calculate_invoice", side_effect=AssertionError("must skip Decimal")), \
                patch("neuron_flow.csv_agents._integer_calculation", side_effect=AssertionError("must skip money")):
            result = verify_document(validated, compute_document(validated))
        self.assertEqual(result["document_status"], "INVALID")
        self.assertIsNone(result["computed_total"])
        self.assertIsNone(result["difference"])
        self.assertEqual(result["errors"][0]["reason_code"], "DUPLICATE_ITEM_ID")

    def test_numeric_equivalent_declared_values_and_raw_mismatch_evidence(self):
        document = grouped()
        document["rows"][0]["fields"]["declared_total"] = "00310.7"
        self.assertEqual(complete(document)["document_status"], "VALID")
        for row in document["rows"]:
            row["fields"]["declared_total"] = "00310.71"
        result = complete(document)
        self.assertEqual(result["declared_total"], "310.71")
        self.assertEqual(result["difference"], "-0.01")
        self.assertEqual(result["errors"], [{"row_number": 2, "field": "declared_total",
                          "reason_code": "TOTAL_MISMATCH", "expected": "310.70", "actual": "00310.71"}])

    def test_price_quantity_and_zero_boundaries(self):
        document = grouped([["DOC", "A", "limit", "1000000", "1000000000000.00",
                             "1000000000000000000.00", "THB"],
                            ["DOC", "B", "free", "1", "0", "1000000000000000000.00", "THB"]])
        self.assertEqual(complete(document)["computed_total"], "1000000000000000000.00")
        cases = [("quantity", "0", "QUANTITY_RANGE"),
                 ("quantity", "1000001", "QUANTITY_RANGE"),
                 ("quantity", "10000000", "QUANTITY_FORMAT"),
                 ("quantity", "-1", "QUANTITY_FORMAT"),
                 ("quantity", "\u0e52", "QUANTITY_FORMAT"),
                 ("quantity", "1e2", "QUANTITY_FORMAT"),
                 ("quantity", " 2", "QUANTITY_FORMAT"),
                 ("unit_price", "1000000000000.01", "PRICE_RANGE"),
                 ("unit_price", "10000000000000", "PRICE_FORMAT"),
                 ("unit_price", "NaN", "PRICE_FORMAT"),
                 ("unit_price", "Infinity", "PRICE_FORMAT"),
                 ("unit_price", "-0.00", "PRICE_FORMAT"),
                 ("unit_price", "1.001", "PRICE_FORMAT"),
                 ("unit_price", ".10", "PRICE_FORMAT")]
        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(document)
                changed["rows"][0]["fields"][field] = value
                result = complete(changed)
                self.assertEqual(result["document_status"], "INVALID")
                self.assertEqual(result["errors"][0]["reason_code"], code)
                self.assertIsNone(result["computed_total"])

    def test_maximum_document_total_uses_23_integer_digits_without_rounding(self):
        row = grouped([["DOC", "A", "maximum", "1000000", "1000000000000.00",
                        "10000000000000000000000.00", "THB"]])["rows"][0]
        document = {"document_id": "DOC", "rows": []}
        for index in range(10000):
            item = copy.deepcopy(row)
            item["source_row"] = index + 2
            item["fields"]["item_id"] = str(index)
            document["rows"].append(item)
        result = complete(document)
        self.assertEqual(result["document_status"], "VALID")
        self.assertEqual(result["computed_total"], "10000000000000000000000.00")
        self.assertEqual(result["difference"], "0.00")

    def test_declared_total_format_range_and_conflicts(self):
        for value, code in [("NaN", "DECLARED_TOTAL_FORMAT"), ("-1", "DECLARED_TOTAL_FORMAT"),
                            ("1e2", "DECLARED_TOTAL_FORMAT"), ("1.001", "DECLARED_TOTAL_FORMAT"),
                            ("10000000000000000000000.01", "DECLARED_TOTAL_RANGE"),
                            ("100000000000000000000000", "DECLARED_TOTAL_FORMAT")]:
            with self.subTest(value=value):
                document = grouped()
                document["rows"][0]["fields"]["declared_total"] = value
                result = complete(document)
                self.assertEqual(result["errors"][0]["reason_code"], code)
                self.assertIsNone(result["declared_total"])
        document = grouped()
        document["rows"][1]["fields"]["declared_total"] = "310.71"
        result = complete(document)
        self.assertIsNone(result["declared_total"])
        self.assertEqual(result["errors"][0]["row_number"], 3)

    def test_missing_fields_wrong_types_and_parser_row_errors_remain_data_errors(self):
        document = grouped()
        del document["rows"][0]["fields"]["description"]
        document["rows"][1]["fields"]["quantity"] = True
        result = complete(document)
        self.assertEqual([error["reason_code"] for error in result["errors"]], ["REQUIRED", "FIELD_TYPE"])
        self.assertIs(result["errors"][1]["actual"], True)
        document = grouped([["DOC"]])
        original_error = copy.deepcopy(document["rows"][0]["errors"][0])
        result = complete(document)
        self.assertEqual(result["errors"][0], original_error)
        self.assertEqual(result["document_status"], "INVALID")
        self.assertEqual(document["rows"][0]["errors"], [original_error])

    def test_text_normalization_limits_and_document_size(self):
        document = grouped()
        document["rows"][0]["fields"]["description"] = "x" * 500
        document["rows"][0]["fields"]["item_id"] = " A "
        self.assertEqual(complete(document)["document_status"], "VALID")
        document["rows"][1]["fields"]["item_id"] = " A "
        self.assertEqual(complete(document)["errors"][0]["reason_code"], "DUPLICATE_ITEM_ID")
        document = grouped()
        document["rows"][0]["fields"]["description"] = "x" * 501
        self.assertEqual(complete(document)["errors"][0]["reason_code"], "TEXT_LENGTH")
        document = grouped()
        document["rows"] = []
        self.assertEqual(complete(document)["errors"][0]["reason_code"], "ITEM_COUNT")
        document["rows"] = [copy.deepcopy(grouped()["rows"][0])] * 10001
        oversized = complete(document)
        self.assertEqual(oversized["errors"][0]["reason_code"], "ITEM_COUNT")
        self.assertEqual(oversized["declared_total"], "310.70")

    def test_changed_calculation_and_numeric_type_do_not_pass_independent_check(self):
        source = validate_document(grouped())
        calculation = compute_document(source)
        message = {"params": {"source": "source"}, "dependencies": {"source": source}}
        with patch("neuron_flow.csv_agents.calculate_invoice", side_effect=AssertionError("independent check required")):
            calculate_csv_output(message, calculation)
        for field, value in [("total", "0.00"), ("total", 310.70), ("currency", "USD")]:
            changed = copy.deepcopy(calculation)
            changed[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                calculate_csv_output(message, changed)
            with self.assertRaises(PermanentAgentError):
                verify_document(source, changed)

    def test_validation_and_verification_callbacks_reject_forged_typed_outputs(self):
        document = grouped()
        source = validate_document(document)
        changed = copy.deepcopy(source)
        changed["invoice"]["items"][0]["quantity"] = 2.0
        self.assertEqual(changed, source)  # Python equality alone would accept it.
        with self.assertRaises(ValueError):
            validate_csv_output({"input": document}, changed)
        for row in document["rows"]:
            row["fields"]["declared_total"] = "310.71"
        source = validate_document(document)
        calculation = compute_document(source)
        output = verify_document(source, calculation)
        message = {"params": {"source": "source", "calculation": "calculation"},
                   "dependencies": {"source": source, "calculation": calculation}}
        output["document_status"] = "VALID"
        with self.assertRaises(ValueError):
            verify_csv_output(message, output)

    def test_invalid_propagation_cannot_be_changed_and_missing_dependency_is_contract_error(self):
        document = grouped()
        document["rows"][0]["fields"]["quantity"] = "0"
        source = validate_document(document)
        calculation = compute_document(source)
        calculation["document_status"] = "VALID"
        with self.assertRaises(PermanentAgentError):
            verify_document(source, calculation)
        for function in (calculate_csv, verify_csv):
            with self.subTest(function=function.__name__), self.assertRaises(PermanentAgentError):
                function({"params": {"source": "missing"}, "dependencies": {}})

    def test_all_100_documents_run_through_actual_worker_processes_and_match_golden(self):
        documents = parse_csv(PROJECT / "acceptance/input.csv")["documents"]
        expected = json.loads((PROJECT / "acceptance/expected_results.json").read_text())["documents"]
        statuses = {"VALID": 0, "INVALID": 0}
        with tempfile.TemporaryDirectory() as workspace:
            with Runtime(workspace, max_workers=3, agents=csv_agent_definitions()) as runtime:
                for document, reference in zip(documents, expected):
                    identifier = document["document_id"]
                    with self.subTest(document_id=identifier):
                        runtime.submit(csv_workflow(document, identifier, multicurrency=False))
                        result = runtime.run(identifier)
                        self.assertEqual(result["status"], "SUCCEEDED")
                        output = result["steps"]["verify"]["output"]
                        self.assertEqual(output, reference)
                        statuses[output["document_status"]] += 1
                        self.assertTrue(all(step["attempts"] == 1 for step in result["steps"].values()))
                        self.assertTrue(all(step["status"] == "SUCCEEDED" for step in result["steps"].values()))
        self.assertEqual(statuses, {"VALID": 80, "INVALID": 20})

    def test_runtime_rejects_wrong_amounts_and_types_without_retrying(self):
        cases = [("csv_calculate", "faulty_calculation", "calculate"),
                 ("csv_calculate", "wrong_type_calculation", "calculate"),
                 ("csv_validate", "wrong_type_validation", "validate"),
                 ("csv_verify", "forged_verification", "verify")]
        with tempfile.TemporaryDirectory() as workspace:
            for index, (agent_name, function, step_name) in enumerate(cases):
                with self.subTest(function=function):
                    agents = [AgentDefinition(agent.name, f"tests.test_csv_agents:{function}", agent.validator, agent.version)
                              if agent.name == agent_name else agent for agent in csv_agent_definitions()]
                    document = grouped()
                    if function == "forged_verification":
                        for row in document["rows"]:
                            row["fields"]["declared_total"] = "310.71"
                    identifier = f"bad_{index}"
                    with Runtime(Path(workspace) / identifier, agents=agents) as runtime:
                        runtime.submit(csv_workflow(document, identifier))
                        result = runtime.run(identifier)
                    self.assertEqual(result["status"], "FAILED")
                    self.assertEqual(result["steps"][step_name]["attempts"], 1)
                    self.assertEqual(result["steps"][step_name]["error"]["type"], "OutputValidationError")


if __name__ == "__main__":
    unittest.main()
