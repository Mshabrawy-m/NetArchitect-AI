"""Tool registry contract, validation, and engine-parity tests."""

from __future__ import annotations

from pydantic import BaseModel

from agents.tools import (
    Tool,
    ToolRegistry,
    TopologyGenerateInput,
    registry_with_defaults,
)
from core.exceptions import (
    ToolInputError,
    ToolNotAllowedError,
    ToolNotFoundError,
    ToolOutputError,
)
from network.addressing import VlsmRequirement, allocate_vlsm
from network.topology import generate_ring


def test_registry_rejects_unknown_tool() -> None:
    registry = registry_with_defaults()

    try:
        registry.invoke("does_not_exist", {}, agent="test", allowed={"does_not_exist"})
    except ToolNotFoundError as error:
        assert "does_not_exist" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("unknown tool was accepted")


def test_registry_rejects_disallowed_tool() -> None:
    registry = registry_with_defaults()

    try:
        registry.invoke(
            "topology_generate",
            {"family": "ring"},
            agent="test",
            allowed=frozenset(),
        )
    except ToolNotAllowedError as error:
        assert "allowlist" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("disallowed tool was executed")


def test_registry_rejects_invalid_input() -> None:
    registry = registry_with_defaults()

    try:
        registry.invoke(
            "topology_generate",
            {"family": "not-a-family"},
            agent="test",
            allowed={"topology_generate"},
        )
    except ToolInputError as error:
        assert "family" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("invalid input was accepted")


def test_registry_rejects_invalid_output() -> None:
    class Input(BaseModel):
        value: int

    class Output(BaseModel):
        value: int

    def broken(_: Input) -> object:
        return object()

    registry = ToolRegistry(
        tools=(
            Tool(
                name="broken",
                description="Returns an unserializable object.",
                input_model=Input,
                output_model=Output,
                implementation=broken,
            ),
        )
    )

    try:
        registry.invoke("broken", {"value": 1}, agent="test", allowed={"broken"})
    except ToolOutputError as error:
        assert "Invalid output" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("invalid output was accepted")


def test_vlsm_tool_matches_direct_engine() -> None:
    registry = registry_with_defaults()
    requirements = [
        VlsmRequirement(name="eng", required_hosts=25),
        VlsmRequirement(name="sales", required_hosts=12),
    ]

    result = registry.invoke(
        "vlsm_allocate",
        {"parent": "10.0.0.0/24", "requirements": requirements},
        agent="test",
        allowed={"vlsm_allocate"},
    )
    expected = allocate_vlsm("10.0.0.0/24", requirements)
    assert result.model_dump() == expected.model_dump()


def test_topology_tool_matches_direct_engine() -> None:
    registry = registry_with_defaults()

    result = registry.invoke(
        "topology_generate",
        {"family": "ring", "name": "Plan ring", "site": "site-1", "params": {"node_count": 5}},
        agent="test",
        allowed={"topology_generate"},
    )
    expected = generate_ring(name="Plan ring", site="site-1", node_count=5)
    assert result.model_dump() == expected.model_dump()


def test_topology_tool_rejects_unknown_parameter() -> None:
    registry = registry_with_defaults()

    try:
        registry.invoke(
            "topology_generate",
            {"family": "ring", "params": {"not_a_parameter": 1}},
            agent="test",
            allowed={"topology_generate"},
        )
    except ToolInputError as error:
        assert "not_a_parameter" in str(error)
    else:  # pragma: no cover - defensive
        raise AssertionError("unknown generator parameter was accepted")


def test_registry_names_are_deterministic() -> None:
    registry = registry_with_defaults()
    assert registry.names() == tuple(sorted(registry.names()))
    assert "topology_generate" in registry.names()
    assert "security_analysis" in registry.names()
    assert isinstance(registry.get("topology_generate").input_model, type)
    assert TopologyGenerateInput(family="star").family == "star"
