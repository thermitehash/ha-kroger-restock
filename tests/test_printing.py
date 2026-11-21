"""Printing tests: shared layout, ESC/POS and PDF golden files, IPP, end-to-end."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import struct
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.kroger_restock.const import DOMAIN, ItemSource, ItemStatus
from custom_components.kroger_restock.printing.escpos import (
    CUT,
    INIT,
    async_send_raw,
    columns_for_width,
    render_receipt,
)
from custom_components.kroger_restock.printing.ipp import (
    IppError,
    async_print_job,
    decode_response_header,
    encode_print_job,
    http_url,
)
from custom_components.kroger_restock.printing.layout import (
    SECTION_REVIEW,
    SECTION_WAITING,
    build_document,
)
from custom_components.kroger_restock.printing.pdf import render_pdf
from custom_components.kroger_restock.store import ListItem

from .helpers import FakeKrogerApi, make_product

GOLDEN = Path(__file__).parent / "golden"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"
PRINTED_AT = datetime(2026, 11, 21, 15, 5, tzinfo=dt_util.get_default_time_zone())
STORE = "Kroger Downtown — 1 Main St, Cincinnati, OH"


def item(name: str, status: ItemStatus, **kwargs: Any) -> ListItem:
    return ListItem(name=name, status=status, source=ItemSource.SCAN, **kwargs)


def sample_items() -> list[ListItem]:
    return [
        item(
            "Kroger 2% Reduced Fat Milk",
            ItemStatus.IN_CART,
            size="1 gal",
            aisle_number="12",
            aisle_description="DAIRY",
        ),
        item(
            "Coca-Cola Classic Soda",
            ItemStatus.IN_CART,
            size="12 pk / 12 fl oz",
            quantity=2,
            aisle_number="7",
            aisle_description="SODA",
        ),
        item(
            "Large Grade A Eggs",
            ItemStatus.HELD,
            size="12 ct",
            aisle_number="12",
            aisle_description="DAIRY",
        ),
        item(
            "Simple Truth Organic Extra Virgin Olive Oil Cold Pressed Imported From Italy",
            ItemStatus.IN_CART,
            size="16.9 fl oz",
            aisle_number="3",
            aisle_description="OILS & VINEGAR",
        ),
        item("Bananas", ItemStatus.IN_CART, size="1 lb", aisle_description="PRODUCE"),
        item("Birthday candles", ItemStatus.IN_CART),
        item(
            "Häagen-Dazs Vanilla Ice Cream",
            ItemStatus.WAITING,
            size="14 oz",
            aisle_number="20",
            aisle_description="FROZEN",
        ),
        item("Café Bustelo Espresso", ItemStatus.WAITING, size="10 oz"),
        item("milk", ItemStatus.NEEDS_REVIEW),
        item("012345678905", ItemStatus.UNMATCHED),
        item("Paper towels", ItemStatus.RECEIVED),
    ]


def doc():
    return build_document(sample_items(), STORE, PRINTED_AT)


def check_golden(name: str, data: bytes) -> None:
    path = GOLDEN / name
    if UPDATE or not path.exists():
        path.write_bytes(data)
    assert data == path.read_bytes(), f"{name} changed; rerun with UPDATE_GOLDEN=1"


def visible(data: bytes) -> bytes:
    """Make ESC/POS control sequences readable for the golden file."""
    for code, label in (
        (b"\x1b@", b"<INIT>"),
        (b"\x1bE\x01", b"<B>"),
        (b"\x1bE\x00", b"</B>"),
        (b"\x1ba\x00", b"<LEFT>"),
        (b"\x1ba\x01", b"<CENTER>"),
        (b"\x1dV\x42\x03", b"<CUT>"),
    ):
        data = data.replace(code, label)
    return data


# --- Layout ---------------------------------------------------------------


def test_layout_groups_and_sections() -> None:
    document = doc()
    titles = [s.title for s in document.sections]
    assert titles == [
        "Aisle 3 · Oils & Vinegar",
        "Aisle 7 · Soda",
        "Aisle 12 · Dairy",
        "Produce",
        "Other",
        SECTION_WAITING,
        SECTION_REVIEW,
    ]
    dairy = document.sections[2]
    assert [line.name for line in dairy.lines] == [
        "Kroger 2% Reduced Fat Milk",
        "Large Grade A Eggs",
    ]
    # Received items aren't printed.
    assert document.item_count == 10
    assert document.footer == "10 items"
    assert document.date_label == "Sat Nov 21, 2026 3:05 PM"
    assert (
        document.sections[1].lines[0].text
        == "Coca-Cola Classic Soda (12 pk / 12 fl oz) ×2"
    )


def test_layout_empty_list() -> None:
    document = build_document([], "Store", PRINTED_AT)
    assert document.sections == []
    assert document.footer == "0 items"


# --- ESC/POS --------------------------------------------------------------


@pytest.mark.parametrize(("width", "columns"), [(80, 48), (58, 32)])
def test_receipt_golden(width: int, columns: int) -> None:
    assert columns_for_width(width) == columns
    data = render_receipt(doc(), columns)
    assert data.startswith(INIT)
    assert data.endswith(CUT)
    text = visible(data)
    for line in text.split(b"\n"):
        plain = line
        for tag in (b"<INIT>", b"<B>", b"</B>", b"<LEFT>", b"<CENTER>", b"<CUT>"):
            plain = plain.replace(tag, b"")
        assert len(plain) <= columns, line
    check_golden(f"receipt_{width}mm.txt", text)


def test_receipt_bold_headers_and_encoding() -> None:
    data = render_receipt(doc(), 48)
    assert b"\x1bE\x01Aisle 12 - Dairy\n\x1bE\x00" in data
    assert b"[ ] Coca-Cola Classic Soda (12 pk / 12 fl oz) x2" in data
    # Accents survive in cp437.
    assert "Häagen-Dazs".encode("cp437") in data


class FakeWriter:
    def __init__(self, sink: bytearray) -> None:
        self.sink = sink
        self.closed = False

    def write(self, data: bytes) -> None:
        self.sink.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.fixture
def fake_printer():
    """Capture what would be sent to host:port over TCP."""
    sent: dict[tuple[str, int], bytearray] = {}

    async def open_connection(host: str, port: int):
        sink = sent.setdefault((host, port), bytearray())
        return object(), FakeWriter(sink)

    with patch(
        "custom_components.kroger_restock.printing.escpos.asyncio.open_connection",
        side_effect=open_connection,
    ):
        yield sent


async def test_send_raw_over_tcp(fake_printer) -> None:
    await async_send_raw("192.168.1.50", b"hello\x1dV\x42\x03", 9100)
    assert bytes(fake_printer[("192.168.1.50", 9100)]) == b"hello\x1dV\x42\x03"


async def test_send_raw_connection_refused() -> None:
    with (
        patch(
            "custom_components.kroger_restock.printing.escpos.asyncio.open_connection",
            side_effect=ConnectionRefusedError("refused"),
        ),
        pytest.raises(OSError),
    ):
        await async_send_raw("192.168.1.50", b"x", 9100)


# --- PDF ------------------------------------------------------------------


def test_pdf_golden() -> None:
    data = render_pdf(doc(), creation_date=PRINTED_AT, compress=False)
    assert data.startswith(b"%PDF-")
    assert b"/MediaBox [0 0 612 792]" in data  # US letter, in points
    for text in (
        b"Grocery list",
        b"Aisle 12 - Dairy",
        b"Waiting - check shelf",
        b"Needs review",
        b"10 items",
    ):
        assert text in data
    check_golden("grocery_list.pdf", data)


def test_pdf_many_items_paginates() -> None:
    items = [
        item(f"Item {n}", ItemStatus.IN_CART, aisle_number=str(n % 20))
        for n in range(150)
    ]
    data = render_pdf(build_document(items, "Store", PRINTED_AT), compress=False)
    assert data.count(b"/Type /Page\n") > 1


# --- IPP ------------------------------------------------------------------


def test_ipp_encoding() -> None:
    body = encode_print_job(
        "ipp://printer.local/ipp/print", b"%PDF-1.4 data", request_id=7
    )
    # version 1.1, Print-Job (0x0002), request-id 7
    assert body[:8] == bytes([1, 1, 0, 2, 0, 0, 0, 7])
    assert body[8] == 0x01  # operation-attributes-tag

    def attr(tag: int, name: bytes, value: bytes) -> bytes:
        return (
            bytes([tag])
            + struct.pack(">H", len(name))
            + name
            + struct.pack(">H", len(value))
            + value
        )

    expected = (
        attr(0x47, b"attributes-charset", b"utf-8")
        + attr(0x48, b"attributes-natural-language", b"en")
        + attr(0x45, b"printer-uri", b"ipp://printer.local/ipp/print")
        + attr(0x42, b"requesting-user-name", b"Home Assistant")
        + attr(0x42, b"job-name", b"Grocery list")
        + attr(0x49, b"document-format", b"application/pdf")
    )
    assert body[9 : 9 + len(expected)] == expected
    assert body[9 + len(expected)] == 0x03  # end-of-attributes-tag
    assert body.endswith(b"%PDF-1.4 data")


@pytest.mark.parametrize(
    ("uri", "url"),
    [
        ("ipp://printer.local/ipp/print", "http://printer.local:631/ipp/print"),
        ("ipps://printer.local/ipp/print", "https://printer.local:631/ipp/print"),
        ("ipp://10.0.0.5:8631/printers/x", "http://10.0.0.5:8631/printers/x"),
        ("http://10.0.0.5:631/ipp/print", "http://10.0.0.5:631/ipp/print"),
    ],
)
def test_ipp_http_url(uri: str, url: str) -> None:
    assert http_url(uri) == url


def test_ipp_bad_scheme() -> None:
    with pytest.raises(IppError):
        http_url("lpd://printer")


def test_ipp_response_header() -> None:
    resp = decode_response_header(bytes([1, 1, 0, 0, 0, 0, 0, 1]) + b"\x01\x03")
    assert resp.ok and resp.request_id == 1
    assert not decode_response_header(bytes([1, 1, 4, 0, 0, 0, 0, 1])).ok
    with pytest.raises(IppError):
        decode_response_header(b"\x01")


async def test_ipp_print_job(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.post(
        "http://printer.local:631/ipp/print",
        content=bytes([1, 1, 0, 0, 0, 0, 0, 1, 3]),
    )
    resp = await async_print_job(
        async_get_clientsession(hass), "ipp://printer.local/ipp/print", b"%PDF"
    )
    assert resp.ok
    _, _, body, headers = aioclient_mock.mock_calls[0]
    assert headers["Content-Type"] == "application/ipp"
    assert body.endswith(b"%PDF")


async def test_ipp_print_job_error_status(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    # 0x0400 client-error-bad-request
    aioclient_mock.post(
        "http://printer.local:631/ipp/print", content=bytes([1, 1, 4, 0, 0, 0, 0, 1, 3])
    )
    with pytest.raises(IppError):
        await async_print_job(
            async_get_clientsession(hass), "ipp://printer.local/ipp/print", b"%PDF"
        )


# --- End to end -----------------------------------------------------------


async def test_print_list_both(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    fake_printer,
    tmp_path: Path,
) -> None:
    hass.config.media_dirs = {"local": str(tmp_path)}
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            "receipt_host": "192.168.1.50",
            "receipt_port": 9100,
            "paper_width": "58",
            "ipp_url": "ipp://printer.local/ipp/print",
            "save_pdf": True,
        },
    )
    await hass.async_block_till_done()
    aioclient_mock.post(
        "http://printer.local:631/ipp/print", content=bytes([1, 1, 0, 0, 0, 0, 0, 1, 3])
    )
    fake_api.add(make_product("0004900002891", "Coca-Cola"))
    await hass.services.async_call(
        DOMAIN, "scan_upc", {"upc": "049000028911"}, blocking=True
    )

    result = await hass.services.async_call(
        DOMAIN, "print_list", {"target": "both"}, blocking=True, return_response=True
    )
    received = fake_printer[("192.168.1.50", 9100)]
    assert result["items"] == 1
    assert result["receipt"] == "printed"
    assert result["pdf"]["printed"] is True
    saved = Path(result["pdf"]["path"])
    assert saved.parent == tmp_path / "kroger_restock"
    assert saved.read_bytes().startswith(b"%PDF-")
    assert received.startswith(INIT) and b"[ ] Coca-Cola" in received
    assert aioclient_mock.call_count == 1


async def test_print_pdf_without_printer_only_saves(
    hass: HomeAssistant, setup_integration: MockConfigEntry, tmp_path: Path
) -> None:
    hass.config.media_dirs = {"local": str(tmp_path)}
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.kroger_test_store_print_pdf"},
        blocking=True,
    )
    files = list((tmp_path / "kroger_restock").glob("*.pdf"))
    assert len(files) == 1


async def test_print_receipt_not_configured(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "print_list", {"target": "receipt"}, blocking=True
        )


async def test_options_printing(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "printing"}
    )
    assert result["step_id"] == "printing"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "receipt_port": 9100,
            "paper_width": "80",
            "save_pdf": True,
            "ipp_url": "lpd://x",
        },
    )
    assert result["errors"] == {"ipp_url": "invalid_ipp_url"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "receipt_host": " 192.168.1.50 ",
            "receipt_port": 9100,
            "paper_width": "58",
            "ipp_url": "ipp://printer.local/ipp/print",
            "save_pdf": False,
        },
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    opts = setup_integration.options
    assert opts["receipt_host"] == "192.168.1.50"
    assert opts["paper_width"] == "58"
    assert opts["save_pdf"] is False
    assert opts["debounce_seconds"] == 3.0


async def test_print_both_partial_failure(
    hass: HomeAssistant, setup_integration: MockConfigEntry, tmp_path: Path
) -> None:
    hass.config.media_dirs = {"local": str(tmp_path)}
    hass.config_entries.async_update_entry(
        setup_integration,
        options={**setup_integration.options, "receipt_host": "192.168.1.50"},
    )
    await hass.async_block_till_done()
    with patch(
        "custom_components.kroger_restock.printing.escpos.asyncio.open_connection",
        side_effect=ConnectionRefusedError("refused"),
    ):
        result = await hass.services.async_call(
            DOMAIN,
            "print_list",
            {"target": "both"},
            blocking=True,
            return_response=True,
        )
    assert result["receipt"] == "failed"
    assert "path" in result["pdf"]
    assert result["errors"][0].startswith("receipt:")
