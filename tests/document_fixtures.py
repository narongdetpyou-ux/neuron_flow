"""Synthetic, reproducible receipt fixtures; no real financial data."""

import io

from neuron_flow.csv_input import FIELDS


PURCHASE = dict(zip(FIELDS, ("R-001", "A", "Notebook", "2", "12.50", "25.00", "USD")))
CSV = (",".join(FIELDS) + "\n" + ",".join(PURCHASE.values()) + "\n").encode()
RECEIPT = "RECEIPT R-001\n2 x Notebook 12.50\nTOTAL USD 25.00\n"


def pdf_bytes(text=RECEIPT):
    """A valid PDF with ASCII text, built independently from the PDF reader."""
    lines = text.splitlines()
    stream = b"BT /F1 16 Tf 50 740 Td 24 TL\n"
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream += f"({escaped}) Tj T*\n".encode("ascii")
    stream += b"ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = b"%PDF-1.4\n"
    offsets = []
    for index, content in enumerate(objects, 1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode() + content + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 6\n0000000000 65535 f \n"
    output += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    output += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return output


def receipt_image(kind="PNG"):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1200, 350), "white")
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 36)
    except OSError:
        font = ImageFont.load_default(size=36)
    ImageDraw.Draw(image).multiline_text((30, 30), RECEIPT, fill="black", font=font, spacing=12)
    output = io.BytesIO()
    image.save(output, format=kind)
    image.close()
    return output.getvalue()


def workbook_bytes(*, formula=False, extra_sheet=False):
    from openpyxl import Workbook
    book = Workbook()
    page = book.active
    page.title = "Purchases"
    page.append(list(FIELDS))
    page.append(list(PURCHASE.values()))
    if formula:
        page["E2"] = "=1+1"
    if extra_sheet:
        book.create_sheet("Other")
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()
