"""Bounded document adapters feeding the existing purchase CSV contract.

Structured imports preserve values, including invalid ones. Receipt text is
evidence for human review, never an automatically certified purchase document.
Optional packages are imported only by the adapter that needs them.
"""

import csv
from contextlib import closing
from decimal import Decimal
import importlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

from .csv_input import FIELDS, MAX_SOURCE_BYTES, read_csv_bytes


MAX_ROWS = 100_000
MAX_PAGES = 50
MAX_TEXT = 2_000_000
MAX_PIXELS = 25_000_000
MAX_EXPANDED_XLSX = 64 * 1024 * 1024
FORMATS = ("csv", "tsv", "json", "xlsx", "pdf", "txt", "png", "jpg", "jpeg", "tif", "tiff")


class DocumentInputError(ValueError):
    """An actionable document adapter failure (before any batch is created)."""


def optional_module(name, extra):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise DocumentInputError(f"DEPENDENCY_MISSING: install neuron-flow-prototype[{extra}]") from exc


def bounded_bytes(data):
    if not isinstance(data, bytes) or len(data) > MAX_SOURCE_BYTES:
        raise DocumentInputError(f"SOURCE_LIMIT: expected bytes, at most {MAX_SOURCE_BYTES}")
    return data


def read_source(path):
    with Path(path).open("rb") as stream:
        return bounded_bytes(stream.read(MAX_SOURCE_BYTES + 1))


def _text(data):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentInputError("ENCODING: source must be UTF-8") from exc


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise DocumentInputError("CELL_TYPE: only text and finite numbers are accepted")
    if isinstance(value, (float, Decimal)):
        if not (value.is_finite() if isinstance(value, Decimal) else math.isfinite(value)):
            raise DocumentInputError("CELL_TYPE: non-finite number")
        number = Decimal(str(value))
        parts = number.as_tuple()
        if len(parts.digits) + abs(parts.exponent) + 2 > MAX_SOURCE_BYTES:
            raise DocumentInputError("CELL_LIMIT: expanded decimal exceeds the source limit")
        # Never do arithmetic or round imported amounts. Explicit decimal
        # strings are preferable when the upstream format uses binary floats.
        return format(number, "f")
    return str(value)


