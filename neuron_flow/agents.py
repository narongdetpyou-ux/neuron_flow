"""Deterministic example agents. Money is represented as strings, not floats."""

from decimal import Decimal, InvalidOperation, localcontext
import re

from .model import PermanentAgentError, encode


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise PermanentAgentError(f"{label} must be non-empty text, at most 500 characters")
    return value.strip()


def normalize_invoice(document):
    if not isinstance(document, dict):
        raise PermanentAgentError("Invoice must be a JSON object")
    document_id = _text(document.get("document_id"), "document_id")
    currency = document.get("currency", "THB")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise PermanentAgentError("currency must be three uppercase letters")
    items = document.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 10000:
        raise PermanentAgentError("items must contain 1-10000 rows")
    normalized, seen = [], set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise PermanentAgentError(f"Row {index} must be an object")
        item_id = _text(item.get("item_id", str(index)), "item_id")
        if item_id in seen:
            raise PermanentAgentError(f"Duplicate item_id: {item_id}")
        seen.add(item_id)
        description = _text(item.get("description"), "description")
        quantity = item.get("quantity")
        if type(quantity) is int:
            quantity = str(quantity)
        if not isinstance(quantity, str) or not re.fullmatch(r"[0-9]{1,7}", quantity):
            raise PermanentAgentError(f"Row {index}: quantity must be a positive integer")
        quantity = int(quantity)
        if not 1 <= quantity <= 1_000_000:
            raise PermanentAgentError(f"Row {index}: quantity is out of range")
        price = item.get("unit_price")
        if type(price) is int:
            price = str(price)
        if not isinstance(price, str) or not re.fullmatch(r"[0-9]{1,13}(\.[0-9]{1,2})?", price):
            raise PermanentAgentError(f"Row {index}: unit_price must be a non-negative decimal string with at most 2 decimal places")
        try:
            value = Decimal(price)
            if value > Decimal("1000000000000"):
                raise PermanentAgentError(f"Row {index}: unit_price is out of range")
            price = format(value, ".2f")
        except InvalidOperation as exc:
            raise PermanentAgentError(f"Row {index}: invalid price") from exc
        normalized.append({"item_id": item_id, "description": description,
                           "quantity": quantity, "unit_price": price})
    return {"document_id": document_id, "currency": currency, "items": normalized}


def extract_invoice(message):
    return normalize_invoice(message["input"])


def _dependency(message, key):
    step_id = message["params"].get(key)
    if step_id not in message["dependencies"]:
        raise PermanentAgentError(f"params.{key} must name a declared dependency")
    return message["dependencies"][step_id]


def calculate_invoice(message):
    document = _dependency(message, "source")
    with localcontext() as context:
        context.prec = 50
        rows = [{"item_id": row["item_id"],
                 "amount": format(Decimal(row["unit_price"]) * row["quantity"], ".2f")}
                for row in document["items"]]
        total = sum((Decimal(row["amount"]) for row in rows), Decimal(0))
    return {"currency": document["currency"], "lines": rows, "total": format(total, ".2f")}


def expected_totals(document):
    """Independent integer-cents arithmetic for checking Decimal calculations."""
    rows, total_cents = [], 0
    for row in document["items"]:
        whole, fraction = row["unit_price"].split(".")
        amount = (int(whole) * 100 + int(fraction)) * row["quantity"]
        rows.append({"item_id": row["item_id"], "amount": f"{amount // 100}.{amount % 100:02d}"})
        total_cents += amount
    return {"currency": document["currency"], "lines": rows,
            "total": f"{total_cents // 100}.{total_cents % 100:02d}"}


def verify_invoice(message):
    document = _dependency(message, "source")
    calculated = _dependency(message, "calculation")
    if encode(calculated) != encode(expected_totals(document)):
        raise PermanentAgentError("Calculated result differs from source rows")
    return {"verified": True, "document_id": document["document_id"],
            "currency": calculated["currency"], "total": calculated["total"],
            "item_count": len(document["items"])}


def echo(message):
    return {"input": message["input"], "params": message["params"]}


def validate_extract(message, result):
    if encode(result) != encode(normalize_invoice(message["input"])):
        raise ValueError("Extracted data does not match the source")


def validate_calculation(message, result):
    if encode(result) != encode(expected_totals(_dependency(message, "source"))):
        raise ValueError("Incorrect line amounts or total")


def validate_verification(message, result):
    if encode(result) != encode(verify_invoice(message)):
        raise ValueError("Verification receipt does not match the checked result")


def validate_echo(message, result):
    if encode(result) != encode({"input": message["input"], "params": message["params"]}):
        raise ValueError("Echo result differs from its input")


def default_agents():
    from .engine import AgentDefinition
    return [
        AgentDefinition("extract_invoice", "neuron_flow.agents:extract_invoice", validate_extract),
        AgentDefinition("calculate_invoice", "neuron_flow.agents:calculate_invoice", validate_calculation),
        AgentDefinition("verify_invoice", "neuron_flow.agents:verify_invoice", validate_verification),
        AgentDefinition("echo", "neuron_flow.agents:echo", validate_echo),
    ]


def invoice_workflow(document, job_id="invoice_demo"):
    return {"job_id": job_id, "input": document, "steps": [
        {"id": "extract", "agent": "extract_invoice"},
        {"id": "calculate", "agent": "calculate_invoice", "depends_on": ["extract"],
         "params": {"source": "extract"}},
        {"id": "verify", "agent": "verify_invoice", "depends_on": ["extract", "calculate"],
         "params": {"source": "extract", "calculation": "calculate"}},
    ]}
