"""Barcode normalization for Kroger product IDs.

Kroger product IDs are 13 digits: the GTIN without its check digit,
left-padded with zeros. A scanned code can arrive in several formats, so we
build an ordered list of candidate product IDs and try each in turn.

This module is pure Python and has no Home Assistant dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

PRODUCT_ID_LENGTH = 13


class BarcodeKind(StrEnum):
    """Recognized barcode formats."""

    UPC_A = "upc_a"
    UPC_E = "upc_e"
    EAN_13 = "ean_13"
    EAN_8 = "ean_8"
    GTIN_14 = "gtin_14"
    PLU = "plu"
    OTHER = "other"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class NormalizedBarcode:
    """Result of normalizing a scanned code."""

    raw: str
    digits: str
    kind: BarcodeKind
    candidates: tuple[str, ...] = field(default_factory=tuple)
    plu: str | None = None
    organic: bool = False

    @property
    def is_plu(self) -> bool:
        """Return True for produce PLU codes."""
        return self.kind is BarcodeKind.PLU


def gs1_check_digit(body: str) -> int:
    """Return the GS1 mod-10 check digit for ``body`` (digits without check)."""
    total = 0
    # Weights alternate 3,1,3,1... starting from the rightmost body digit.
    for index, char in enumerate(reversed(body)):
        digit = int(char)
        total += digit * 3 if index % 2 == 0 else digit
    return (10 - total % 10) % 10


def has_valid_check_digit(code: str) -> bool:
    """Return True if the last digit of ``code`` is a valid GS1 check digit."""
    if len(code) < 2 or not code.isdigit():
        return False
    return gs1_check_digit(code[:-1]) == int(code[-1])


def expand_upc_e(code: str) -> str | None:
    """Expand an 8-digit UPC-E code to a 12-digit UPC-A code.

    Returns None if the code is not a plausible UPC-E (number system 0 or 1).
    """
    if len(code) != 8 or not code.isdigit():
        return None
    number_system = code[0]
    if number_system not in "01":
        return None
    d1, d2, d3, d4, d5, d6 = code[1:7]
    check = code[7]
    if d6 in "012":
        body = f"{d1}{d2}{d6}0000{d3}{d4}{d5}"
    elif d6 == "3":
        body = f"{d1}{d2}{d3}00000{d4}{d5}"
    elif d6 == "4":
        body = f"{d1}{d2}{d3}{d4}00000{d5}"
    else:
        body = f"{d1}{d2}{d3}{d4}{d5}0000{d6}"
    return f"{number_system}{body}{check}"


def _pad(code: str) -> str:
    return code.zfill(PRODUCT_ID_LENGTH)[-PRODUCT_ID_LENGTH:]


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        if value and len(value) == PRODUCT_ID_LENGTH:
            seen.setdefault(value, None)
    return tuple(seen)


def normalize_barcode(raw: str) -> NormalizedBarcode:
    """Normalize a scanned code into ordered Kroger product ID candidates.

    Rules, in order:
      1. UPC-A (12 digits): drop the check digit, left-pad to 13.
      2. EAN-13: drop the check digit, left-pad to 13.
      3. UPC-E (8 digits): expand to UPC-A, then rule 1.
      4. Fallback: the full code, left-pad to 13.
      5. PLU (4-5 digits): no candidates; caller does a name search.
    """
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    length = len(digits)

    if length < 4:
        return NormalizedBarcode(raw=raw, digits="", kind=BarcodeKind.INVALID)

    if length in (4, 5):
        organic = length == 5 and digits[0] == "9"
        plu = digits[1:] if length == 5 else digits
        return NormalizedBarcode(
            raw=raw,
            digits=digits,
            kind=BarcodeKind.PLU,
            plu=plu,
            organic=organic,
        )

    candidates: list[str] = []
    kind = BarcodeKind.OTHER

    if length == 12:
        kind = BarcodeKind.UPC_A
        if has_valid_check_digit(digits):
            candidates += [_pad(digits[:-1]), _pad(digits)]
        else:
            # Probably not a check-digit-bearing code; try it as-is first.
            candidates += [_pad(digits), _pad(digits[:-1])]
    elif length == 13:
        kind = BarcodeKind.EAN_13
        if has_valid_check_digit(digits):
            candidates += [_pad(digits[:-1]), digits]
        else:
            candidates += [digits, _pad(digits[:-1])]
    elif length == 14:
        kind = BarcodeKind.GTIN_14
        candidates.append(_pad(digits[:-1]))
        if digits[0] == "0":
            candidates.append(digits[1:])
    elif length == 8:
        upc_a = expand_upc_e(digits)
        if upc_a is not None and has_valid_check_digit(upc_a):
            kind = BarcodeKind.UPC_E
            candidates.append(_pad(upc_a[:-1]))
        else:
            kind = BarcodeKind.EAN_8
            if has_valid_check_digit(digits):
                candidates.append(_pad(digits[:-1]))
        candidates.append(_pad(digits))
    elif 6 <= length < PRODUCT_ID_LENGTH:
        # 6, 7, 9, 10, 11 digits: e.g. a UPC-A whose check digit was stripped
        # by the scanner. Fallback rule only.
        candidates.append(_pad(digits))
    else:
        return NormalizedBarcode(raw=raw, digits=digits, kind=BarcodeKind.INVALID)

    return NormalizedBarcode(
        raw=raw, digits=digits, kind=kind, candidates=_dedupe(candidates)
    )


# A small table of very common IFPS produce PLUs. Used only to build a better
# search term; unknown PLUs still go to review.
COMMON_PLUS: dict[str, str] = {
    "3283": "Honeycrisp apples",
    "4011": "Bananas",
    "4022": "Green seedless grapes",
    "4023": "Red seedless grapes",
    "4046": "Hass avocados",
    "4048": "Limes",
    "4053": "Lemons",
    "4060": "Broccoli",
    "4062": "Cucumbers",
    "4065": "Green bell peppers",
    "4072": "Russet potatoes",
    "4082": "Red onions",
    "4087": "Roma tomatoes",
    "4131": "Fuji apples",
    "4225": "Hass avocados",
    "4664": "Tomatoes on the vine",
}


def plu_search_term(normalized: NormalizedBarcode) -> str | None:
    """Return a product search term for a PLU, or None if it's unknown."""
    if normalized.plu is None:
        return None
    name = COMMON_PLUS.get(normalized.plu)
    if name is None:
        return None
    return f"organic {name.lower()}" if normalized.organic else name.lower()


def plu_display_name(normalized: NormalizedBarcode) -> str:
    """Return a human-readable name for a PLU item."""
    name = COMMON_PLUS.get(normalized.plu or "")
    if name is None:
        return f"Produce PLU {normalized.digits}"
    return f"Organic {name.lower()}" if normalized.organic else name