def table_to_csv(rows):
    """Convert a rectangular table without guessing headers or dropping rows."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for index, row in enumerate(rows):
        if index > MAX_ROWS:
            raise DocumentInputError(f"ROW_LIMIT: at most {MAX_ROWS} data rows")
        writer.writerow([_cell(value) for value in row])
        if output.tell() > MAX_SOURCE_BYTES:
            raise DocumentInputError("SOURCE_LIMIT: normalized CSV is too large")
    data = bounded_bytes(output.getvalue().encode("utf-8"))
    parsed = read_csv_bytes(data)
    if not parsed["input_rows"]:
        raise DocumentInputError("EMPTY_TABLE: no data rows")
    return data


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise DocumentInputError(f"JSON_DUPLICATE_KEY: {key}")
        value[key] = item
    return value


def json_to_csv(data):
    try:
        rows = json.loads(_text(data), parse_float=Decimal, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise DocumentInputError(f"JSON_SYNTAX: line {exc.lineno}") from exc
    except ArithmeticError as exc:
        raise DocumentInputError("JSON_NUMBER: decimal exponent is outside the supported range") from exc
    if not isinstance(rows, list) or not rows:
        raise DocumentInputError("JSON_SHAPE: expected a non-empty list of purchase row objects")
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise DocumentInputError("JSON_SHAPE: each row must have exactly the seven CSV fields")
    return table_to_csv([FIELDS] + [[row[key] for key in FIELDS] for row in rows])


def _xlsx(data, sheet):
    # Preflight OOXML expansion and refuse executable/macro-bearing workbooks.
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 2000 or sum(member.file_size for member in members) > MAX_EXPANDED_XLSX:
                raise DocumentInputError("XLSX_LIMIT: expanded workbook is too large")
            if any("vbaproject" in member.filename.lower() for member in members):
                raise DocumentInputError("XLSX_MACROS: export a values-only .xlsx workbook")
    except zipfile.BadZipFile as exc:
        raise DocumentInputError("XLSX_SYNTAX: invalid workbook ZIP") from exc
    optional_module("defusedxml", "excel")
    excel = optional_module("openpyxl", "excel")
    try:
        book = excel.load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise DocumentInputError("XLSX_SYNTAX: workbook could not be opened") from exc
    try:
        if sheet is None and len(book.sheetnames) != 1:
            raise DocumentInputError("XLSX_SHEET: specify --sheet for a workbook with multiple sheets")
        name = sheet if sheet is not None else book.sheetnames[0]
        if name not in book.sheetnames:
            raise DocumentInputError("XLSX_SHEET: worksheet does not exist")
        page = book[name]
        if (page.max_row or 0) > MAX_ROWS + 1 or (page.max_column or 0) > len(FIELDS):
            raise DocumentInputError("XLSX_LIMIT: worksheet exceeds row/column limits")
        def rows():
            for row in page.iter_rows():
                if any(cell.data_type in {"f", "e"} for cell in row):
                    raise DocumentInputError("XLSX_FORMULA: export values; formulas/errors are not accepted")
                yield [cell.value for cell in row]
        return table_to_csv(rows()), name
    finally:
        book.close()


def _ocr_image(image, language):
    if image.width * image.height > MAX_PIXELS:
        raise DocumentInputError("IMAGE_LIMIT: too many pixels")
    if not re.fullmatch(r"[a-zA-Z0-9_]+(?:\+[a-zA-Z0-9_]+)*", language):
        raise DocumentInputError("OCR_LANGUAGE: use language codes such as eng or tha+eng")
    with tempfile.TemporaryDirectory(prefix="neuron-ocr-") as temporary:
        source = Path(temporary) / "page.png"
        destination = Path(temporary) / "text"
        image.convert("RGB").save(source)
        try:
            result = subprocess.run(
                ["tesseract", str(source), str(destination), "-l", language, "--psm", "6"],
                capture_output=True, timeout=30, check=False,
            )
        except FileNotFoundError as exc:
            raise DocumentInputError("OCR_MISSING: install Tesseract and the requested language data") from exc
        except subprocess.TimeoutExpired as exc:
            raise DocumentInputError("OCR_TIMEOUT: page exceeded 30 seconds") from exc
        if result.returncode:
            raise DocumentInputError("OCR_FAILED: check the image and installed Tesseract language data")
        with destination.with_suffix(".txt").open("rb") as stream:
            text = stream.read(MAX_TEXT + 1)
        if len(text) > MAX_TEXT:
            raise DocumentInputError("TEXT_LIMIT: OCR output is too large")
        return text.decode("utf-8")


def _image_pages(data, ocr, language):
    if not ocr:
        raise DocumentInputError("OCR_REQUIRED: image receipts require --ocr")
    images = optional_module("PIL.Image", "ocr")
    try:
        with images.open(io.BytesIO(data)) as image:
            frames = getattr(image, "n_frames", 1)
            if frames > MAX_PAGES:
                raise DocumentInputError("PAGE_LIMIT: too many image frames")
            pages = []
            for index in range(frames):
                image.seek(index)
                pages.append({"page": index + 1, "method": "tesseract", "text": _ocr_image(image, language)})
            return pages
    except DocumentInputError:
        raise
    except Exception as exc:
        raise DocumentInputError("IMAGE_SYNTAX: image could not be read") from exc


def _pdf_pages(data, ocr, language):
    pdf = optional_module("pypdf", "pdf")
    try:
        reader = pdf.PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise DocumentInputError("PDF_ENCRYPTED: supply an unlocked PDF")
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            raise DocumentInputError(f"PAGE_LIMIT: PDF must have 1-{MAX_PAGES} pages")
        pages = []
        for index, page in enumerate(reader.pages):
            content = page.get_contents()
            if content is not None and len(content.get_data()) > MAX_EXPANDED_XLSX:
                raise DocumentInputError("PDF_LIMIT: decoded page content is too large")
            text = page.extract_text() or ""
            pages.append({"page": index + 1, "method": "pdf_text", "text": text})
        if ocr:
            _pdf_ocr(data, pages, language)
        return pages
    except DocumentInputError:
        raise
    except Exception as exc:
        raise DocumentInputError("PDF_SYNTAX: PDF could not be read") from exc


def _pdf_ocr(data, pages, language):
    empty = [page for page in pages if not page["text"].strip()]
    if not empty:
        return
    renderer = optional_module("pypdfium2", "ocr")
    with renderer.PdfDocument(data) as document:
        for entry in empty:
            with closing(document[entry["page"] - 1]) as page:
                width, height = page.get_size()
                if width <= 0 or height <= 0 or width * height * 4 > MAX_PIXELS:
                    raise DocumentInputError("IMAGE_LIMIT: rendered PDF page is too large")
                with closing(page.render(scale=2)) as bitmap:
                    with bitmap.to_pil() as image:
                        entry.update(text=_ocr_image(image, language), method="tesseract")


def _receipt_hints(pages):
    # Preserve every candidate and location; ambiguous totals/currency symbols
    # are not resolved by a heuristic. No inferred line items or tax arithmetic.
    hints = []
    for page in pages:
        for number, line in enumerate(page["text"].splitlines(), 1):
            if re.search(r"\b(total|amount due|receipt|invoice|currency)\b|ยอดรวม|สุทธิ|ใบเสร็จ|สกุลเงิน", line, re.I):
                hints.append({"page": page["page"], "line": number, "text": line[:1000]})
    return hints


def prepare_document(data, filename, *, sheet=None, ocr=False, language="eng"):
    """Return normalized CSV or a receipt review draft with page evidence."""
    bounded_bytes(data)
    kind = Path(filename).suffix.lower().lstrip(".")
    if kind not in FORMATS:
        raise DocumentInputError("FORMAT_UNSUPPORTED: " + ", ".join(FORMATS))
    if sheet is not None and kind != "xlsx":
        raise DocumentInputError("XLSX_SHEET: --sheet only applies to .xlsx")
    result = {"format": kind, "csv": None, "pages": [], "review_reasons": [], "sheet": None}
    if kind == "csv":
        read_csv_bytes(data)
        result["csv"] = data
    elif kind == "tsv":
        try:
            result["csv"] = table_to_csv(csv.reader(io.StringIO(_text(data), newline=""), delimiter="\t", strict=True))
        except csv.Error as exc:
            raise DocumentInputError("TSV_SYNTAX: malformed tab-separated input") from exc
    elif kind == "json":
        result["csv"] = json_to_csv(data)
    elif kind == "xlsx":
        result["csv"], result["sheet"] = _xlsx(data, sheet)
    else:
        if kind == "txt":
            result["pages"] = [{"page": 1, "method": "text", "text": _text(data)}]
        elif kind == "pdf":
            result["pages"] = _pdf_pages(data, ocr, language)
        else:
            result["pages"] = _image_pages(data, ocr, language)
        if sum(len(page["text"]) for page in result["pages"]) > MAX_TEXT:
            raise DocumentInputError("TEXT_LIMIT: extracted text is too large")
        result["review_reasons"] = ["RECEIPT_REQUIRES_REVIEW"]
        if any(not page["text"].strip() for page in result["pages"]):
            result["review_reasons"].append("EMPTY_PAGE_REQUIRES_OCR_OR_MANUAL_ENTRY")
        result["hints"] = _receipt_hints(result["pages"])
    if result["csv"] is not None:
        parsed = read_csv_bytes(result["csv"])
        records = sorted([row for doc in parsed["documents"] for row in doc["rows"]]
                         + parsed["ungrouped_rows"], key=lambda row: row["source_row"])
        result["source_record_mapping"] = [
            {"normalized_csv_row": row["source_row"], "source_record": index + 1,
             "source_locator": (f"/{index}" if kind == "json" else
                                f"{result['sheet']}!row:{index + 2}" if kind == "xlsx" else
                                f"data-record:{index + 1}")}
            for index, row in enumerate(records)
        ]
    return result
