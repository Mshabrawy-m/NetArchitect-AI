"""Strict CSV parsing and gap-handling tests."""

from __future__ import annotations

from forecasting import (
    FindingCode,
    FindingSeverity,
    GapPolicy,
    parse_csv,
    parsing,
)
from tests.unit.forecasting.helpers import csv_text, rows_for

EIGHT = [str(value) for value in range(10, 18)]


def _codes(result: object) -> set[str]:
    return {finding.code.value for finding in result.findings}  # type: ignore[attr-defined]


def test_valid_csv_parses_two_series_with_provenance() -> None:
    rows = rows_for(EIGHT) + rows_for(
        ["1", "2", "3", "4", "5", "6", "7", "8"],
        series_id="s2",
        unit="Mbps",
    )
    result = parse_csv(csv_text(rows))

    assert result.valid
    assert result.raw_rows == 16
    assert [series.series_id for series in result.series] == ["s1", "s2"]
    assert [series.unit.value for series in result.series] == ["users", "Mbps"]
    assert all(series.provenance.value == "user_supplied" for series in result.series)
    assert result.series[0].observations[0].value == 10
    assert result.series[0].fill_report.filled_points == 0


def test_each_bad_input_yields_its_expected_finding() -> None:
    cases = [
        (
            csv_text(rows_for(EIGHT), header="timestamp,series_id,value"),
            FindingCode.missing_column,
        ),
        (
            csv_text(rows_for(EIGHT), header="timestamp,series_id,value,unit,extra"),
            FindingCode.unknown_column,
        ),
        (
            csv_text(rows_for(EIGHT)[:3] + [rows_for(EIGHT)[2]] + rows_for(EIGHT)[3:]),
            FindingCode.duplicate_timestamp,
        ),
        (
            csv_text(rows_for(["1", "2", "abc"] + EIGHT[3:])),
            FindingCode.non_numeric_value,
        ),
        (
            csv_text(rows_for(["1", "-2"] + EIGHT[2:])),
            FindingCode.negative_value,
        ),
        (
            csv_text([rows_for(EIGHT)[1], rows_for(EIGHT)[0], *rows_for(EIGHT)[2:]]),
            FindingCode.unsorted_timestamps,
        ),
        (
            csv_text(
                rows_for(EIGHT[:4])
                + rows_for(EIGHT[4:], unit="Mbps")
            ),
            FindingCode.mixed_units,
        ),
        (
            csv_text(rows_for(["1", "2", "3"])),
            FindingCode.too_few_points,
        ),
        (
            csv_text([("not-a-date", "s1", "11", "users")]),
            FindingCode.invalid_timestamp,
        ),
        (
            csv_text(rows_for(EIGHT[:4]) + rows_for(EIGHT[4:], unit="packets")),
            FindingCode.invalid_unit,
        ),
        ("", FindingCode.empty_input),
    ]
    for text, expected in cases:
        result = parse_csv(text)
        assert expected in _codes(result), (expected, result.findings)
        assert not result.valid


def test_malformed_row_is_reported_without_crashing() -> None:
    rows = rows_for(EIGHT)
    rows[2] = ("2026-01-03T00:00:00", "s1", "12")
    result = parse_csv(csv_text(rows))

    assert FindingCode.malformed_row in _codes(result)
    assert not result.valid


def test_gap_modes_have_hand_computed_fills() -> None:
    # Missing fourth raw point sits between 12 and 14.
    values = ["10", "11", "12", "", "14", "15", "16", "17"]
    rows = rows_for(values)

    rejected = parse_csv(csv_text(rows), gap_policy=GapPolicy.reject)
    assert FindingCode.missing_value in _codes(rejected)
    assert FindingCode.unfilled_gap in _codes(rejected)
    assert rejected.series == ()

    interpolated = parse_csv(csv_text(rows), gap_policy=GapPolicy.linear_interpolate)
    assert interpolated.valid
    # (12 + 14) / 2 = 13; one filled row.
    assert interpolated.series[0].observations[3].value == 13.0
    assert interpolated.series[0].fill_report.filled_points == 1
    assert interpolated.series[0].fill_report.policy is GapPolicy.linear_interpolate
    assert any("interpolated" in detail for detail in interpolated.series[0].fill_report.details)

    carried = parse_csv(csv_text(rows), gap_policy=GapPolicy.carry_forward)
    assert carried.valid
    # Previous observation was 12, so the carried value is 12.
    assert carried.series[0].observations[3].value == 12.0
    assert carried.series[0].fill_report.filled_points == 1


def test_leading_gap_is_never_filled_silently() -> None:
    rows = rows_for(["", "11", "12", "13", "14", "15", "16", "17"])
    result = parse_csv(csv_text(rows), gap_policy=GapPolicy.carry_forward)

    assert FindingCode.unfilled_gap in _codes(result)
    assert result.series == ()
    assert any(
        finding.severity is FindingSeverity.warning
        and finding.code is FindingCode.missing_value
        for finding in result.findings
    )


def test_limits_are_reported_as_findings(monkeypatch: object) -> None:
    monkeypatch.setattr(parsing, "MAX_FORECAST_POINTS", 4)  # type: ignore[attr-defined]
    points = parse_csv(csv_text(rows_for(EIGHT)))
    assert FindingCode.point_limit in _codes(points)

    monkeypatch.setattr(parsing, "MAX_FORECAST_POINTS", 2_000)  # type: ignore[attr-defined]
    monkeypatch.setattr(parsing, "MAX_FORECAST_SERIES", 1)  # type: ignore[attr-defined]
    two_series = csv_text(
        rows_for(EIGHT) + rows_for(EIGHT, series_id="s2")
    )
    series = parse_csv(two_series)
    assert FindingCode.series_limit in _codes(series)
