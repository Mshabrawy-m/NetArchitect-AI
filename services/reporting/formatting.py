"""Number formatting and numeric-token extraction for reports.

The report builder formats every number through :func:`format_number`, and the
consistency checker extracts numeric tokens with :func:`numeric_tokens` before
comparing them with the report's ``ValueRecord`` appendix. The two functions are
kept together so the "what the report prints" and "what the checker reads"
rules cannot drift apart.

IP addresses and CIDR prefixes are masked before token extraction: they are
identifiers, not measured quantities, and their dotted octets are not report
numbers.
"""

from __future__ import annotations

import re

_IPV4_OR_CIDR = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b")
_IPV6_OR_CIDR = re.compile(
    r"(?<![0-9A-Za-z])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?:/\d{1,3})?\b"
)
# A standalone number, not part of an identifier such as "site-1" or "r2".
_NUMERIC_TOKEN = re.compile(r"(?<![A-Za-z0-9_.-])-?\d+(?:\.\d+)?(?![A-Za-z0-9_.-])")
_PLAIN_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def format_number(value: float, *, digits: int = 2) -> str:
    """Format one number deterministically, without thousands separators.

    Integers print without a decimal part. Fractions are rounded to ``digits``
    and trailing zeros are removed. No thousands separators are used so the
    printed token is also a valid CSV field.
    """
    if isinstance(value, bool):
        raise TypeError("format_number does not accept booleans")
    number = float(value)
    if not number.is_integer():
        return f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return str(int(number))


def parse_display(display: str) -> float | None:
    """Return the numeric value of a printed field, or None when it is text."""
    text = display.strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    if _PLAIN_NUMBER.fullmatch(text) is None:
        return None
    return float(text)


def masked_text(text: str) -> str:
    """Return text with IP addresses and CIDR prefixes removed."""
    without_v4 = _IPV4_OR_CIDR.sub(" ", text)
    return _IPV6_OR_CIDR.sub(" ", without_v4)


def numeric_tokens(text: str) -> list[str]:
    """Return standalone numeric tokens, excluding addresses and identifiers."""
    return [match.group() for match in _NUMERIC_TOKEN.finditer(masked_text(text))]


__all__ = [
    "format_number",
    "masked_text",
    "numeric_tokens",
    "parse_display",
]
