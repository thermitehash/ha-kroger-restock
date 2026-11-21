"""ESC/POS receipt rendering and raw TCP (port 9100) printing.

Only generic commands are used, so no printer-specific driver is needed:
``ESC @`` (initialize), ``ESC E n`` (bold), ``ESC a n`` (align) and
``GS V`` (cut).
"""

from __future__ import annotations

import asyncio
import textwrap

from .layout import PrintDocument, to_plain

ESC = b"\x1b"
GS = b"\x1d"
INIT = ESC + b"@"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
ALIGN_LEFT = ESC + b"a\x00"
ALIGN_CENTER = ESC + b"a\x01"
# GS V 66 n: feed n lines, then partial cut (function B).
CUT = GS + b"V\x42\x03"
LF = b"\n"

ENCODING = "cp437"
CHECKBOX = "[ ] "
COLUMNS_58MM = 32
COLUMNS_80MM = 48
DEFAULT_PORT = 9100
SEND_TIMEOUT = 10.0


def columns_for_width(paper_mm: int) -> int:
    """58 mm paper fits 32 columns; 80 mm fits 48."""
    return COLUMNS_58MM if int(paper_mm) == 58 else COLUMNS_80MM


def _encode(text: str) -> bytes:
    return to_plain(text, ENCODING).encode(ENCODING, "replace")


def _wrap(text: str, width: int, first: str = "", rest: str = "") -> list[str]:
    return textwrap.wrap(
        to_plain(text, ENCODING),
        width=width,
        initial_indent=first,
        subsequent_indent=rest,
        break_long_words=True,
        break_on_hyphens=True,
    ) or [first.rstrip()]


def render_receipt(doc: PrintDocument, columns: int = COLUMNS_80MM) -> bytes:
    """Render ``doc`` as ESC/POS bytes for a ``columns``-wide printer."""
    out = bytearray(INIT)
    out += ALIGN_CENTER + BOLD_ON
    for line in _wrap(doc.title.upper(), columns):
        out += _encode(line) + LF
    out += BOLD_OFF
    for line in _wrap(doc.store, columns):
        out += _encode(line) + LF
    out += _encode(doc.date_label) + LF
    out += ALIGN_LEFT + _encode("=" * columns) + LF

    indent = " " * len(CHECKBOX)
    for section in doc.sections:
        out += LF + BOLD_ON
        for line in _wrap(section.title, columns):
            out += _encode(line) + LF
        out += BOLD_OFF
        for item in section.lines:
            for line in _wrap(item.text, columns, CHECKBOX, indent):
                out += _encode(line) + LF

    out += LF + _encode("=" * columns) + LF
    out += ALIGN_CENTER + _encode(doc.footer) + LF + ALIGN_LEFT
    out += CUT
    return bytes(out)


async def async_send_raw(host: str, data: bytes, port: int = DEFAULT_PORT) -> None:
    """Send raw bytes to a network printer (JetDirect / port 9100)."""
    async with asyncio.timeout(SEND_TIMEOUT):
        _reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(data)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
