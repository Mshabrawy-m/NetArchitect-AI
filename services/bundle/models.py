"""Typed models for in-memory project bundles (B1).

A bundle is a deterministic ZIP of guarded JSON sections plus a manifest that
records what was captured and a SHA-256 checksum for every member. The models
here are pure data: no Streamlit, no clock read, and no disk access. All models
are frozen and forbid extra keys so a hostile manifest cannot smuggle fields
into the restored session state.

The bundle format is separate from the digital-twin schema. ``TWIN_SCHEMA_VERSION``
stays ``2``; the twin is stored through :mod:`digital_twin.serialization` and
the manifest version describes only this container.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from capacity.models import CapacityRun
from digital_twin import DigitalTwin, Snapshot
from forecasting.models import TimeSeries
from optimization.models import OptimizationRun
from security.models import FlowRequest
from services.copilot.decisions import DecisionRecord
from services.reporting.models import ReportDocument
from simulation import FailureSweepResult, RoutingModeComparison, ScenarioRun

CURRENT_BUNDLE_VERSION: int = 2
MIN_BUNDLE_VERSION: int = 1
BUNDLE_KIND: Literal["netarchitect-project-bundle"] = "netarchitect-project-bundle"

# Canonical member names. Every member written by ``create_bundle`` is one of
# these or a numbered file below a directory listed here.
TWIN_MEMBER = "twin.json"
DECISIONS_MEMBER = "decisions.json"
FLOWS_MEMBER = "security/flows.json"
SETTINGS_MEMBER = "settings.json"
MANIFEST_MEMBER = "manifest.json"

SECTION_DIRECTORIES: tuple[str, ...] = (
    "snapshots/",
    "runs/simulation/",
    "runs/sweeps/",
    "runs/mode_comparisons/",
    "runs/optimization/",
    "runs/capacity/",
    "runs/forecast/",
    "reports/",
)

# Secrets and session-only values are never included in a settings snapshot.
SECRET_SETTING_TOKENS: tuple[str, ...] = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "CREDENTIAL",
)


class BundleSourceFingerprints(BaseModel):
    """Content-keyed provenance maps captured alongside the runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    optimization_runs: dict[str, str] = Field(default_factory=dict)
    rerankings: dict[str, str] = Field(default_factory=dict)
    addressing_check: dict[str, str] = Field(default_factory=dict)
    report_times: dict[str, str] = Field(default_factory=dict)


class BundleProvenance(BaseModel):
    """Where the captured data came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    twin_fingerprint: str
    source_fingerprints: BundleSourceFingerprints = Field(
        default_factory=BundleSourceFingerprints
    )


class BundleSections(BaseModel):
    """Relative ZIP member paths for every captured section."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    twin: str = TWIN_MEMBER
    snapshots: tuple[str, ...] = Field(default_factory=tuple)
    simulation_runs: tuple[str, ...] = Field(default_factory=tuple)
    failure_sweeps: tuple[str, ...] = Field(default_factory=tuple)
    mode_comparisons: tuple[str, ...] = Field(default_factory=tuple)
    optimization_runs: tuple[str, ...] = Field(default_factory=tuple)
    capacity_runs: tuple[str, ...] = Field(default_factory=tuple)
    forecast_series: tuple[str, ...] = Field(default_factory=tuple)
    reports: tuple[str, ...] = Field(default_factory=tuple)
    decisions: str | None = None
    security_flows: str | None = None


class BundleManifest(BaseModel):
    """The manifest stored as ``manifest.json`` in every bundle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["netarchitect-project-bundle"] = BUNDLE_KIND
    bundle_version: int
    created_at: datetime
    source_app_version: str
    settings: dict[str, str] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=dict)
    provenance: BundleProvenance
    sections: BundleSections = Field(default_factory=BundleSections)
    members: dict[str, str] = Field(default_factory=dict)
    migration_path: tuple[str, ...] = Field(default_factory=tuple)


class BundleData(BaseModel):
    """Validated, in-memory payload returned by :func:`import_bundle`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    twin: DigitalTwin
    created_at: datetime
    source_app_version: str
    bundle_version: int
    snapshots: tuple[Snapshot, ...] = Field(default_factory=tuple)
    simulation_runs: tuple[ScenarioRun, ...] = Field(default_factory=tuple)
    failure_sweeps: tuple[FailureSweepResult, ...] = Field(default_factory=tuple)
    mode_comparisons: tuple[RoutingModeComparison, ...] = Field(default_factory=tuple)
    optimization_runs: tuple[OptimizationRun, ...] = Field(default_factory=tuple)
    capacity_runs: tuple[CapacityRun, ...] = Field(default_factory=tuple)
    forecast_series: tuple[TimeSeries, ...] = Field(default_factory=tuple)
    reports: tuple[ReportDocument, ...] = Field(default_factory=tuple)
    decision_records: tuple[DecisionRecord, ...] = Field(default_factory=tuple)
    security_flows: tuple[FlowRequest, ...] = Field(default_factory=tuple)
    settings: dict[str, str] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=dict)
    source_fingerprints: BundleSourceFingerprints = Field(
        default_factory=BundleSourceFingerprints
    )


__all__ = [
    "BUNDLE_KIND",
    "CURRENT_BUNDLE_VERSION",
    "DECISIONS_MEMBER",
    "FLOWS_MEMBER",
    "MANIFEST_MEMBER",
    "MIN_BUNDLE_VERSION",
    "SECRET_SETTING_TOKENS",
    "SECTION_DIRECTORIES",
    "SETTINGS_MEMBER",
    "TWIN_MEMBER",
    "BundleData",
    "BundleManifest",
    "BundleProvenance",
    "BundleSections",
    "BundleSourceFingerprints",
]
