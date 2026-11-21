"""Letter-size, two-column PDF rendering with fpdf2.

Sections flow down the left column, then the right column, then onto the
next page. The last page is balanced so a short list uses both columns
evenly. A section that breaks across columns repeats its heading with
"(cont.)".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fpdf import FPDF

from .layout import PrintDocument, to_plain

PAGE_FORMAT = "letter"
MARGIN = 13.0  # mm
GUTTER = 8.0  # mm between columns
COLUMNS = 2
BOX = 3.4  # checkbox size, mm
BOX_GAP = 2.4  # space between checkbox and text, mm
LINE_HEIGHT = 5.2
HEADING_HEIGHT = 6.5
HEADING_GAP = 3.0  # space above a section heading (not at a column top)
FOOTER_SPACE = 9.0  # reserved at the bottom of each page for the page footer
ENCODING = "latin-1"  # fpdf2 core fonts
FONT = "Helvetica"
ITEM_SIZE = 10
HEADING_SIZE = 11


def _t(text: str) -> str:
    return to_plain(text, ENCODING)


@dataclass(frozen=True, slots=True)
class _Block:
    """A section heading or an item line, already measured."""

    kind: str  # "heading" | "item" | "total"
    text: str
    height: float
    section: str = ""


@dataclass(frozen=True, slots=True)
class _Placed:
    """A block (or a continuation heading) at its final position."""

    block: _Block
    page: int
    column: int
    y: float


def _place(
    blocks: list[_Block],
    first_top: float,
    page_top: float,
    page_bottom: float,
    last_page_bottom: dict[int, float] | None = None,
) -> list[_Placed]:
    """Assign every block a page, column and y position."""
    overrides = last_page_bottom or {}
    placed: list[_Placed] = []
    page, column = 0, 0
    top = first_top
    y = top

    def bottom() -> float:
        return overrides.get(page, page_bottom)

    def advance() -> None:
        nonlocal page, column, top, y
        if column + 1 < COLUMNS:
            column += 1
        else:
            page, column, top = page + 1, 0, page_top
        y = top

    for index, block in enumerate(blocks):
        gap = HEADING_GAP if block.kind != "item" and y > top else 0.0
        need = gap + block.height
        if block.kind == "heading":
            # Keep a heading together with its first line.
            following = blocks[index + 1] if index + 1 < len(blocks) else None
            if following is not None and following.kind == "item":
                need += following.height
        if y + need > bottom() and y > top:
            advance()
            gap = 0.0
            if block.kind == "item":
                cont = _Block("heading", f"{block.section} (cont.)", HEADING_HEIGHT)
                placed.append(_Placed(cont, page, column, y))
                y += cont.height
        y += gap
        placed.append(_Placed(block, page, column, y))
        y += block.height
    return placed


def _balanced(
    blocks: list[_Block], first_top: float, page_top: float, page_bottom: float
) -> list[_Placed]:
    """Place blocks, then even out the columns on the last page."""
    placed = _place(blocks, first_top, page_top, page_bottom)
    if not placed:
        return placed
    last = placed[-1].page
    pages = last + 1
    start = first_top if last == 0 else page_top
    low, high = start, page_bottom
    best = placed
    # Binary search the lowest bottom for the last page that still fits.
    for _ in range(30):
        mid = (low + high) / 2
        trial = _place(blocks, first_top, page_top, page_bottom, {last: mid})
        if trial[-1].page + 1 == pages:
            best, high = trial, mid
        else:
            low = mid
        if high - low < 0.5:
            break
    return best


def _text_height(pdf: FPDF, width: float, text: str) -> float:
    lines = pdf.multi_cell(
        width, LINE_HEIGHT, text, align="L", dry_run=True, output="LINES"
    )
    return max(1, len(lines)) * LINE_HEIGHT


def render_pdf(
    doc: PrintDocument,
    creation_date: datetime | None = None,
    *,
    compress: bool = True,
) -> bytes:
    """Render ``doc`` as a two-column, letter-size PDF and return the bytes."""
    pdf = FPDF(orientation="portrait", unit="mm", format=PAGE_FORMAT)
    pdf.set_compression(compress)
    pdf.set_title(_t(f"{doc.title} - {doc.store}"))
    pdf.set_creator("Kroger Restock for Home Assistant")
    pdf.set_creation_date(creation_date or doc.printed_at)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(auto=False)
    footer_text = _t(doc.footer)

    def footer() -> None:
        pdf.set_y(-MARGIN)
        pdf.set_font(FONT, size=8)
        pdf.cell(0, 4, f"{footer_text} - page {pdf.page_no()}", align="C")

    pdf.footer = footer  # type: ignore[method-assign]
    pdf.add_page()

    # Full-width header on the first page
    pdf.set_font(FONT, style="B", size=17)
    pdf.cell(0, 8, _t(doc.title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT, size=10)
    pdf.cell(0, 5, _t(doc.store), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _t(doc.date_label), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    pdf.line(MARGIN, pdf.get_y(), pdf.w - MARGIN, pdf.get_y())
    first_top = pdf.get_y() + 1.0

    column_width = (pdf.w - 2 * MARGIN - GUTTER * (COLUMNS - 1)) / COLUMNS
    text_width = column_width - BOX - BOX_GAP
    page_bottom = pdf.h - MARGIN - FOOTER_SPACE

    # Measure
    pdf.set_font(FONT, size=ITEM_SIZE)
    blocks: list[_Block] = []
    for section in doc.sections:
        title = _t(section.title)
        blocks.append(_Block("heading", title, HEADING_HEIGHT))
        for line in section.lines:
            text = _t(line.text)
            blocks.append(
                _Block("item", text, _text_height(pdf, text_width, text), title)
            )
    blocks.append(_Block("total", footer_text, LINE_HEIGHT))

    # Place, then draw
    page = 0
    for placed in _balanced(blocks, first_top, MARGIN, page_bottom):
        while placed.page > page:
            pdf.add_page()
            page += 1
        x = MARGIN + placed.column * (column_width + GUTTER)
        block = placed.block
        if block.kind == "item":
            pdf.set_font(FONT, size=ITEM_SIZE)
            pdf.rect(x, placed.y + (LINE_HEIGHT - BOX) / 2, BOX, BOX)
            pdf.set_xy(x + BOX + BOX_GAP, placed.y)
            pdf.multi_cell(text_width, LINE_HEIGHT, block.text, align="L")
        else:
            size = HEADING_SIZE if block.kind == "heading" else ITEM_SIZE
            pdf.set_font(FONT, style="B", size=size)
            pdf.set_xy(x, placed.y)
            pdf.cell(column_width, block.height, block.text)
    return bytes(pdf.output())
