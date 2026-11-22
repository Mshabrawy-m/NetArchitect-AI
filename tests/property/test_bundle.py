"""Bounded round-trip and tamper invariants for in-memory project bundles."""

from __future__ import annotations

import io
import json
import zipfile

from hypothesis import given
from hypothesis import strategies as st

from services.bundle import (
    CURRENT_BUNDLE_VERSION,
    BundleData,
    build_bundle,
    read_bundle,
)
from services.bundle.models import MANIFEST_MEMBER, TWIN_MEMBER
from services.bundle.service import limits_snapshot
from simulation.evaluator import twin_fingerprint
from tests.property.config import BOUNDED
from tests.unit.digital_twin.helpers import make_twin
from tests.unit.simulation.helpers import make_link, make_topology

_NAME = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_",
    min_size=1,
    max_size=64,
)


@BOUNDED
@given(name=_NAME, capacity=st.floats(10.0, 1000.0, allow_nan=False), directed=st.booleans())
def test_bundle_round_trip_is_exact_for_varied_twins(
    name: str, capacity: float, directed: bool
) -> None:
    topology = make_topology(
        ["a", "b"], [make_link("ab", "a", "b", capacity_mbps=capacity, directed=directed)]
    )
    twin = make_twin(
        topology=topology,
        metadata=make_twin().metadata.model_copy(update={"name": name}),
    )
    data = BundleData(
        twin=twin,
        created_at=twin.metadata.created_at,
        source_app_version="v1.0.0",
        bundle_version=CURRENT_BUNDLE_VERSION,
        limits=limits_snapshot(),
    )
    payload = build_bundle(data)
    assert build_bundle(data) == payload
    restored = read_bundle(payload)
    assert restored.twin == twin
    assert twin_fingerprint(restored.twin) == twin_fingerprint(twin)
    assert build_bundle(restored) == payload


@BOUNDED
@given(name=_NAME)
def test_manifest_checksum_detects_any_single_member_tamper(name: str) -> None:
    twin = make_twin(
        metadata=make_twin().metadata.model_copy(update={"name": name}),
    )
    payload = build_bundle(
        BundleData(
            twin=twin,
            created_at=twin.metadata.created_at,
            source_app_version="v1.0.0",
            bundle_version=CURRENT_BUNDLE_VERSION,
        )
    )
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        members = {item: archive.read(item) for item in archive.namelist()}
    members[TWIN_MEMBER] = members[TWIN_MEMBER].replace(
        name.encode("utf-8"), (name + "-tampered").encode("utf-8"), 1
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for item in sorted(members):
            archive.writestr(item, members[item])
    restored_bytes = buffer.getvalue()

    from services.bundle import BundleChecksumError

    try:
        read_bundle(restored_bytes)
    except BundleChecksumError:
        return
    raise AssertionError("Tampered twin member was accepted without a checksum failure")


@BOUNDED
@given(secret=_NAME)
def test_manifest_never_records_a_secret_setting(secret: str) -> None:
    payload = build_bundle(
        BundleData(
            twin=make_twin(),
            created_at=make_twin().metadata.created_at,
            source_app_version="v1.0.0",
            bundle_version=CURRENT_BUNDLE_VERSION,
            settings={"APP_NAME": "NetArchitect AI", "GROQ_API_KEY": "sk-" + secret},
        )
    )
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        members = {item: archive.read(item) for item in archive.namelist()}
    manifest = json.loads(members[MANIFEST_MEMBER].decode("utf-8"))
    settings_member = json.loads(members["settings.json"].decode("utf-8"))
    assert "GROQ_API_KEY" not in manifest["settings"]
    assert "GROQ_API_KEY" not in settings_member
    raw = b"".join(members.values()).decode("utf-8", errors="replace")
    assert ("sk-" + secret) not in raw
