"""Strict CSV parsing with typed findings and explicit gap handling.

Accepted format (one header row, then one observation per row)::

    timestamp,series_id,value,unit
    2026-01-01T00:00:00,users-a,10,users
    2026-01-02T00:00:00,users-a,12,users

Timestamps must be ISO-8601 and consistently timezone-aware or consistently
naive. Rows must already be chronological inside each series; the parser reports
unsorted input instead of silently reordering it. Duplicate timestamps are
errors *within one series*; different series may share timestamps. Units may
differ between series but not inside one series.

Missing values are empty cells or ``na``, ``n/a``, ``nan``, ``none``, ``null``
(case-insensitive). They are never filled silently: ``reject`` makes the series
invalid, ``linear interpolate`` fills interior gaps, and ``carry forward`` fills
gaps after the first known value. Leading gaps cannot be carried forward and
trailing gaps cannot be interpolated; those remain unfilled and are reported.
"""

from __future__ import annotations

import csv
import io
import math
from collections import OrderedDict
from datetime import datetime

from config.limits import (
    MAX_FORECAST_POINTS,
    MAX_FORECAST_SERIES,
    MIN_FORECAST_POINTS,
)

from .models import (
    DataProvenance,
    FillReport,
    Finding,
    FindingCode,
    FindingSeverity,
    GapPolicy,
    Observation,
    ParseResult,
    SeriesUnit,
    TimeSeries,
)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "series_id",
    "value",
    "unit",
)
MISSING_TOKENS: frozenset[str] = frozenset(
    {"", "na", "n/a", "nan", "none", "null"}
)


def _finding(
    code: FindingCode,
    message: str,
    *,
    severity: FindingSeverity = FindingSeverity.error,
    series_id: str = "",
    row: int | None = None,
) -> Finding:
    return Finding(
        code=code,
        severity=severity,
        message=message,
        series_id=series_id,
        row=row,
    )


def _parse_timestamp(raw: str, row: int, findings: list[Finding]) -> datetime | None:
    text = raw.strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        findings.append(
            _finding(
                FindingCode.invalid_timestamp,
                f"Row {row}: {raw!r} is not an ISO-8601 timestamp.",
                row=row,
            )
        )
        return None


def _parse_value(raw: str, row: int, findings: list[Finding]) -> float | None | object:
    """Return a value, ``None`` for a missing cell, or a sentinel on error."""
    text = raw.strip()
    if text.lower() in MISSING_TOKENS:
        return None
    try:
        value = float(text)
    except ValueError:
        findings.append(
            _finding(
                FindingCode.non_numeric_value,
                f"Row {row}: value {raw!r} is not numeric.",
                row=row,
            )
        )
        return _INVALID
    if not math.isfinite(value):
        findings.append(
            _finding(
                FindingCode.non_numeric_value,
                f"Row {row}: value {raw!r} is not finite.",
                row=row,
            )
        )
        return _INVALID
    if value < 0:
        findings.append(
            _finding(
                FindingCode.negative_value,
                f"Row {row}: value {value:g} is negative; values must be >= 0.",
                row=row,
            )
        )
        return _INVALID
    return value


_INVALID = object()

_RawObservation = tuple[int, datetime, float | None]


