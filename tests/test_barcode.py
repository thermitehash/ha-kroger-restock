"""Barcode normalization tests with real-format codes."""

from __future__ import annotations

import pytest

from custom_components.kroger_restock.barcode import (
    BarcodeKind,
    expand_upc_e,
    gs1_check_digit,
    has_valid_check_digit,
    normalize_barcode,
    plu_display_name,
    plu_search_term,
)


@pytest.mark.parametrize(
    ("body", "check"),
    [
        ("04900002891", 1),  # Coca-Cola 12 oz can, UPC-A 049000028911
        ("301762042200", 3),  # Nutella, EAN-13 3017620422003
        ("04210000526", 4),  # UPC-A form of UPC-E 04252614
        ("01111060903", 8),
    ],
)
def test_check_digit(body: str, check: int) -> None:
    """GS1 mod-10 check digits."""
    assert gs1_check_digit(body) == check
    assert has_valid_check_digit(body + str(check))


def test_upc_a() -> None:
    """Rule 1: drop the check digit, left-pad to 13."""
    result = normalize_barcode("049000028911")
    assert result.kind is BarcodeKind.UPC_A
    assert result.candidates == ("0004900002891", "0049000028911")


def test_upc_a_invalid_check_digit_tries_full_code_first() -> None:
    """A 12-digit code with a bad check digit is probably check-less."""
    result = normalize_barcode("049000028912")
    assert result.candidates[0] == "0049000028912"
    assert result.candidates[1] == "0004900002891"


def test_ean_13() -> None:
    """Rule 2: EAN-13, drop the check digit, left-pad."""
    result = normalize_barcode("3017620422003")
    assert result.kind is BarcodeKind.EAN_13
    assert result.candidates == ("0301762042200", "3017620422003")


def test_ean_13_with_leading_zero_is_upc() -> None:
    """A UPC-A scanned as EAN-13 maps to the same product ID."""
    assert normalize_barcode("0049000028911").candidates[0] == "0004900002891"


@pytest.mark.parametrize(
    ("upc_e", "upc_a"),
    [
        ("04252614", "042100005264"),  # d6 = 1
        ("01234505", "012000003455"),  # d6 = 0
        ("01234565", "012345000065"),  # d6 = 5-9
        ("01234531", "012300000451"),  # d6 = 3
        ("01234548", "012340000058"),  # d6 = 4
    ],
)
def test_upc_e_expansion(upc_e: str, upc_a: str) -> None:
    """Rule 3: UPC-E expands to UPC-A."""
    assert expand_upc_e(upc_e) == upc_a


def test_upc_e_candidates() -> None:
    """UPC-E expands then applies rule 1, then the fallback."""
    result = normalize_barcode("04252614")
    assert result.kind is BarcodeKind.UPC_E
    assert result.candidates == ("0004210000526", "0000004252614")


def test_upc_e_rejects_bad_number_system() -> None:
    """Number system must be 0 or 1."""
    assert expand_upc_e("54252614") is None


def test_ean_8_fallback() -> None:
    """EAN-8 (not a UPC-E) uses drop-check then full code."""
    result = normalize_barcode("96385074")  # valid EAN-8
    assert result.kind is BarcodeKind.EAN_8
    assert result.candidates == ("0000009638507", "0000096385074")


def test_11_digit_fallback() -> None:
    """Rule 4: unknown lengths are padded as-is."""
    result = normalize_barcode("04900002891")
    assert result.kind is BarcodeKind.OTHER
    assert result.candidates == ("0004900002891",)


def test_gtin_14() -> None:
    """GTIN-14 drops the check digit."""
    result = normalize_barcode("00049000028911")
    assert result.candidates[0] == "0004900002891"


def test_strips_scanner_noise() -> None:
    """Whitespace, CR/LF and symbology prefixes are ignored."""
    assert normalize_barcode(" 0490-0002-8911\r\n").digits == "049000028911"


@pytest.mark.parametrize(
    ("code", "plu", "organic", "name", "term"),
    [
        ("4011", "4011", False, "Bananas", "bananas"),
        ("94011", "4011", True, "Organic bananas", "organic bananas"),
        ("4999", "4999", False, "Produce PLU 4999", None),
    ],
)
def test_plu(code: str, plu: str, organic: bool, name: str, term: str | None) -> None:
    """Rule 5: PLUs get no candidates, just a search term."""
    result = normalize_barcode(code)
    assert result.is_plu
    assert result.candidates == ()
    assert result.plu == plu
    assert result.organic is organic
    assert plu_display_name(result) == name
    assert plu_search_term(result) == term


@pytest.mark.parametrize("code", ["", "abc", "1", "12345678901234567"])
def test_invalid(code: str) -> None:
    """Junk is rejected."""
    assert normalize_barcode(code).kind is BarcodeKind.INVALID
