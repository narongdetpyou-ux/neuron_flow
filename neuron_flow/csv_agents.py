"""Versioned purchase-CSV document agents with independent money verification.

Validation success is an internal ``document_status=None`` until the Decimal
calculation passes its integer-satang check. INVALID data flows through all
steps as data; agent exceptions remain engine failures for the batch layer.
"""

from copy import deepcopy
import re

from .agents import calculate_invoice
from .engine import AgentDefinition
from .model import PermanentAgentError, encode


CONTRACT_VERSION = "purchase-csv-v1"
AGENT_VERSION = "0.2.0"
FINAL_FIELDS = ("document_id", "document_status", "source_rows", "computed_total",
                "declared_total", "difference", "errors")
QUANTITY_FORMAT = "unsigned-integer:1..7-digits"
PRICE_FORMAT = "unsigned-decimal:1..13-digits;scale<=2"
DECLARED_FORMAT = "unsigned-decimal:1..23-digits;scale<=2"
MAX_TOTAL_CENTS = 10 ** 24


def _money(value):
    sign = "-" if value < 0 else ""
    value = abs(value)
    return f"{sign}{value // 100}.{value % 100:02d}"


def _cents(value):
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0") or "0")


def _projection(envelope):
    return deepcopy({key: envelope[key] for key in FINAL_FIELDS})


