"""Pull a Kroger product ID out of a shared kroger.com product link.

Product pages look like ``https://www.kroger.com/p/<slug>/<13-digit id>``,
on kroger.com or any Kroger-family banner (ralphs.com, fredmeyer.com, ...).
The Kroger app shares text with the link embedded, so links are searched for
anywhere in the input.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from .order_email import KROGER_FAMILY_DOMAINS

_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_PRODUCT_PATH = re.compile(r"/p/(?:[^/]+/)*(\d{13})/?$")
PRODUCT_ID = re.compile(r"^\d{13}$")


@dataclass(frozen=True, slots=True)
class LinkResult:
    """What a shared link or text contained."""

    product_id: str | None  # the 13-digit Kroger product ID, if found
    found_url: bool  # any URL at all in the input


def _is_kroger_host(host: str) -> bool:
    host = host.lower().split(":")[0]
    return any(host == d or host.endswith(f".{d}") for d in KROGER_FAMILY_DOMAINS)


def product_id_from_text(text: str) -> LinkResult:
    """Find a Kroger product ID in a URL or in text that contains one.

    Query strings and fragments are ignored. Links to other sites, or to
    Kroger pages that aren't product pages, give ``product_id=None``.
    """
    urls = _URL.findall(text or "")
    for url in urls:
        parts = urlsplit(url.rstrip(".,);]"))
        if not _is_kroger_host(parts.hostname or ""):
            continue
        if match := _PRODUCT_PATH.search(parts.path):
            return LinkResult(match.group(1), True)
    return LinkResult(None, bool(urls))
