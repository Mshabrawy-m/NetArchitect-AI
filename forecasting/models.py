"""Typed inputs and results for deterministic capacity forecasting.

Every value produced by this package is a *modeled projection from stated
assumptions*, not a measurement or a guarantee. There is no machine learning:
only explicit time-series rules implemented with NumPy arithmetic.

Data provenance is mandatory. A series is either ``user_supplied`` or
``synthetic``; synthetic data always carries the ``SYNTHETIC`` label in results,
charts, exports, and reports.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL_NOTE = (
    "Modeled projection from stated assumptions; not a measurement or guarantee."
)
SYNTHETIC_LABEL = "SYNTHETIC"
USER_SUPPLIED_LABEL = "USER-SUPPLIED"
APPROX_INTERVAL_NOTE = (
    "Approximate residual-based prediction interval; not a calibrated "
    "confidence or guarantee."
)

# Fixed normal quantile used by the residual-based interval. It is a stated
# modeling assumption, not a fitted parameter.
INTERVAL_Z = 1.96


class DataProvenance(str, Enum):
    """Origin of one time series. Never inferred."""

    user_supplied = "user_supplied"
    synthetic = "synthetic"

    @property
    def label(self) -> str:
        """The uppercase label used in UI, exports, and reports."""
        return SYNTHETIC_LABEL if self is DataProvenance.synthetic else USER_SUPPLIED_LABEL


class SeriesUnit(str, Enum):
    """Supported semantic units for a demand forecast."""

    users = "users"
    mbps = "Mbps"


class GapPolicy(str, Enum):
    """How missing observations are handled. Never applied silently."""

    reject = "reject"
    linear_interpolate = "linear interpolate"
    carry_forward = "carry forward"


class FindingSeverity(str, Enum):
    """Severity of a validation finding."""

    error = "error"
    warning = "warning"
    info = "info"


class FindingCode(str, Enum):
    """Stable codes for parsing and validation findings."""

    missing_column = "missing_column"
    unknown_column = "unknown_column"
    empty_input = "empty_input"
    malformed_row = "malformed_row"
    duplicate_timestamp = "duplicate_timestamp"
    non_numeric_value = "non_numeric_value"
    negative_value = "negative_value"
    unsorted_timestamps = "unsorted_timestamps"
    mixed_units = "mixed_units"
    too_few_points = "too_few_points"
    missing_value = "missing_value"
    unfilled_gap = "unfilled_gap"
    series_limit = "series_limit"
    point_limit = "point_limit"
    invalid_timestamp = "invalid_timestamp"
    invalid_series_id = "invalid_series_id"
    invalid_unit = "invalid_unit"


class ForecastModelKind(str, Enum):
    """Deterministic forecast rules implemented by this package."""

    naive = "naive"
    moving_average = "moving_average"
    linear_trend = "linear_trend"
    holt = "holt"
    seasonal_naive = "seasonal_naive"


class Finding(BaseModel):
    """One typed, non-fatal validation finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: FindingCode
    severity: FindingSeverity
    message: str
    series_id: str = ""
    row: int | None = Field(
        default=None,
        description="One-based CSV data row, when the finding is row-specific.",
    )


class FillReport(BaseModel):
    """Explicit record of every missing value that was filled."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy: GapPolicy
    filled_points: int = Field(ge=0)
    unfilled_points: int = Field(ge=0)
    details: tuple[str, ...] = Field(default_factory=tuple)


class Observation(BaseModel):
    """One numeric observation at a caller-supplied timestamp."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    value: float = Field(ge=0)


class TimeSeries(BaseModel):
    """One validated, chronological, single-unit series."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    series_id: str = Field(min_length=1)
    unit: SeriesUnit
    provenance: DataProvenance
    observations: tuple[Observation, ...] = Field(default_factory=tuple)
    fill_report: FillReport = Field(
        default_factory=lambda: FillReport(policy=GapPolicy.reject, filled_points=0, unfilled_points=0),
    )

    @model_validator(mode="after")
    def _chronological(self) -> TimeSeries:
        timestamps = [observation.timestamp for observation in self.observations]
        if timestamps != sorted(timestamps):
            raise ValueError("Observations must be sorted by timestamp.")
        if len(set(timestamps)) != len(timestamps):
            raise ValueError("A series cannot contain duplicate timestamps.")
        return self

    @property
    def label(self) -> str:
        """The provenance label that must travel with this series."""
        return self.provenance.label


class ParseResult(BaseModel):
    """Result of strict CSV parsing. Findings are returned, never raised."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    series: tuple[TimeSeries, ...] = Field(default_factory=tuple)
    findings: tuple[Finding, ...] = Field(default_factory=tuple)
    raw_rows: int = Field(default=0, ge=0)

    @property
    def valid(self) -> bool:
        """True when no error-severity finding was produced."""
        return not any(finding.severity is FindingSeverity.error for finding in self.findings)


class HistorySummary(BaseModel):
    """Descriptive, non-predictive summary of the observed history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int = Field(ge=0)
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    unit: SeriesUnit
    step_seconds: float = Field(
        default=0.0,
        ge=0,
        description="Median positive timestamp spacing used to place forecast points.",
    )
    irregular_spacing: bool = False


class ForecastPoint(BaseModel):
    """One modeled projection with its approximate interval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: int = Field(ge=1)
    timestamp: datetime
    value: float
    lower: float | None = None
    upper: float | None = None


class EvaluationMetrics(BaseModel):
    """Chronological held-out accuracy metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mae: float = Field(ge=0)
    rmse: float = Field(ge=0)
    smape: float = Field(ge=0)
    sample_count: int = Field(ge=0)


class ModelEvaluation(BaseModel):
    """One candidate model's held-out evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: ForecastModelKind
    parameters: dict[str, float | int | str]
    metrics: EvaluationMetrics


class ForecastResult(BaseModel):
    """Complete, traceable result for one forecast."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    series_id: str
    provenance: DataProvenance
    data_label: str
    unit: SeriesUnit
    model: ForecastModelKind
    parameters: dict[str, float | int | str] = Field(default_factory=dict)
    history: HistorySummary
    forecast_points: tuple[ForecastPoint, ...]
    evaluation: ModelEvaluation
    naive_evaluation: ModelEvaluation
    beats_naive: bool
    selection_note: str
    fill_report: FillReport
    assumptions: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class ForecastRun(BaseModel):
    """A bounded set of per-series forecast results and settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    results: tuple[ForecastResult, ...] = Field(default_factory=tuple)
    horizon: int = Field(ge=1)
    gap_policy: GapPolicy
    findings: tuple[Finding, ...] = Field(default_factory=tuple)
    model_note: str = MODEL_NOTE
    interval_note: str = APPROX_INTERVAL_NOTE

    @property
    def has_synthetic(self) -> bool:
        """True when any result was produced from SYNTHETIC data."""
        return any(result.provenance is DataProvenance.synthetic for result in self.results)


__all__ = [
    "APPROX_INTERVAL_NOTE",
    "INTERVAL_Z",
    "MODEL_NOTE",
    "SYNTHETIC_LABEL",
    "USER_SUPPLIED_LABEL",
    "DataProvenance",
    "EvaluationMetrics",
    "FillReport",
    "Finding",
    "FindingCode",
    "FindingSeverity",
    "ForecastModelKind",
    "ForecastPoint",
    "ForecastResult",
    "ForecastRun",
    "GapPolicy",
    "HistorySummary",
    "ModelEvaluation",
    "Observation",
    "ParseResult",
    "SeriesUnit",
    "TimeSeries",
]
