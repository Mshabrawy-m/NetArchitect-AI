"""Unit tests validating the sample fixtures under ``data/samples``."""

import json

from core.schemas.addressing import VlanPlan
from core.schemas.network import Topology
from core.schemas.optimization import OptimizationConfig
from core.schemas.organization import Organization
from core.schemas.requirements import NetworkRequirements
from core.schemas.routing import RouteEntry
from core.schemas.scenario import Scenario
from core.schemas.validation import ValidationReport


def _load_fixture(name: str) -> dict:
    """Read a sample fixture as a raw dict (path relative to the repo root)."""
    path = f"data/samples/{name}"
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _assert_meta(data: dict) -> None:
    """Every fixture carries the sample-data marker and a description."""
    assert data["_sample_data"] is True
    assert "description" in data


def test_sample_organization() -> None:
    data = _load_fixture("sample_organization.json")
    _assert_meta(data)
    Organization.model_validate(data)


def test_sample_topology() -> None:
    data = _load_fixture("sample_topology.json")
    _assert_meta(data)
    Topology.model_validate(data)


def test_sample_addressing() -> None:
    data = _load_fixture("sample_addressing.json")
    _assert_meta(data)
    VlanPlan.model_validate(data)


def test_sample_routing() -> None:
    data = _load_fixture("sample_routing.json")
    _assert_meta(data)
    RouteEntry.model_validate(data)


def test_sample_scenario() -> None:
    data = _load_fixture("sample_scenario.json")
    _assert_meta(data)
    Scenario.model_validate(data)


def test_sample_optimization() -> None:
    data = _load_fixture("sample_optimization.json")
    _assert_meta(data)
    OptimizationConfig.model_validate(data)


def test_sample_requirements() -> None:
    data = _load_fixture("sample_requirements.json")
    _assert_meta(data)
    NetworkRequirements.model_validate(data)


def test_sample_findings() -> None:
    data = _load_fixture("sample_findings.json")
    _assert_meta(data)
    ValidationReport.model_validate(data)
