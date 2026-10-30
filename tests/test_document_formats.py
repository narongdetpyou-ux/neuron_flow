"""Format contracts, actual parsing/OCR and bounded failure paths."""

from decimal import Decimal
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch
import zipfile

from neuron_flow import document_input as document
from neuron_flow.csv_input import FIELDS, read_csv_bytes
from tests.document_fixtures import CSV, PURCHASE, RECEIPT, pdf_bytes, receipt_image, workbook_bytes


HAS_PDF = importlib.util.find_spec("pypdf") is not None
HAS_EXCEL = all(importlib.util.find_spec(name) is not None for name in ("openpyxl", "defusedxml"))
HAS_IMAGE = importlib.util.find_spec("PIL") is not None
HAS_OCR = HAS_IMAGE and shutil.which("tesseract") is not None
HAS_SCAN = HAS_PDF and HAS_OCR and importlib.util.find_spec("pypdfium2") is not None


class StructuredInputTests(unittest.TestCase):
    def test_csv_bom_preserved_and_all_structured_adapters_share_contract(self):
        rows = [PURCHASE, {**PURCHASE, "document_id": "R-002", "unit_price": "0.001", "currency": "KWD", "declared_total": "0.002"}]
        for filename, data in (
            ("data.csv", b"\xef\xbb\xbf" + CSV),
            ("data.tsv", CSV.replace(b",", b"\t")),
            ("data.json", json.dumps(rows).encode()),
        ):
            with self.subTest(filename=filename):
                result = document.prepare_document(data, filename)
                parsed = read_csv_bytes(result["csv"])
                self.assertTrue(parsed["documents"])
                self.assertEqual(result["review_reasons"], [])
                self.assertEqual(result["source_record_mapping"][0]["normalized_csv_row"], 2)
                if filename.endswith("csv"):
                    self.assertEqual(result["csv"], data)
                if filename.endswith("json"):
                    self.assertEqual(parsed["documents"][1]["rows"][0]["fields"]["unit_price"], "0.001")
                    self.assertEqual(result["source_record_mapping"][1]["source_locator"], "/1")

    def test_json_decimal_numbers_and_invalid_values_not_silently_fixed(self):
        data = json.dumps([{**PURCHASE, "quantity": 2, "unit_price": 12.5}]).encode()
        fields = read_csv_bytes(document.json_to_csv(data))["documents"][0]["rows"][0]["fields"]
        self.assertEqual(fields["unit_price"], "12.5")
        self.assertEqual(fields["quantity"], "2")
        normalized = document.table_to_csv([FIELDS, ["", "A", None, 0, -1, 0, "USD"]])
        self.assertEqual(len(read_csv_bytes(normalized)["ungrouped_rows"]), 1)
        self.assertEqual(document._cell(Decimal("1E-3")), "0.001")

    def test_bad_json_shape_duplicate_keys_and_non_finite_are_rejected(self):
        for data, code in (
            (b"{", "JSON_SYNTAX"), (b"{}", "JSON_SHAPE"), (b"[]", "JSON_SHAPE"),
            (b"[null]", "JSON_SHAPE"), (b'[{"document_id":"A","document_id":"B"}]', "JSON_DUPLICATE_KEY"),
            (json.dumps([{**PURCHASE, "unit_price": float("nan")}]).encode(), "CELL_TYPE"),
            (json.dumps([{**PURCHASE, "quantity": True}]).encode(), "CELL_TYPE"),
            (json.dumps([{**PURCHASE, "description": {}}]).encode(), "CELL_TYPE"),
        ):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, code):
                document.prepare_document(data, "data.json")
        for value in (float("inf"), Decimal("NaN")):
            with self.assertRaisesRegex(ValueError, "CELL_TYPE"):
                document._cell(value)

    def test_limits_unknown_format_encoding_empty_table_and_tsv_syntax(self):
        for data, filename, code in (
            (b"", "old.xls", "FORMAT_UNSUPPORTED"), (b"\xff", "text.txt", "ENCODING"),
            (b'"unclosed', "bad.tsv", "TSV_SYNTAX"),
        ):
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, code):
                document.prepare_document(data, filename)
        with self.assertRaisesRegex(ValueError, "XLSX_SHEET"):
            document.prepare_document(CSV, "data.csv", sheet="foo")
        for data in ("text", b"x" * (document.MAX_SOURCE_BYTES + 1)):
            with self.assertRaisesRegex(ValueError, "SOURCE_LIMIT"):
                document.bounded_bytes(data)
        with self.assertRaisesRegex(ValueError, "EMPTY_TABLE"):
            document.table_to_csv([FIELDS])
        with patch.object(document, "MAX_ROWS", 1), self.assertRaisesRegex(ValueError, "ROW_LIMIT"):
            document.table_to_csv([FIELDS, list(PURCHASE.values()), list(PURCHASE.values())])
        with patch.object(document, "MAX_SOURCE_BYTES", 4), self.assertRaisesRegex(ValueError, "SOURCE_LIMIT"):
            document.table_to_csv([FIELDS])
        with patch.object(document.importlib, "import_module", side_effect=ImportError), self.assertRaisesRegex(ValueError, "DEPENDENCY_MISSING"):
            document.optional_module("missing", "pdf")

    def test_text_receipt_keeps_every_ambiguous_total_candidate_with_page_and_line(self):
        result = document.prepare_document((RECEIPT + "Subtotal USD 20.00\nยอดรวม 25.00\n").encode(), "receipt.txt")
        self.assertIsNone(result["csv"])
        self.assertEqual(result["pages"][0]["text"].splitlines()[0], "RECEIPT R-001")
        self.assertEqual(result["hints"][-1], {"page": 1, "line": 5, "text": "ยอดรวม 25.00"})
        self.assertIn("RECEIPT_REQUIRES_REVIEW", result["review_reasons"])
        empty = document.prepare_document(b"", "blank.txt")
        self.assertIn("EMPTY_PAGE_REQUIRES_OCR_OR_MANUAL_ENTRY", empty["review_reasons"])
        with patch.object(document, "MAX_TEXT", 1), self.assertRaisesRegex(ValueError, "TEXT_LIMIT"):
            document.prepare_document(RECEIPT.encode(), "receipt.txt")


