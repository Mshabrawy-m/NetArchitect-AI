"""Build and restore in-memory project bundles (B1).

The bundle captures one digital twin plus the bounded derived results a user may
want to hand to a colleague: snapshots, engine runs with their source
fingerprints, a decision log, modeled security flow requests, and a non-secret
settings snapshot. Everything is produced and consumed in memory; the only I/O
is the caller's upload/download of the returned bytes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from capacity.models import CapacityRun
from config import limits as limits_module
from config.limits import (
    MAX_CAPACITY_RUNS,
    MAX_COPILOT_DECISIONS,
    MAX_FORECAST_SERIES,
    MAX_OPTIMIZATION_RUNS,
    MAX_SCENARIOS,
    MAX_SECURITY_FLOW_CHECKS,
    MAX_SNAPSHOTS,
    MAX_TWIN_SNAPSHOT_BYTES,
)
from config.settings import Settings
from core.exceptions import NetArchitectError
from digital_twin import Snapshot
from digital_twin.serialization import from_json as twin_from_json
from digital_twin.serialization import to_json as twin_to_json
from forecasting.models import TimeSeries
from optimization.models import OptimizationRun
from security.models import FlowRequest
from services.copilot.decisions import DecisionRecord
from services.export.json_export import from_json as report_from_json
from services.export.json_export import to_json as report_to_json
from services.reporting.models import ReportDocument
from simulation import FailureSweepResult, RoutingModeComparison, ScenarioRun
from simulation.evaluator import twin_fingerprint

from .codec import (
    build_archive,
    decode_json,
    digest,
    read_archive,
    verify_checksums,
)
from .errors import BundleFormatError, BundleLimitError
from .migrations import migrate_manifest
from .models import (
    CURRENT_BUNDLE_VERSION,
    DECISIONS_MEMBER,
    FLOWS_MEMBER,
    MANIFEST_MEMBER,
    SECRET_SETTING_TOKENS,
    SETTINGS_MEMBER,
    TWIN_MEMBER,
    BundleData,
    BundleManifest,
    BundleProvenance,
    BundleSections,
)

_MAX_BUNDLE_REPORTS = 8
_T = TypeVar("_T", bound=BaseModel)

_LIMIT_NAMES: tuple[str, ...] = (
    "MAX_NODES",
    "MAX_EDGES",
    "MAX_DEMANDS",
    "MAX_SCENARIOS",
    "MAX_OPTIMIZATION_RUNS",
    "MAX_CAPACITY_RUNS",
    "MAX_FORECAST_SERIES",
    "MAX_SNAPSHOTS",
    "MAX_SECURITY_FLOW_CHECKS",
    "MAX_COPILOT_DECISIONS",
    "MAX_INPUT_BYTES",
    "MAX_JSON_DEPTH",
    "MAX_BUNDLE_BYTES",
    "MAX_BUNDLE_MEMBERS",
)


def _safe_settings(values: Mapping[str, object]) -> dict[str, str]:
    """Keep only non-secret scalar settings, sorted for deterministic bytes."""
    return {
        str(key): str(value)
        for key, value in sorted(values.items())
        if not any(token in str(key).upper() for token in SECRET_SETTING_TOKENS)
    }


def settings_snapshot(settings: Settings) -> dict[str, str]:
    """Return non-secret settings as a deterministic string mapping."""
    return _safe_settings(settings.model_dump(mode="json"))


def limits_snapshot() -> dict[str, int]:
    """Return the read-only numeric limits relevant to a restored session."""
    return {name: int(getattr(limits_module, name)) for name in _LIMIT_NAMES}


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=None) + "\n"
    ).encode("utf-8")


def _numbered(directory: str, count: int) -> tuple[str, ...]:
    return tuple(f"{directory}{index:04d}.json" for index in range(count))


def _model_payloads(items: Sequence[BaseModel]) -> list[bytes]:
    return [item.model_dump_json().encode("utf-8") for item in items]


def build_bundle(data: BundleData) -> bytes:
    """Serialize ``data`` to a deterministic in-memory ZIP archive."""
    members: dict[str, bytes] = {
        TWIN_MEMBER: twin_to_json(data.twin, indent=None).encode("utf-8"),
    }

    sections = BundleSections(
        twin=TWIN_MEMBER,
        snapshots=_numbered("snapshots/", len(data.snapshots)),
        simulation_runs=_numbered("runs/simulation/", len(data.simulation_runs)),
        failure_sweeps=_numbered("runs/sweeps/", len(data.failure_sweeps)),
        mode_comparisons=_numbered(
            "runs/mode_comparisons/", len(data.mode_comparisons)
        ),
        optimization_runs=_numbered(
            "runs/optimization/", len(data.optimization_runs)
        ),
        capacity_runs=_numbered("runs/capacity/", len(data.capacity_runs)),
        forecast_series=_numbered("runs/forecast/", len(data.forecast_series)),
        reports=_numbered("reports/", len(data.reports)),
        decisions=DECISIONS_MEMBER if data.decision_records else None,
        security_flows=FLOWS_MEMBER if data.security_flows else None,
    )

    grouped: tuple[tuple[tuple[str, ...], Sequence[BaseModel]], ...] = (
        (sections.snapshots, data.snapshots),
        (sections.simulation_runs, data.simulation_runs),
        (sections.failure_sweeps, data.failure_sweeps),
        (sections.mode_comparisons, data.mode_comparisons),
        (sections.optimization_runs, data.optimization_runs),
        (sections.capacity_runs, data.capacity_runs),
        (sections.forecast_series, data.forecast_series),
    )
    for paths, items in grouped:
        for path, payload in zip(paths, _model_payloads(items)):
            members[path] = payload
    for path, report in zip(sections.reports, data.reports):
        members[path] = report_to_json(report)
    if sections.decisions is not None:
        members[sections.decisions] = _canonical_json(
            [record.model_dump(mode="json") for record in data.decision_records]
        )
    if sections.security_flows is not None:
        members[sections.security_flows] = _canonical_json(
            [flow.model_dump(mode="json") for flow in data.security_flows]
        )
    safe_settings = _safe_settings(data.settings)
    members[SETTINGS_MEMBER] = _canonical_json(safe_settings)

    checksums = {name: digest(payload) for name, payload in members.items()}
    manifest = BundleManifest(
        bundle_version=CURRENT_BUNDLE_VERSION,
        created_at=data.created_at,
        source_app_version=data.source_app_version,
        settings=safe_settings,
        limits=dict(data.limits),
        provenance=BundleProvenance(
            twin_fingerprint=twin_fingerprint(data.twin),
            source_fingerprints=data.source_fingerprints,
        ),
        sections=sections,
        members=checksums,
    )
    members[MANIFEST_MEMBER] = _canonical_json(manifest.model_dump(mode="json"))
    return build_archive(members)


def _validate_items(
    raw: Any, model: type[_T], *, label: str, cap: int
) -> tuple[_T, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise BundleFormatError(f"{label} must be a JSON array.")
    if len(raw) > cap:
        raise BundleLimitError(
            f"{label} has {len(raw)} items; the limit is {cap}."
        )
    result: list[_T] = []
    for item in raw:
        if not isinstance(item, dict):
            raise BundleFormatError(f"{label} contains a non-object item.")
        try:
            result.append(model.model_validate(item))
        except ValidationError as error:
            raise BundleFormatError(f"{label} failed schema validation.") from error
    return tuple(result)


def _section_items(
    members: Mapping[str, bytes], paths: Sequence[str], *, label: str, cap: int
) -> list[Any]:
    return [
        decode_json(members[path], label=f"{label} section")
        for path in paths
        if path in members
    ]


def _require_members(
    members: Mapping[str, bytes], paths: Sequence[str], *, label: str
) -> None:
    if any(path not in members for path in paths):
        raise BundleFormatError(f"{label} references a missing archive member.")


def read_bundle(payload: bytes) -> BundleData:
    """Restore a validated :class:`BundleData` from hostile input bytes."""
    members = read_archive(payload)
    raw_manifest = decode_json(members[MANIFEST_MEMBER], label="Bundle manifest")
    if not isinstance(raw_manifest, dict):
        raise BundleFormatError("Bundle manifest must be a JSON object.")
    migrated, migration_path = migrate_manifest(raw_manifest)
    migrated["migration_path"] = migration_path
    try:
        manifest = BundleManifest.model_validate(migrated)
    except ValidationError as error:
        raise BundleFormatError("Bundle manifest failed schema validation.") from error
    verify_checksums(members, manifest.members)

    sections = manifest.sections
    all_paths: list[str] = [sections.twin, *sections.snapshots, *sections.simulation_runs]
    all_paths.extend(
        [
            *sections.failure_sweeps,
            *sections.mode_comparisons,
            *sections.optimization_runs,
            *sections.capacity_runs,
            *sections.forecast_series,
            *sections.reports,
        ]
    )
    all_paths.extend(
        path for path in (sections.decisions, sections.security_flows) if path
    )
    _require_members(members, all_paths, label="Bundle manifest")

    try:
        twin = twin_from_json(
            members[sections.twin].decode("utf-8")
        )
    except UnicodeDecodeError as error:
        raise BundleFormatError("Twin section is not valid UTF-8.") from error
    except NetArchitectError as error:
        raise BundleFormatError("Twin section failed guarded validation.") from error

    recorded_fingerprint = manifest.provenance.twin_fingerprint
    if recorded_fingerprint and recorded_fingerprint != twin_fingerprint(twin):
        raise BundleFormatError("Twin fingerprint does not match the bundle manifest.")

    snapshots = _validate_items(
        _section_items(members, sections.snapshots, label="snapshots", cap=MAX_SNAPSHOTS),
        Snapshot,
        label="snapshots",
        cap=MAX_SNAPSHOTS,
    )
    if sum(item.size_bytes() for item in snapshots) > MAX_TWIN_SNAPSHOT_BYTES:
        raise BundleLimitError("Bundled snapshots exceed the snapshot byte limit.")

    reports: list[ReportDocument] = []
    if len(sections.reports) > _MAX_BUNDLE_REPORTS:
        raise BundleLimitError("Bundle contains too many reports.")
    for path in sections.reports:
        try:
            reports.append(report_from_json(members[path]))
        except NetArchitectError as error:
            raise BundleFormatError("Report section failed validation.") from error

    decision_items: Any = []
    if sections.decisions is not None:
        decision_items = decode_json(
            members[sections.decisions], label="decision log section"
        )
    flow_items: Any = []
    if sections.security_flows is not None:
        flow_items = decode_json(
            members[sections.security_flows], label="security flow section"
        )

    settings = manifest.settings
    if not isinstance(settings, dict):
        raise BundleFormatError("Bundle settings must be an object.")
    limits_map = manifest.limits
    if not isinstance(limits_map, dict):
        raise BundleFormatError("Bundle limits must be an object.")

    return BundleData(
        twin=twin,
        created_at=manifest.created_at,
        source_app_version=manifest.source_app_version,
        bundle_version=manifest.bundle_version,
        snapshots=snapshots,
        simulation_runs=_validate_items(
            _section_items(
                members, sections.simulation_runs, label="simulation runs", cap=MAX_SCENARIOS
            ),
            ScenarioRun,
            label="simulation runs",
            cap=MAX_SCENARIOS,
        ),
        failure_sweeps=_validate_items(
            _section_items(
                members, sections.failure_sweeps, label="failure sweeps", cap=MAX_SCENARIOS
            ),
            FailureSweepResult,
            label="failure sweeps",
            cap=MAX_SCENARIOS,
        ),
        mode_comparisons=_validate_items(
            _section_items(
                members,
                sections.mode_comparisons,
                label="mode comparisons",
                cap=MAX_SCENARIOS,
            ),
            RoutingModeComparison,
            label="mode comparisons",
            cap=MAX_SCENARIOS,
        ),
        optimization_runs=_validate_items(
            _section_items(
                members,
                sections.optimization_runs,
                label="optimization runs",
                cap=MAX_OPTIMIZATION_RUNS,
            ),
            OptimizationRun,
            label="optimization runs",
            cap=MAX_OPTIMIZATION_RUNS,
        ),
        capacity_runs=_validate_items(
            _section_items(
                members,
                sections.capacity_runs,
                label="capacity runs",
                cap=MAX_CAPACITY_RUNS,
            ),
            CapacityRun,
            label="capacity runs",
            cap=MAX_CAPACITY_RUNS,
        ),
        forecast_series=_validate_items(
            _section_items(
                members,
                sections.forecast_series,
                label="forecast series",
                cap=MAX_FORECAST_SERIES,
            ),
            TimeSeries,
            label="forecast series",
            cap=MAX_FORECAST_SERIES,
        ),
        reports=tuple(reports),
        decision_records=_validate_items(
            decision_items,
            DecisionRecord,
            label="decision log",
            cap=MAX_COPILOT_DECISIONS,
        ),
        security_flows=_validate_items(
            flow_items,
            FlowRequest,
            label="security flows",
            cap=MAX_SECURITY_FLOW_CHECKS,
        ),
        settings=dict(settings),
        limits=dict(limits_map),
        source_fingerprints=manifest.provenance.source_fingerprints,
    )


__all__ = [
    "build_bundle",
    "limits_snapshot",
    "read_bundle",
    "settings_snapshot",
]