def _fill_series(
    raw: list[_RawObservation],
    policy: GapPolicy,
    series_id: str,
    findings: list[Finding],
) -> tuple[tuple[Observation, ...], FillReport]:
    known = [index for index, (_, _, value) in enumerate(raw) if value is not None]
    details: list[str] = []
    filled: dict[int, float] = {}
    if policy is GapPolicy.reject:
        for row, _, value in raw:
            if value is None:
                findings.append(
                    _finding(
                        FindingCode.unfilled_gap,
                        f"Row {row}: missing value rejected for series {series_id!r}.",
                        series_id=series_id,
                        row=row,
                    )
                )
    elif known:
        first, last = known[0], known[-1]
        carried = 0.0
        for index, (row, _, value) in enumerate(raw):
            if value is not None:
                carried = float(value)
                continue
            if policy is GapPolicy.carry_forward:
                if index < first:
                    findings.append(
                        _finding(
                            FindingCode.unfilled_gap,
                            f"Row {row}: leading gap cannot be carried forward "
                            f"for series {series_id!r}.",
                            series_id=series_id,
                            row=row,
                        )
                    )
                    continue
                filled[index] = carried
                details.append(f"row {row}: carried forward {carried:g}")
            else:
                if index < first or index > last:
                    findings.append(
                        _finding(
                            FindingCode.unfilled_gap,
                            f"Row {row}: edge gap cannot be linearly interpolated "
                            f"for series {series_id!r}.",
                            series_id=series_id,
                            row=row,
                        )
                    )
                    continue
                before = max(position for position in known if position < index)
                after = min(position for position in known if position > index)
                left_value = raw[before][2]
                right_value = raw[after][2]
                assert left_value is not None and right_value is not None
                fraction = (index - before) / (after - before)
                filled_value = float(left_value) + fraction * (
                    float(right_value) - float(left_value)
                )
                filled[index] = filled_value
                details.append(f"row {row}: interpolated {filled_value:g}")
    observations = tuple(
        Observation(
            timestamp=timestamp,
            value=float(value if value is not None else filled.get(index, 0.0)),
        )
        for index, (_, timestamp, value) in enumerate(raw)
        if value is not None or index in filled
    )
    return observations, FillReport(
        policy=policy,
        filled_points=len(filled),
        unfilled_points=sum(1 for _, _, value in raw if value is None) - len(filled),
        details=tuple(details),
    )


