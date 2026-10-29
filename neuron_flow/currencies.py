"""Supported ISO 4217 currencies and exact integer minor-unit arithmetic.

Amounts are expressed in one currency; this module never converts currencies or
rounds extra fractional digits. The table records accounting minor units, not
cash rounding conventions.
"""

import re


CURRENCY_MINOR_UNITS = {
    **dict.fromkeys((
        "THB", "USD", "EUR", "GBP", "CNY", "HKD", "SGD", "AUD", "CAD", "CHF",
        "NZD", "SEK", "NOK", "DKK", "INR", "IDR", "MYR", "PHP", "TWD", "AED",
        "SAR", "QAR", "ILS", "TRY", "ZAR", "BRL", "MXN", "PLN", "CZK", "HUF",
        "RON", "BGN", "EGP", "PKR", "BDT", "RUB",
    ), 2),
    **dict.fromkeys(("JPY", "KRW", "VND", "CLP", "ISK"), 0),
    **dict.fromkeys(("BHD", "KWD", "OMR", "JOD", "TND"), 3),
}
SUPPORTED_CURRENCIES = tuple(sorted(CURRENCY_MINOR_UNITS))


def minor_digits(currency):
    """Return the accounting scale for an exact, uppercase supported code."""
    if not isinstance(currency, str) or currency not in CURRENCY_MINOR_UNITS:
        raise ValueError("Unsupported currency code")
    return CURRENCY_MINOR_UNITS[currency]


def parse_minor(value, currency):
    """Parse unsigned ASCII decimal text without rounding or float arithmetic."""
    digits = minor_digits(currency)
    fraction_pattern = rf"(\.[0-9]{{1,{digits}}})?" if digits else ""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+" + fraction_pattern, value):
        raise ValueError(f"Amount must be unsigned decimal text with at most {digits} decimal places")
    whole, _, fraction = value.partition(".")
    return int(whole) * 10 ** digits + int(fraction.ljust(digits, "0") or "0")


def format_minor(value, currency):
    """Format a signed integer amount at its currency's canonical scale."""
    digits = minor_digits(currency)
    if type(value) is not int:
        raise ValueError("Minor-unit amount must be an integer")
    sign = "-" if value < 0 else ""
    value = abs(value)
    if not digits:
        return f"{sign}{value}"
    factor = 10 ** digits
    return f"{sign}{value // factor}.{value % factor:0{digits}d}"


def document_currency(document):
    """Return one supported currency only when every source row uses it."""
    rows = document.get("rows", [])
    if not rows:
        return None
    first = rows[0].get("fields", {}).get("currency")
    if not isinstance(first, str) or first not in CURRENCY_MINOR_UNITS:
        return None
    if any(row.get("fields", {}).get("currency") != first for row in rows):
        return None
    return first