def validate_document(document):
    """Validate a grouped ``csv_input`` document without mutating source data.

    Shape errors in the parser envelope indicate a programming/agent contract
    error. Data fields and parser-reported row errors produce INVALID results.
    Numeric strings remain strict ASCII and retain the 0.1.0 quantity/price
    bounds; identifier and description text is trimmed after length checks.
    """
    if not isinstance(document, dict) or not isinstance(document.get("rows"), list):
        raise PermanentAgentError("Expected a grouped CSV document with rows")
    rows = document["rows"]
    identifier = document.get("document_id", "")
    source_rows = []
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("source_row")) is not int
                or row["source_row"] < 2 or not isinstance(row.get("fields"), dict)
                or not isinstance(row.get("errors", []), list)):
            raise PermanentAgentError("Invalid grouped CSV row envelope")
        source_rows.append(row["source_row"])
    first_row = source_rows[0] if source_rows else None
    errors = []

    def error(row_number, field, code, expected, actual):
        errors.append({"row_number": row_number, "field": field,
                       "reason_code": code, "expected": expected, "actual": actual})

    def required(value, row_number, field):
        if not isinstance(value, str):
            error(row_number, field, "FIELD_TYPE", "string", value)
            return False
        if not value.strip():
            error(row_number, field, "REQUIRED", "non-empty", value)
            return False
        return True

    def text(value, row_number, field):
        if not required(value, row_number, field):
            return None
        if len(value) > 500:
            error(row_number, field, "TEXT_LENGTH", "text:length<=500", value)
            return None
        return value.strip()

    normalized_id = text(identifier, first_row, "document_id")
    result = {"document_id": normalized_id if normalized_id is not None else identifier,
              "document_status": None, "source_rows": source_rows,
              "computed_total": None, "declared_total": None, "difference": None,
              "errors": errors, "invoice": None, "declared_total_raw": None}
    if not 1 <= len(rows) <= 10000:
        error(first_row, "items", "ITEM_COUNT", "count:1..10000", len(rows))
        if rows:
            declared = rows[0]["fields"].get("declared_total", "")
            if (isinstance(declared, str)
                    and re.fullmatch(r"[0-9]{1,23}(\.[0-9]{1,2})?", declared)
                    and _cents(declared) <= MAX_TOTAL_CENTS):
                result["declared_total"] = _money(_cents(declared))
                result["declared_total_raw"] = declared
        result["document_status"] = "INVALID"
        return result

    items, seen = [], set()
    first_currency = None
    first_declared = None
    declared_conflict = False
    for index, row in enumerate(rows):
        row_number, fields = row["source_row"], row["fields"]
        errors.extend(deepcopy(row.get("errors", [])))
        row_id = text(fields.get("document_id", ""), row_number, "document_id")
        if row_id is not None and normalized_id is not None and row_id != normalized_id:
            error(row_number, "document_id", "DOCUMENT_ID_CONFLICT", normalized_id,
                  fields.get("document_id", ""))
        raw_item_id = fields.get("item_id", "")
        item_id = text(raw_item_id, row_number, "item_id")
        if item_id is not None:
            if item_id in seen:
                error(row_number, "item_id", "DUPLICATE_ITEM_ID", "unique-within-document", raw_item_id)
            seen.add(item_id)
        description = text(fields.get("description", ""), row_number, "description")

        raw_quantity = fields.get("quantity", "")
        quantity = None
        if required(raw_quantity, row_number, "quantity"):
            if not re.fullmatch(r"[0-9]{1,7}", raw_quantity):
                error(row_number, "quantity", "QUANTITY_FORMAT", QUANTITY_FORMAT, raw_quantity)
            elif not 1 <= int(raw_quantity) <= 1_000_000:
                error(row_number, "quantity", "QUANTITY_RANGE", "integer:1..1000000", raw_quantity)
            else:
                quantity = int(raw_quantity)

        raw_price = fields.get("unit_price", "")
        price = None
        if required(raw_price, row_number, "unit_price"):
            if not re.fullmatch(r"[0-9]{1,13}(\.[0-9]{1,2})?", raw_price):
                error(row_number, "unit_price", "PRICE_FORMAT", PRICE_FORMAT, raw_price)
            elif _cents(raw_price) > 100_000_000_000_000:
                error(row_number, "unit_price", "PRICE_RANGE", "decimal:0..1000000000000", raw_price)
            else:
                price = _money(_cents(raw_price))

        raw_declared = fields.get("declared_total", "")
        declared = None
        if required(raw_declared, row_number, "declared_total"):
            if not re.fullmatch(r"[0-9]{1,23}(\.[0-9]{1,2})?", raw_declared):
                error(row_number, "declared_total", "DECLARED_TOTAL_FORMAT", DECLARED_FORMAT, raw_declared)
            elif _cents(raw_declared) > MAX_TOTAL_CENTS:
                error(row_number, "declared_total", "DECLARED_TOTAL_RANGE",
                      "decimal:0..10000000000000000000000", raw_declared)
            else:
                declared = _cents(raw_declared)
        if index == 0:
            first_declared = declared
            result["declared_total"] = _money(declared) if declared is not None else None
            result["declared_total_raw"] = raw_declared if isinstance(raw_declared, str) else None
        elif declared is not None and first_declared is not None and declared != first_declared:
            error(row_number, "declared_total", "DECLARED_TOTAL_CONFLICT", _money(first_declared), raw_declared)
            declared_conflict = True

        raw_currency = fields.get("currency", "")
        if required(raw_currency, row_number, "currency"):
            if raw_currency != "THB":
                error(row_number, "currency", "CURRENCY_UNSUPPORTED", "THB", raw_currency)
            if index == 0:
                first_currency = raw_currency
            elif first_currency is not None and raw_currency != first_currency:
                error(row_number, "currency", "CURRENCY_CONFLICT", first_currency, raw_currency)
        items.append({"item_id": item_id, "description": description,
                      "quantity": quantity, "unit_price": price})
    if declared_conflict:
        result["declared_total"] = None
    if errors:
        result["document_status"] = "INVALID"
    else:
        result["invoice"] = {"document_id": normalized_id, "currency": "THB", "items": items}
    return result


def _integer_calculation(validated):
    """An independent satang oracle, never calling the Decimal calculator."""
    invoice = validated["invoice"]
    lines, total = [], 0
    for item in invoice["items"]:
        value = _cents(item["unit_price"]) * item["quantity"]
        lines.append({"item_id": item["item_id"], "amount": _money(value)})
        total += value
    return {"currency": invoice["currency"], "lines": lines, "total": _money(total)}


