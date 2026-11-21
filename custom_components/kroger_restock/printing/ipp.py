"""Minimal IPP/1.1 Print-Job client (RFC 8010 encoding, RFC 8011 semantics).

Only what is needed to send one PDF: a Print-Job request with the required
operation attributes, followed by the document data.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from urllib.parse import urlsplit, urlunsplit

from aiohttp import ClientError, ClientSession, ClientTimeout

IPP_VERSION = (1, 1)
OP_PRINT_JOB = 0x0002

# Delimiter tags (RFC 8010 §3.5.1)
TAG_OPERATION_ATTRIBUTES = 0x01
TAG_JOB_ATTRIBUTES = 0x02
TAG_END_OF_ATTRIBUTES = 0x03

# Value tags (RFC 8010 §3.5.2)
TAG_INTEGER = 0x21
TAG_BOOLEAN = 0x22
TAG_ENUM = 0x23
TAG_TEXT_WITHOUT_LANGUAGE = 0x41
TAG_NAME_WITHOUT_LANGUAGE = 0x42
TAG_KEYWORD = 0x44
TAG_URI = 0x45
TAG_CHARSET = 0x47
TAG_NATURAL_LANGUAGE = 0x48
TAG_MIME_MEDIA_TYPE = 0x49

CONTENT_TYPE = "application/ipp"
DEFAULT_PORT = 631
REQUEST_TIMEOUT = ClientTimeout(total=30)


class IppError(Exception):
    """IPP request failed."""


@dataclass(frozen=True, slots=True)
class IppResponse:
    """Parsed response header."""

    version: tuple[int, int]
    status_code: int
    request_id: int

    @property
    def ok(self) -> bool:
        """successful-ok* status codes are 0x0000-0x00FF (RFC 8011 §B.1.2)."""
        return self.status_code < 0x0100


def _attribute(tag: int, name: str, value: bytes) -> bytes:
    name_bytes = name.encode("utf-8")
    return (
        struct.pack(">BH", tag, len(name_bytes))
        + name_bytes
        + struct.pack(">H", len(value))
        + value
    )


def encode_print_job(
    printer_uri: str,
    document: bytes,
    *,
    request_id: int = 1,
    job_name: str = "Grocery list",
    user_name: str = "Home Assistant",
    document_format: str = "application/pdf",
) -> bytes:
    """Encode a Print-Job request.

    attributes-charset and attributes-natural-language must come first,
    in that order, followed by the target (printer-uri) (RFC 8011 §4.1.4).
    """
    header = struct.pack(">BBHI", *IPP_VERSION, OP_PRINT_JOB, request_id)
    attrs = bytes([TAG_OPERATION_ATTRIBUTES])
    attrs += _attribute(TAG_CHARSET, "attributes-charset", b"utf-8")
    attrs += _attribute(TAG_NATURAL_LANGUAGE, "attributes-natural-language", b"en")
    attrs += _attribute(TAG_URI, "printer-uri", printer_uri.encode("utf-8"))
    attrs += _attribute(
        TAG_NAME_WITHOUT_LANGUAGE, "requesting-user-name", user_name.encode("utf-8")
    )
    attrs += _attribute(TAG_NAME_WITHOUT_LANGUAGE, "job-name", job_name.encode("utf-8"))
    attrs += _attribute(
        TAG_MIME_MEDIA_TYPE, "document-format", document_format.encode("utf-8")
    )
    attrs += bytes([TAG_END_OF_ATTRIBUTES])
    return header + attrs + document


def decode_response_header(data: bytes) -> IppResponse:
    """Decode the 8-byte IPP response header."""
    if len(data) < 8:
        raise IppError("IPP response too short")
    major, minor, status, request_id = struct.unpack(">BBHI", data[:8])
    return IppResponse((major, minor), status, request_id)


def http_url(printer_uri: str) -> str:
    """Map ipp:// and ipps:// URIs to the HTTP(S) URL to POST to."""
    parts = urlsplit(printer_uri)
    scheme = parts.scheme.lower()
    if scheme in ("http", "https"):
        return printer_uri
    if scheme not in ("ipp", "ipps"):
        raise IppError(f"Unsupported printer URI scheme: {parts.scheme}")
    netloc = parts.netloc
    if parts.port is None:
        netloc = f"{netloc}:{DEFAULT_PORT}"
    return urlunsplit(
        (
            "https" if scheme == "ipps" else "http",
            netloc,
            parts.path or "/",
            parts.query,
            "",
        )
    )


async def async_print_job(
    session: ClientSession,
    printer_uri: str,
    document: bytes,
    *,
    job_name: str = "Grocery list",
) -> IppResponse:
    """Send a PDF to an IPP printer and return the parsed response header."""
    body = encode_print_job(printer_uri, document, job_name=job_name)
    try:
        async with session.post(
            http_url(printer_uri),
            data=body,
            headers={"Content-Type": CONTENT_TYPE},
            timeout=REQUEST_TIMEOUT,
        ) as resp:
            if resp.status != 200:
                raise IppError(f"HTTP {resp.status} from printer")
            response = decode_response_header(await resp.read())
    except (ClientError, TimeoutError) as err:
        raise IppError(str(err)) from err
    if not response.ok:
        raise IppError(f"Printer returned IPP status 0x{response.status_code:04x}")
    return response
