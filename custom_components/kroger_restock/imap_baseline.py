"""Baseline an IMAP folder: record existing messages as seen, unprocessed.

A folder such as a Gmail "Kroger" label can hold years of order emails. When
order tracking is linked to it, every message already there is recorded as
seen (by content key, below) without being processed, so only mail that
arrives afterwards is acted on.

Keys are content-based, matching ``OrderWatcher.email_keys``: the Message-ID
header, and a hash of sender, subject and date. HA's IMAP integration reports
SEARCH *sequence numbers* as ``uid``; those shift when mail leaves the folder,
so they are never used to decide whether a message was seen.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
import hashlib
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

HEADER_FIELDS = "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)])"
FETCH_CHUNK = 100


class BaselineError(Exception):
    """The baseline couldn't be taken (IMAP unreachable, bad folder, ...)."""


@dataclass(frozen=True, slots=True)
class Baseline:
    """Messages that were in the folder when order tracking was linked."""

    entry_id: str
    folder: str
    search: str
    keys: frozenset[str]
    count: int


def content_keys(
    sender: str | None,
    subject: str | None,
    date: datetime | str | None,
    message_id: str | None,
) -> list[str]:
    """Keys identifying one email regardless of folder or sequence number."""
    keys = []
    if message_id:
        keys.append(f"mid:{message_id.strip()}")
    raw = f"{sender}|{subject}|{date}"
    keys.append("sha:" + hashlib.sha1(raw.encode()).hexdigest()[:20])
    return keys


def header_keys(raw: bytes) -> list[str]:
    """Content keys from raw header bytes, parsed the way HA's IMAP does."""
    message = message_from_bytes(raw)
    sender = str(parseaddr(message["From"])[1])
    subject = str(make_header(decode_header(message["Subject"] or "")))
    date: datetime | None = None
    if (date_str := message["Date"]) is not None:
        try:
            date = parsedate_to_datetime(date_str)
        except TypeError, ValueError:
            date = None
    message_id = message["Message-ID"]
    return content_keys(sender, subject, date, str(message_id) if message_id else None)


async def async_connect(entry_data: Mapping[str, Any]) -> Any:
    """Open an IMAP connection with an IMAP config entry's own settings."""
    # Imported lazily: aioimaplib is only installed once HA's IMAP integration
    # has been set up, which it must be for an IMAP entry to exist.
    from homeassistant.components.imap.coordinator import (  # noqa: PLC0415
        connect_to_server,
    )

    return await connect_to_server(entry_data)


def _chunks(items: list[bytes], size: int) -> Iterable[list[bytes]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def async_take_baseline(entry_id: str, entry_data: Mapping[str, Any]) -> Baseline:
    """Read the headers of every message the IMAP entry's search matches."""
    folder = str(entry_data.get("folder", "INBOX"))
    search = str(entry_data.get("search", "UnSeen UnDeleted"))
    charset = str(entry_data.get("charset", "utf-8"))
    try:
        client = await async_connect(entry_data)
    except Exception as err:
        raise BaselineError(f"Couldn't connect to the mailbox: {err}") from err
    keys: set[str] = set()
    count = 0
    try:
        result, lines = await client.search(search, charset=charset)
        if result != "OK":
            raise BaselineError(f"Search {search!r} failed: {result}")
        numbers = lines[0].split() if len(lines) > 1 else []
        for chunk in _chunks(numbers, FETCH_CHUNK):
            response = await client.fetch(b",".join(chunk).decode(), HEADER_FIELDS)
            if response.result != "OK":
                raise BaselineError(f"Fetching headers failed: {response.result}")
            # aioimaplib returns each message's header block as a bytearray
            # literal between the "n FETCH (...)" and ")" lines.
            for part in response.lines:
                if isinstance(part, bytearray):
                    keys.update(header_keys(bytes(part)))
                    count += 1
    except BaselineError:
        raise
    except Exception as err:
        raise BaselineError(f"Reading the folder failed: {err}") from err
    finally:
        try:
            await client.logout()
        except Exception:
            _LOGGER.debug("IMAP logout after baseline failed", exc_info=True)
    return Baseline(entry_id, folder, search, frozenset(keys), count)
