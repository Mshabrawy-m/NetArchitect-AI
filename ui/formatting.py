"""Consistent, bounded formatting for visible engineering values.

All values are formatted as Latin/numeric tokens; an Arabic session isolates the
whole token so direction marks cannot reorder digits, decimals, IPs, or units.
The module performs no engineering work and owns no session state.
"""

from __future__ import annotations

import math

from ui import i18n

NA = "n/a"


def _na() -> str:
    """Return the translated missing-value marker."""
    return i18n.t("common.na")


def _plain_number(value: object, *, decimals: int) -> str | None:
    """Return a plain numeric string, or None for a missing value."""
    if value is None:
        return None
    if isinstance(value, bool):
        return i18n.t("common.yes") if value else i18n.t("common.no")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if decimals < 0:
        raise ValueError("decimals must be non-negative")
    return f"{number:,.{decimals}f}"


def number(value: object, *, decimals: int = 0) -> str:
    """Return a grouped number with a fixed number of decimals."""
    plain = _plain_number(value, decimals=decimals)
    return _na() if plain is None else i18n.ltr(plain)


def percent(value: object, *, decimals: int = 1) -> str:
    """Format a value that is already expressed in percentage points."""
    plain = _plain_number(value, decimals=decimals)
    return _na() if plain is None else i18n.ltr(f"{plain}%")


def ratio(value: object, *, decimals: int = 1) -> str:
    """Format a 0-1 ratio as a percentage, preserving exact rounding."""
    try:
        scaled = None if value is None else float(value) * 100
    except (TypeError, ValueError):
        scaled = None
    return percent(scaled, decimals=decimals)


def capacity_mbps(value: object, *, decimals: int = 1) -> str:
    """Format a link capacity or demand in Mbps."""
    plain = _plain_number(value, decimals=decimals)
    return _na() if plain is None else i18n.ltr(f"{plain} Mbps")


def latency_ms(value: object, *, decimals: int = 1) -> str:
    """Format a modeled latency in milliseconds, or n/a when absent."""
    plain = _plain_number(value, decimals=decimals)
    return _na() if plain is None else i18n.ltr(f"{plain} ms")


def signed(value: object, *, decimals: int = 0, unit: str = "") -> str:
    """Format a signed delta with an explicit unit."""
    if value is None:
        return _na()
    try:
        number_value = float(value)
    except (TypeError, ValueError):
        return _na()
    if not math.isfinite(number_value):
        return _na()
    return i18n.ltr(f"{number_value:+,.{decimals}f}{unit}")


def signed_int(value: object) -> str:
    """Format an integer delta, for example a served-demand change."""
    if value is None:
        return _na()
    try:
        number_value = int(value)
    except (TypeError, ValueError):
        return _na()
    return i18n.ltr(f"{number_value:+d}")


__all__ = [
    "NA",
    "capacity_mbps",
    "latency_ms",
    "number",
    "percent",
    "ratio",
    "signed",
    "signed_int",
]
