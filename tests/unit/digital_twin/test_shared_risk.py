"""Additive shared-risk-group schema and compatibility tests."""

from __future__ import annotations

from digital_twin import SharedRiskGroup, from_json, to_json
from digital_twin.serialization import canonical_payload
from digital_twin.validation import validate_twin
from simulation.evaluator import twin_fingerprint
from tests.unit.simulation.helpers import line_twin


def _twin(groups: tuple[SharedRiskGroup, ...] = ()):
    return line_twin().model_copy(update={"shared_risk_groups": groups})


def test_empty_groups_are_absent_from_legacy_json_and_fingerprint() -> None:
    twin = _twin()
    payload = to_json(twin, indent=None)

    assert "shared_risk_groups" not in payload
    assert "shared_risk_groups" not in canonical_payload(twin)
    assert from_json(payload) == twin


def test_group_members_are_canonicalized_and_round_trip() -> None:
    group = SharedRiskGroup(
        id="shared-uplink",
        link_ids=("bc", "ab", "ab"),
        device_ids=("b",),
    )
    twin = _twin((group,))

    assert group.link_ids == ("ab", "bc")
    assert group.device_ids == ("b",)
    payload = to_json(twin, indent=None)
    assert "shared_risk_groups" in payload
    assert from_json(payload) == twin
    assert twin_fingerprint(twin) != twin_fingerprint(_twin())


def test_validation_flags_unknown_group_members() -> None:
    bad = _twin((SharedRiskGroup(id="bad", link_ids=("missing",)),))
    codes = {finding.code for finding in validate_twin(bad).findings}

    assert "twin_shared_risk_group_unknown_link" in codes
    assert validate_twin(bad).is_valid is False


def test_group_without_members_is_rejected_by_schema() -> None:
    from pydantic import ValidationError

    try:
        SharedRiskGroup(id="empty")
    except ValidationError:
        return
    raise AssertionError("An empty shared-risk group should not validate")
