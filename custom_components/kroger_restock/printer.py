"""Print the list to an ESC/POS receipt printer and/or a letter PDF."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    CONF_IPP_URL,
    CONF_PAPER_WIDTH,
    CONF_RECEIPT_HOST,
    CONF_RECEIPT_PORT,
    CONF_SAVE_PDF,
    DEFAULT_PAPER_WIDTH,
    DEFAULT_RECEIPT_PORT,
    DEFAULT_SAVE_PDF,
    DOMAIN,
    PDF_SUBDIR,
    PRINT_BOTH,
    PRINT_PDF,
    PRINT_RECEIPT,
)
from .coordinator import entry_option
from .printing.escpos import async_send_raw, columns_for_width, render_receipt
from .printing.ipp import IppError, async_print_job
from .printing.layout import PrintDocument, build_document
from .printing.pdf import render_pdf

if TYPE_CHECKING:
    from .coordinator import KrogerRestockCoordinator

_LOGGER = logging.getLogger(__name__)


def build(
    coordinator: KrogerRestockCoordinator, now: datetime | None = None
) -> PrintDocument:
    """Build the shared layout from the current list."""
    store = coordinator.location_name or coordinator.config_entry.title
    return build_document(coordinator.items, store, now or dt_util.now())


def pdf_dir(coordinator: KrogerRestockCoordinator) -> Path:
    """Folder PDFs are saved to (/media/kroger_restock by default)."""
    hass = coordinator.hass
    media = hass.config.media_dirs.get("local") or "/media"
    return Path(media) / PDF_SUBDIR


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def async_print(
    coordinator: KrogerRestockCoordinator, target: str
) -> dict[str, Any]:
    """Print to ``receipt``, ``pdf`` or ``both``. Returns a result per target."""
    entry = coordinator.config_entry
    hass = coordinator.hass
    doc = build(coordinator)
    result: dict[str, Any] = {"items": doc.item_count}
    errors: list[str] = []

    if target in (PRINT_RECEIPT, PRINT_BOTH):
        host = entry_option(entry, CONF_RECEIPT_HOST)
        if not host:
            if target == PRINT_RECEIPT:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="no_receipt_printer"
                )
            result["receipt"] = "not_configured"
        else:
            port = int(entry_option(entry, CONF_RECEIPT_PORT, DEFAULT_RECEIPT_PORT))
            width = int(entry_option(entry, CONF_PAPER_WIDTH, DEFAULT_PAPER_WIDTH))
            data = render_receipt(doc, columns_for_width(width))
            try:
                await async_send_raw(host, data, port)
            except (OSError, TimeoutError) as err:
                errors.append(f"receipt: {err}")
                result["receipt"] = "failed"
            else:
                result["receipt"] = "printed"

    if target in (PRINT_PDF, PRINT_BOTH):
        pdf = await hass.async_add_executor_job(render_pdf, doc)
        pdf_result: dict[str, Any] = {"bytes": len(pdf)}
        if entry_option(entry, CONF_SAVE_PDF, DEFAULT_SAVE_PDF):
            path = (
                pdf_dir(coordinator)
                / f"grocery_list_{doc.printed_at:%Y%m%d_%H%M%S}.pdf"
            )
            try:
                await hass.async_add_executor_job(_write, path, pdf)
            except OSError as err:
                errors.append(f"pdf save: {err}")
            else:
                pdf_result["path"] = str(path)
        if ipp_url := entry_option(entry, CONF_IPP_URL):
            try:
                await async_print_job(async_get_clientsession(hass), ipp_url, pdf)
            except IppError as err:
                errors.append(f"pdf print: {err}")
                pdf_result["printed"] = False
            else:
                pdf_result["printed"] = True
        else:
            pdf_result["printed"] = False
        result["pdf"] = pdf_result

    if errors:
        _LOGGER.warning("Printing problems: %s", "; ".join(errors))
        if errors and not any(
            v == "printed"
            or (isinstance(v, dict) and (v.get("printed") or v.get("path")))
            for v in (result.get("receipt"), result.get("pdf"))
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="print_failed",
                translation_placeholders={"error": "; ".join(errors)},
            )
        result["errors"] = errors
    return result
