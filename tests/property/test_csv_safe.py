"""Bounded spreadsheet-formula neutralization invariants."""

from __future__ import annotations

import re

from hypothesis import given
from hypothesis import strategies as st

from core.csv_safe import neutralize_cell, neutralized_rows
from tests.property.config import BOUNDED

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


@st.composite
def _cells(draw):
    return draw(
        st.one_of(
            st.none(),
            st.booleans(),
            st.integers(min_value=-1000, max_value=1000),
            st.floats(
                min_value=-1000.0,
                max_value=1000.0,
                allow_nan=False,
                allow_infinity=False,
                width=32,
            ),
            st.text(max_size=40),
        )
    )


@BOUNDED
@given(value=_cells())
def test_neutralize_cell_only_quotes_formula_like_text(value) -> None:
    original = "" if value is None else str(value)
    result = neutralize_cell(value)
    stripped = original.lstrip(" \u00a0")
    plain_number = bool(_PLAIN_NUMBER.fullmatch(stripped)) and stripped[0] in "+-"
    dangerous = stripped.startswith(_FORMULA_PREFIXES) and not plain_number

    if dangerous:
        assert result == "'" + original
    else:
        assert result == original

    result_stripped = result.lstrip(" \u00a0")
    if result_stripped.startswith(_FORMULA_PREFIXES):
        assert _PLAIN_NUMBER.fullmatch(result_stripped)


@BOUNDED
@given(rows=st.lists(st.lists(_cells(), max_size=4), max_size=4))
def test_neutralized_rows_applies_cell_rule(rows) -> None:
    assert neutralized_rows(rows) == tuple(
        tuple(neutralize_cell(cell) for cell in row) for row in rows
    )