def compute_document(validated):
    """Use the existing Decimal calculation only for data that passed validation."""
    if validated["document_status"] == "INVALID":
        return _projection(validated)
    if validated["document_status"] is not None or validated["invoice"] is None:
        raise PermanentAgentError("Calculation requires validated input")
    return calculate_invoice({"params": {"source": "invoice"},
                              "dependencies": {"invoice": validated["invoice"]}})


def verify_document(validated, calculated):
    """Confirm Decimal output independently, then compare the declared total."""
    if validated["document_status"] == "INVALID":
        result = _projection(validated)
        if encode(calculated) != encode(result):
            raise PermanentAgentError("Invalid-document propagation differs from validation")
        return result
    if validated["document_status"] is not None or validated["invoice"] is None:
        raise PermanentAgentError("Verification requires validated input")
    reference = _integer_calculation(validated)
    if encode(calculated) != encode(reference):
        raise PermanentAgentError("Decimal calculation differs from independent integer satang")
    result = _projection(validated)
    difference = _cents(reference["total"]) - _cents(validated["declared_total"])
    result["computed_total"] = reference["total"]
    result["difference"] = _money(difference)
    result["document_status"] = "INVALID" if difference else "VALID"
    if difference:
        result["errors"].append({
            "row_number": result["source_rows"][0], "field": "declared_total",
            "reason_code": "TOTAL_MISMATCH", "expected": reference["total"],
            "actual": validated["declared_total_raw"],
        })
    return result


def _dependency(message, key):
    identifier = message.get("params", {}).get(key)
    dependencies = message.get("dependencies", {})
    if not isinstance(identifier, str) or identifier not in dependencies:
        raise PermanentAgentError(f"params.{key} must name a declared dependency")
    return dependencies[identifier]


def validate_csv(message):
    return validate_document(message["input"])


def calculate_csv(message):
    return compute_document(_dependency(message, "source"))


def verify_csv(message):
    return verify_document(_dependency(message, "source"), _dependency(message, "calculation"))


def validate_csv_output(message, output):
    if encode(output) != encode(validate_document(message["input"])):
        raise ValueError("CSV validation output differs from source fields")


def calculate_csv_output(message, output):
    source = _dependency(message, "source")
    expected = _projection(source) if source["document_status"] == "INVALID" else _integer_calculation(source)
    if encode(output) != encode(expected):
        raise ValueError("CSV Decimal output differs from independent integer satang")


def verify_csv_output(message, output):
    expected = verify_document(_dependency(message, "source"), _dependency(message, "calculation"))
    if encode(output) != encode(expected):
        raise ValueError("CSV verification output differs from independently checked source")


def csv_agent_definitions():
    return [
        AgentDefinition("csv_validate", "neuron_flow.csv_agents:validate_csv", validate_csv_output, AGENT_VERSION),
        AgentDefinition("csv_calculate", "neuron_flow.csv_agents:calculate_csv", calculate_csv_output, AGENT_VERSION),
        AgentDefinition("csv_verify", "neuron_flow.csv_agents:verify_csv", verify_csv_output, AGENT_VERSION),
    ]


def csv_workflow(document, job_id, timeout_s=5):
    return {"job_id": job_id, "input": document, "steps": [
        {"id": "validate", "agent": "csv_validate", "timeout_s": timeout_s, "max_attempts": 2},
        {"id": "calculate", "agent": "csv_calculate", "depends_on": ["validate"],
         "params": {"source": "validate"}, "timeout_s": timeout_s, "max_attempts": 2},
        {"id": "verify", "agent": "csv_verify", "depends_on": ["validate", "calculate"],
         "params": {"source": "validate", "calculation": "calculate"},
         "timeout_s": timeout_s, "max_attempts": 2},
    ]}
