"""Letter-size PDF rendering with fpdf2."""

from __future__ import annotations

from datetime import datetime

from fpdf import FPDF

from .layout import PrintDocument, to_plain

PAGE_FORMAT = "letter"
MARGIN = 15  # mm
BOX = 3.6  # checkbox size, mm
LINE_HEIGHT = 6.0
ENCODING = "latin-1"  # fpdf2 core fonts


def _t(text: str) -> str:
    return to_plain(text, ENCODING)


def render_pdf(
    doc: PrintDocument,
    creation_date: datetime | None = None,
    *,
    compress: bool = True,
) -> bytes:
    """Render ``doc`` as a letter-size PDF and return the bytes."""
    pdf = FPDF(orientation="portrait", unit="mm", format=PAGE_FORMAT)
    pdf.set_compression(compress)
    pdf.set_title(_t(f"{doc.title} - {doc.store}"))
    pdf.set_creator("Kroger Restock for Home Assistant")
    pdf.set_creation_date(creation_date or doc.printed_at)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(auto=True, margin=MARGIN + 6)
    footer_text = _t(doc.footer)

    def footer() -> None:
        pdf.set_y(-MARGIN)
        pdf.set_font("Helvetica", size=9)
        pdf.cell(0, 5, f"{footer_text} - page {pdf.page_no()}", align="C")

    pdf.footer = footer  # type: ignore[method-assign]
    pdf.add_page()

    pdf.set_font("Helvetica", style="B", size=18)
    pdf.cell(0, 9, _t(doc.title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 6, _t(doc.store), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _t(doc.date_label), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.line(MARGIN, pdf.get_y(), pdf.w - MARGIN, pdf.get_y())

    text_x = MARGIN + BOX + 3
    text_w = pdf.w - MARGIN - text_x
    for section in doc.sections:
        if pdf.will_page_break(LINE_HEIGHT * 3):
            pdf.add_page()
        pdf.ln(4)
        pdf.set_font("Helvetica", style="B", size=13)
        pdf.cell(0, 7, _t(section.title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        for line in section.lines:
            if pdf.will_page_break(LINE_HEIGHT):
                pdf.add_page()
            y = pdf.get_y()
            pdf.rect(MARGIN, y + (LINE_HEIGHT - BOX) / 2, BOX, BOX)
            pdf.set_x(text_x)
            pdf.multi_cell(
                text_w, LINE_HEIGHT, _t(line.text), new_x="LMARGIN", new_y="NEXT"
            )

    pdf.ln(4)
    pdf.set_font("Helvetica", style="B", size=11)
    pdf.cell(0, 6, footer_text, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