@unittest.skipUnless(HAS_EXCEL, "install the excel extra")
class ExcelInputTests(unittest.TestCase):
    def test_actual_workbook_rows_and_explicit_sheet_selection(self):
        result = document.prepare_document(workbook_bytes(), "data.xlsx")
        self.assertEqual(result["csv"], CSV)
        self.assertEqual(result["source_record_mapping"][0]["source_locator"], "Purchases!row:2")
        multiple = workbook_bytes(extra_sheet=True)
        with self.assertRaisesRegex(ValueError, "XLSX_SHEET"):
            document.prepare_document(multiple, "data.xlsx")
        self.assertEqual(document.prepare_document(multiple, "data.xlsx", sheet="Purchases")["csv"], CSV)
        with self.assertRaisesRegex(ValueError, "XLSX_SHEET"):
            document.prepare_document(multiple, "data.xlsx", sheet="Missing")

    def test_formulas_macros_invalid_archives_and_expansion_limits(self):
        with self.assertRaisesRegex(ValueError, "XLSX_FORMULA"):
            document.prepare_document(workbook_bytes(formula=True), "data.xlsx")
        with self.assertRaisesRegex(ValueError, "XLSX_SYNTAX"):
            document.prepare_document(b"not zip", "data.xlsx")
        for member, code in (("xl/vbaProject.bin", "XLSX_MACROS"), ("invalid.xml", "XLSX_SYNTAX")):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as archive:
                archive.writestr(member, b"x")
            with self.assertRaisesRegex(ValueError, code):
                document.prepare_document(data.getvalue(), "data.xlsx")
        with patch.object(document, "MAX_EXPANDED_XLSX", 1), self.assertRaisesRegex(ValueError, "XLSX_LIMIT"):
            document.prepare_document(workbook_bytes(), "data.xlsx")
        with patch.object(document, "MAX_ROWS", 0), self.assertRaisesRegex(ValueError, "XLSX_LIMIT"):
            document.prepare_document(workbook_bytes(), "data.xlsx")


