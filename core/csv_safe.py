"""CSV cell neutralization for spreadsheet-safe exports.

Cells beginning with ``=``, ``+``, ``-``, ``@``, tab, or carriage return can be
interpreted as formulas by spreadsheet software. Exports prefix those cells
with an apostrophe. Plain signed numbers are left untouched so modeled values
remain numeric. Neutralization is applied only at serialization; stored domain
data is never changed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
)


def neutralize_cell(value: Any) -> str:
    """Return a spreadsheet-safe string representation of one CSV cell."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    stripped = text.lstrip(" \u00a0")
    if not stripped.startswith(_FORMULA_PREFIXES):
        return text
    if stripped[0] in "+-" and (
        len(stripped) == 1 or _PLAIN_NUMBER.fullmatch(stripped)
    ):
        return text
    return "'" + text


def neutralized_rows(rows: Iterable[Sequence[Any]]) -> tuple[tuple[str, ...], ...]:
    """Return every cell in ``rows`` as a neutralized string."""
    return tuple(tuple(neutralize_cell(cell) for cell in row) for row in rows)


__all__ = ["neutralize_cell", "neutralized_rows"]