def parse_csv(text: str, *, gap_policy: GapPolicy = GapPolicy.reject) -> ParseResult:
    """Parse and validate CSV text, returning series plus typed findings."""
    findings: list[Finding] = []
    if not isinstance(text, str) or not text.strip():
        return ParseResult(
            findings=(_finding(FindingCode.empty_input, "No CSV data was supplied."),)
        )

    reader = csv.reader(io.StringIO(text))
    try:
        header = [cell.strip().lower() for cell in next(reader)]
    except StopIteration:
        return ParseResult(
            findings=(_finding(FindingCode.empty_input, "The CSV has no header row."),)
        )

    missing = [name for name in REQUIRED_COLUMNS if name not in header]
    for name in missing:
        findings.append(
            _finding(
                FindingCode.missing_column,
                f"Required column {name!r} is missing.",
            )
        )
    unknown = [name for name in header if name and name not in REQUIRED_COLUMNS]
    for name in unknown:
        findings.append(
            _finding(
                FindingCode.unknown_column,
                f"Column {name!r} is not part of the accepted format.",
            )
        )
    if missing or unknown:
        return ParseResult(findings=tuple(findings))

    index = {name: header.index(name) for name in REQUIRED_COLUMNS}
    grouped: OrderedDict[str, list[_RawObservation]] = OrderedDict()
    units: dict[str, SeriesUnit] = {}
    raw_rows = 0
    for row_number, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            continue
        raw_rows += 1
        if len(cells) != len(header):
            findings.append(
                _finding(
                    FindingCode.malformed_row,
                    f"Row {row_number}: expected {len(header)} cells, got {len(cells)}.",
                    row=row_number,
                )
            )
            continue
        series_id = cells[index["series_id"]].strip()
        if not series_id:
            findings.append(
                _finding(
                    FindingCode.invalid_series_id,
                    f"Row {row_number}: series id is empty.",
                    row=row_number,
                )
            )
            continue
        unit_text = cells[index["unit"]].strip()
        try:
            unit = SeriesUnit(unit_text)
        except ValueError:
            findings.append(
                _finding(
                    FindingCode.invalid_unit,
                    f"Row {row_number}: unit {unit_text!r} must be 'users' or 'Mbps'.",
                    series_id=series_id,
                    row=row_number,
                )
            )
            continue
        timestamp = _parse_timestamp(cells[index["timestamp"]], row_number, findings)
        if timestamp is None:
            continue
        value = _parse_value(cells[index["value"]], row_number, findings)
        if value is _INVALID:
            continue
        if series_id in units and units[series_id] is not unit:
            findings.append(
                _finding(
                    FindingCode.mixed_units,
                    f"Row {row_number}: series {series_id!r} mixes units "
                    f"{units[series_id].value!r} and {unit.value!r}.",
                    series_id=series_id,
                    row=row_number,
                )
            )
            continue
        units[series_id] = unit
        grouped.setdefault(series_id, []).append((row_number, timestamp, value))

    if raw_rows > MAX_FORECAST_POINTS:
        findings.append(
            _finding(
                FindingCode.point_limit,
                f"CSV has {raw_rows} data rows; the limit is {MAX_FORECAST_POINTS}.",
            )
        )
        return ParseResult(findings=tuple(findings), raw_rows=raw_rows)
    if len(grouped) > MAX_FORECAST_SERIES:
        findings.append(
            _finding(
                FindingCode.series_limit,
                f"CSV has {len(grouped)} series; the limit is {MAX_FORECAST_SERIES}.",
            )
        )
        return ParseResult(findings=tuple(findings), raw_rows=raw_rows)

    series: list[TimeSeries] = []
    for series_id, rows in grouped.items():
        timestamps = [entry[1] for entry in rows]
        aware = [timestamp.tzinfo is not None for timestamp in timestamps]
        if len(set(aware)) > 1:
            findings.append(
                _finding(
                    FindingCode.invalid_timestamp,
                    f"Series {series_id!r} mixes timezone-aware and naive timestamps.",
                    series_id=series_id,
                )
            )
            continue
        if timestamps != sorted(timestamps):
            findings.append(
                _finding(
                    FindingCode.unsorted_timestamps,
                    f"Series {series_id!r} is not in ascending timestamp order.",
                    series_id=series_id,
                )
            )
            continue
        duplicates = {
            timestamp
            for timestamp in timestamps
            if timestamps.count(timestamp) > 1
        }
        if duplicates:
            for row_number, timestamp, _ in rows:
                if timestamp in duplicates:
                    findings.append(
                        _finding(
                            FindingCode.duplicate_timestamp,
                            f"Row {row_number}: duplicate timestamp "
                            f"{timestamp.isoformat()} in series {series_id!r}.",
                            series_id=series_id,
                            row=row_number,
                        )
                    )
            continue
        for row_number, _, value in rows:
            if value is None:
                findings.append(
                    _finding(
                        FindingCode.missing_value,
                        f"Row {row_number}: missing value in series {series_id!r}; "
                        f"policy {gap_policy.value!r}.",
                        severity=FindingSeverity.warning,
                        series_id=series_id,
                        row=row_number,
                    )
                )
        observations, fill_report = _fill_series(rows, gap_policy, series_id, findings)
        if any(
            finding.severity is FindingSeverity.error
            and finding.series_id == series_id
            and finding.code is FindingCode.unfilled_gap
            for finding in findings
        ):
            continue
        if len(observations) < MIN_FORECAST_POINTS:
            findings.append(
                _finding(
                    FindingCode.too_few_points,
                    f"Series {series_id!r} has {len(observations)} usable points; "
                    f"the minimum is {MIN_FORECAST_POINTS}.",
                    series_id=series_id,
                )
            )
            continue
        series.append(
            TimeSeries(
                series_id=series_id,
                unit=units[series_id],
                provenance=DataProvenance.user_supplied,
                observations=observations,
                fill_report=fill_report,
            )
        )
    return ParseResult(
        series=tuple(series),
        findings=tuple(findings),
        raw_rows=raw_rows,
    )


__all__ = ["MISSING_TOKENS", "REQUIRED_COLUMNS", "parse_csv"]