@unittest.skipUnless(HAS_PDF, "install the pdf extra")
class PdfInputTests(unittest.TestCase):
    def test_actual_text_pdf_and_empty_page_are_review_only(self):
        result = document.prepare_document(pdf_bytes(), "receipt.pdf", ocr=True)
        self.assertIn("TOTAL USD 25.00", result["pages"][0]["text"])
        self.assertEqual(result["pages"][0]["method"], "pdf_text")
        self.assertIsNone(result["csv"])
        result = document.prepare_document(pdf_bytes(""), "scan.pdf")
        self.assertIn("EMPTY_PAGE_REQUIRES_OCR_OR_MANUAL_ENTRY", result["review_reasons"])

    def test_encrypted_malformed_and_oversized_pdfs(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(100, 100)
        writer.encrypt("secret")
        data = io.BytesIO()
        writer.write(data)
        with self.assertRaisesRegex(ValueError, "PDF_ENCRYPTED"):
            document.prepare_document(data.getvalue(), "locked.pdf")
        with self.assertRaisesRegex(ValueError, "PDF_SYNTAX"):
            document.prepare_document(b"broken", "bad.pdf")
        with patch.object(document, "MAX_PAGES", 0), self.assertRaisesRegex(ValueError, "PAGE_LIMIT"):
            document.prepare_document(pdf_bytes(), "long.pdf")
        with patch.object(document, "MAX_EXPANDED_XLSX", 1), self.assertRaisesRegex(ValueError, "PDF_LIMIT"):
            document.prepare_document(pdf_bytes(), "big.pdf")


@unittest.skipUnless(HAS_IMAGE, "install the ocr extra")
class OcrInputTests(unittest.TestCase):
    @unittest.skipUnless(HAS_OCR, "install Tesseract English language data")
    def test_actual_ocr_on_png_jpeg_tiff_and_scanned_pdf(self):
        for kind, suffix in (("PNG", "png"), ("JPEG", "jpg"), ("TIFF", "tiff")):
            with self.subTest(kind=kind):
                result = document.prepare_document(receipt_image(kind), "receipt." + suffix, ocr=True)
                self.assertIn("25.00", result["pages"][0]["text"])
                self.assertIsNone(result["csv"])
        if HAS_SCAN:
            result = document.prepare_document(receipt_image("PDF"), "scan.pdf", ocr=True)
            self.assertEqual(result["pages"][0]["method"], "tesseract")
            self.assertIn("25.00", result["pages"][0]["text"])

    def test_images_require_ocr_and_bad_images_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, "OCR_REQUIRED"):
            document.prepare_document(b"image", "receipt.png")
        with self.assertRaisesRegex(ValueError, "IMAGE_SYNTAX"):
            document.prepare_document(b"not an image", "receipt.png", ocr=True)
        with patch.object(document, "MAX_PAGES", 0), self.assertRaisesRegex(ValueError, "PAGE_LIMIT"):
            document.prepare_document(receipt_image(), "receipt.png", ocr=True)
        with patch.object(document, "MAX_PIXELS", 1), self.assertRaisesRegex(ValueError, "IMAGE_LIMIT"):
            document.prepare_document(receipt_image(), "receipt.png", ocr=True)

    def test_ocr_language_missing_binary_timeout_provider_error_and_output_limit(self):
        from PIL import Image
        with Image.new("RGB", (10, 10)) as image:
            with self.assertRaisesRegex(ValueError, "OCR_LANGUAGE"):
                document._ocr_image(image, "eng --evil")
            for side_effect, code in ((FileNotFoundError, "OCR_MISSING"),
                                      (subprocess.TimeoutExpired("tesseract", 30), "OCR_TIMEOUT")):
                with patch.object(document.subprocess, "run", side_effect=side_effect), self.assertRaisesRegex(ValueError, code):
                    document._ocr_image(image, "eng")
            with patch.object(document.subprocess, "run", return_value=Mock(returncode=1)), self.assertRaisesRegex(ValueError, "OCR_FAILED"):
                document._ocr_image(image, "tha+eng")
            def large_output(command, **kwargs):
                Path(command[2] + ".txt").write_text("too much")
                return Mock(returncode=0)
            with patch.object(document.subprocess, "run", side_effect=large_output), patch.object(document, "MAX_TEXT", 1), self.assertRaisesRegex(ValueError, "TEXT_LIMIT"):
                document._ocr_image(image, "eng")

    @unittest.skipUnless(HAS_SCAN, "install PDF OCR extras")
    def test_render_pixel_limit_for_scanned_pdf(self):
        with patch.object(document, "MAX_PIXELS", 1), self.assertRaisesRegex(ValueError, "IMAGE_LIMIT"):
            document.prepare_document(receipt_image("PDF"), "scan.pdf", ocr=True)
