"""B1 in-memory project bundle tests.

Every archive is built and read in memory. Hostile archives are constructed by
rewriting a valid bundle so the rejection path is exercised with otherwise
realistic payloads.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest

from config.settings import Settings
from core.exceptions import NetArchitectError
from core.schemas.scenario import ScenarioType
from digital_twin.serialization import from_json as twin_from_json
from digital_twin.serialization import to_json as twin_to_json
from digital_twin.snapshots import create_snapshot
from security.models import FlowRequest, Protocol
from services.bundle import (
    CURRENT_BUNDLE_VERSION,
    BundleChecksumError,
    BundleData,
    BundleFormatError,
    BundleLimitError,
    BundlePathError,
    BundleSourceFingerprints,
    BundleVersionError,
    build_bundle,
    limits_snapshot,
    read_bundle,
    settings_snapshot,
)
from services.bundle.codec import is_safe_member
from services.bundle.migrations import migrate_manifest
from services.bundle.models import MANIFEST_MEMBER, TWIN_MEMBER
from services.copilot.decisions import DecisionKind, DecisionRecord
from simulation import ScenarioRun
from simulation.evaluator import twin_fingerprint
from simulation.scenarios import run_scenario
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.simulation.helpers import make_scenario

CREATED_AT = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _bundle(twin: Any | None = None) -> BundleData:
    design = twin if twin is not None else make_twin()
    scenario_run: ScenarioRun = run_scenario(
        design,
        make_scenario(
            ScenarioType.single_link_failure,
            affected_links=["l1"],
        ),
    )
    return BundleData(
        twin=design,
        created_at=CREATED_AT,
        source_app_version="v1.0.0",
        bundle_version=CURRENT_BUNDLE_VERSION,
        snapshots=(
            create_snapshot(design, "baseline", captured_at=CREATED_AT),
        ),
        simulation_runs=(scenario_run,),
        decision_records=(
            DecisionRecord(
                kind=DecisionKind.snapshot_saved,
                subject_id="baseline",
                title="Saved baseline",
                page="Digital Twin",
                source_fingerprint=twin_fingerprint(design),
                created_at=CREATED_AT,
            ),
        ),
        security_flows=(
            FlowRequest(
                id="flow-1",
                source_device_id="r1",
                destination_device_id="sw1",
                protocol=Protocol.tcp,
                port=443,
            ),
        ),
        settings={"APP_NAME": "NetArchitect AI", "APP_VERSION": "v1.0.0"},
        limits=limits_snapshot(),
        source_fingerprints=BundleSourceFingerprints(
            optimization_runs={"run-key": twin_fingerprint(design)},
        ),
    )


def _members(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _rewrite(payload: bytes, operations: dict[str, bytes | None]) -> bytes:
    members = _members(payload)
    for name, value in operations.items():
        if value is None:
            members.pop(name, None)
        else:
            members[name] = value
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in sorted(members):
            archive.writestr(name, members[name])
    return buffer.getvalue()


def _manifest(payload: bytes) -> dict[str, Any]:
    members = _members(payload)
    return json.loads(members[MANIFEST_MEMBER].decode("utf-8"))


def test_full_round_trip_is_exact_and_deterministic() -> None:
    data = _bundle()
    first = build_bundle(data)
    assert build_bundle(data) == first
    restored = read_bundle(first)
    assert restored == data
    assert twin_to_json(restored.twin) == twin_to_json(data.twin)
    assert restored.source_fingerprints.optimization_runs == (
        data.source_fingerprints.optimization_runs
    )
    assert read_bundle(build_bundle(restored)) == restored


def test_twin_section_uses_the_legacy_twin_codec() -> None:
    data = _bundle()
    payload = build_bundle(data)
    assert _members(payload)[TWIN_MEMBER].decode("utf-8").strip() == twin_to_json(
        data.twin, indent=None
    ).strip()
    assert twin_from_json(_members(payload)[TWIN_MEMBER].decode("utf-8")) == data.twin


def test_zero_case_empty_topology_round_trips() -> None:
    empty = make_twin(topology=make_twin().topology.model_copy(update={"devices": [], "links": []}))
    data = BundleData(
        twin=empty,
        created_at=CREATED_AT,
        source_app_version="v1.0.0",
        bundle_version=CURRENT_BUNDLE_VERSION,
    )
    restored = read_bundle(build_bundle(data))
    assert list(restored.twin.topology.devices) == []
    assert restored.snapshots == ()
    assert restored.decision_records == ()


def test_settings_snapshot_excludes_every_secret_token() -> None:
    settings = Settings(
        GROQ_API_KEY="sk-not-a-real-key",
        GROQ_BASE_URL="https://example.invalid",
    )
    snapshot = settings_snapshot(settings)
    assert snapshot["GROQ_BASE_URL"] == "https://example.invalid"
    assert "GROQ_API_KEY" not in snapshot
    assert all(
        token not in key.upper()
        for key in snapshot
        for token in ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
    )


def test_member_allowlist_rejects_traversal_and_specials() -> None:
    safe = {
        "manifest.json",
        "twin.json",
        "decisions.json",
        "security/flows.json",
        "settings.json",
        "snapshots/0000.json",
        "runs/simulation/0000.json",
    }
    assert all(is_safe_member(name) for name in safe)
    unsafe = (
        "../evil.json",
        "/abs.json",
        "C:\\evil.json",
        "runs//0000.json",
        "runs/./0000.json",
        "runs/../evil.json",
        "snapshots/-1.json",
        "snapshots/0000.txt",
        "unknown/0000.json",
        "",
    )
    assert not any(is_safe_member(name) for name in unsafe)


def test_checksum_mismatch_is_rejected() -> None:
    payload = build_bundle(_bundle())
    members = _members(payload)
    manifest = json.loads(members[MANIFEST_MEMBER].decode("utf-8"))
    manifest["members"][TWIN_MEMBER] = "0" * 64
    hostile = _rewrite(
        payload,
        {MANIFEST_MEMBER: json.dumps(manifest, sort_keys=True).encode("utf-8")},
    )
    with pytest.raises(BundleChecksumError):
        read_bundle(hostile)


def test_injected_extra_member_is_rejected() -> None:
    payload = build_bundle(_bundle())
    hostile = _rewrite(payload, {"snapshots/9999.json": b"{}"})
    with pytest.raises(BundleChecksumError):
        read_bundle(hostile)


def test_traversal_member_is_rejected_before_checksums() -> None:
    payload = build_bundle(_bundle())
    hostile = _rewrite(payload, {"../evil.json": b"{}"})
    with pytest.raises(BundlePathError):
        read_bundle(hostile)


def test_missing_manifest_and_corrupt_zip_are_typed() -> None:
    payload = build_bundle(_bundle())
    with pytest.raises(BundleFormatError):
        read_bundle(_rewrite(payload, {MANIFEST_MEMBER: None}))
    with pytest.raises(BundleFormatError):
        read_bundle(b"not a zip")
    with pytest.raises(BundleLimitError):
        read_bundle(b"")


def test_malformed_section_json_is_rejected() -> None:
    payload = build_bundle(_bundle())
    hostile = _rewrite(payload, {TWIN_MEMBER: b"{not json"})
    with pytest.raises((BundleFormatError, NetArchitectError)):
        read_bundle(hostile)


@pytest.mark.parametrize("version", [0, CURRENT_BUNDLE_VERSION + 1])
def test_bad_bundle_versions_are_rejected(version: int) -> None:
    payload = build_bundle(_bundle())
    manifest = _manifest(payload)
    manifest["bundle_version"] = version
    hostile = _rewrite(
        payload,
        {MANIFEST_MEMBER: json.dumps(manifest, sort_keys=True).encode("utf-8")},
    )
    with pytest.raises(BundleVersionError):
        read_bundle(hostile)


def test_v1_to_v2_migration_preserves_provenance_and_drops_secrets() -> None:
    legacy: dict[str, Any] = {
        "bundle_version": 1,
        "kind": "netarchitect-project-bundle",
        "created_at": CREATED_AT.isoformat(),
        "source_app_version": "v0",
        "settings": {"APP_NAME": "NetArchitect AI", "GROQ_API_KEY": "secret"},
        "sections": {"twin": TWIN_MEMBER, "decision_log": "decisions.json"},
    }
    migrated, path = migrate_manifest(legacy)
    assert path == ("v1_to_v2",)
    assert migrated["bundle_version"] == CURRENT_BUNDLE_VERSION
    assert migrated["sections"]["decisions"] == "decisions.json"
    assert "decision_log" not in migrated["sections"]
    assert "GROQ_API_KEY" not in migrated["settings"]
    assert migrated["provenance"]["twin_fingerprint"] == ""
    assert legacy["bundle_version"] == 1


def test_old_bundle_without_checksum_map_still_imports() -> None:
    payload = build_bundle(_bundle())
    manifest = _manifest(payload)
    manifest["bundle_version"] = 1
    manifest["members"] = {}
    hostile = _rewrite(
        payload,
        {MANIFEST_MEMBER: json.dumps(manifest, sort_keys=True).encode("utf-8")},
    )
    restored = read_bundle(hostile)
    assert restored.bundle_version == CURRENT_BUNDLE_VERSION
    assert restored.twin == _bundle().twin


def test_bundle_byte_cap_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.bundle import codec

    monkeypatch.setattr(codec, "MAX_BUNDLE_BYTES", 8)
    with pytest.raises(BundleLimitError):
        read_bundle(build_bundle(_bundle()))


def test_hostile_json_depth_and_numeric_values_are_rejected() -> None:
    payload = build_bundle(_bundle())
    nested: Any = 0
    for _ in range(80):
        nested = [nested]
    twin_payload = json.dumps(nested).encode("utf-8")
    manifest = _manifest(payload)
    manifest["members"][TWIN_MEMBER] = hashlib.sha256(twin_payload).hexdigest()
    hostile = _rewrite(
        payload,
        {
            TWIN_MEMBER: twin_payload,
            MANIFEST_MEMBER: json.dumps(manifest, sort_keys=True).encode("utf-8"),
        },
    )
    with pytest.raises(BundleFormatError):
        read_bundle(hostile)
