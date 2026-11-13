"""Validated what-if scenarios over an unmodified baseline twin.

A scenario is translated into an explicit :class:`ScenarioPlan` before any
change is applied. The plan is validated against the baseline twin, so a
malformed scenario raises :class:`ScenarioValidationError` with an actionable
message instead of partially changing the model.

Each run evaluates the baseline and the scenario state with the same
assumptions and one shared runtime budget. :class:`ScenarioRun` records the
scenario inputs, assumptions, thresholds, both twin references (including
SHA-256 fingerprints), both network states, and a deterministic comparison.
No timestamp or elapsed time is stored, so identical inputs produce identical
results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config.limits import (
    MAX_DEMANDS,
    MAX_EDGES,
    MAX_NODES,
    MAX_SCENARIO_ELEMENTS,
)
from core.exceptions import ScenarioValidationError
from core.schemas.network import Device, Link
from core.schemas.routing import TrafficDemand
from core.schemas.scenario import Scenario, ScenarioType
from digital_twin import (
    DigitalTwin,
    add_demand,
    apply_failure,
    set_demands,
    set_link_capacity,
    set_link_cost,
    set_topology,
)
from network.topology import add_device, add_link

from .evaluator import (
    _check_deadline,
    _resolve_deadline,
    evaluate,
    twin_reference,
)
from .models import (
    MODEL_NOTE,
    CongestionLevel,
    CongestionThresholds,
    NetworkState,
    SimulationAssumptions,
    TwinReference,
)
from .tables import format_path


class LinkChangeKind(str, Enum):
    """How one link's modeled state differs after the scenario."""

    added = "added"
    removed = "removed"
    level_changed = "level_changed"


class PathChange(BaseModel):
    """A demand whose selected path changed between the two states."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Demand name.")
    baseline_path: str = Field(description="Baseline path, or an unserved reason.")
    scenario_path: str = Field(description="Scenario path, or an unserved reason.")
    baseline_served: bool = Field(description="Whether the demand was served before.")
    scenario_served: bool = Field(description="Whether the demand is served after.")


class LinkChange(BaseModel):
    """A link added, removed, or moved to another congestion band."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: str = Field(description="Physical link id.")
    kind: LinkChangeKind = Field(description="Kind of change.")
    baseline_utilization_percent: float | None = Field(
        default=None,
        ge=0,
        description="Baseline utilization, or None when the link did not exist.",
    )
    scenario_utilization_percent: float | None = Field(
        default=None,
        ge=0,
        description="Scenario utilization, or None when the link was removed.",
    )
    baseline_level: CongestionLevel | None = Field(
        default=None,
        description="Baseline congestion band, if the link existed.",
    )
    scenario_level: CongestionLevel | None = Field(
        default=None,
        description="Scenario congestion band, if the link exists.",
    )


class ScenarioComparison(BaseModel):
    """Deterministic before/after comparison for one scenario run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_served_demand_count: int = Field(ge=0)
    scenario_served_demand_count: int = Field(ge=0)
    baseline_served_demand_ratio: float = Field(ge=0, le=1)
    scenario_served_demand_ratio: float = Field(ge=0, le=1)
    newly_unserved_demands: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Demands served at baseline but unserved in the scenario.",
    )
    recovered_demands: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Demands unserved at baseline but served in the scenario.",
    )
    path_changes: tuple[PathChange, ...] = Field(
        default_factory=tuple,
        description="Demands whose selected path or served status changed.",
    )
    link_changes: tuple[LinkChange, ...] = Field(
        default_factory=tuple,
        description="Links added, removed, or moved to another band.",
    )
    new_congested_links: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Links that moved from normal/absent to warning or worse.",
    )
    relieved_links: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Links that moved from warning or worse to normal/absent.",
    )
    max_utilization_delta_percent: float = Field(
        description="Scenario minus baseline maximum utilization, in percentage points.",
    )
    congested_link_delta: int = Field(
        description="Scenario minus baseline congested-link count.",
    )
    overloaded_link_delta: int = Field(
        description="Scenario minus baseline overloaded-link count.",
    )
    disconnected_device_delta: int = Field(
        description="Scenario minus baseline disconnected-device count.",
    )
    recovery_available: bool = Field(
        description=(
            "Whether every demand served at baseline is still served in the "
            "scenario."
        ),
    )
    recovery_note: str = Field(description="Plain-language recovery outcome.")
    summary: str = Field(description="Deterministic one-line outcome summary.")


class ScenarioRun(BaseModel):
    """One reproducible scenario result with full traceability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario: Scenario = Field(description="Validated scenario inputs.")
    baseline_twin: TwinReference = Field(
        description="Baseline twin name, version, and fingerprint.",
    )
    scenario_twin: TwinReference = Field(
        description="Scenario twin name, version, and fingerprint.",
    )
    assumptions: SimulationAssumptions = Field(description="Assumptions used.")
    thresholds: CongestionThresholds = Field(description="Thresholds used.")
    baseline_state: NetworkState = Field(description="Baseline modeled state.")
    scenario_state: NetworkState = Field(description="Scenario modeled state.")
    comparison: ScenarioComparison = Field(description="Before/after comparison.")
    warnings: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Non-fatal warnings gathered from both evaluations.",
    )
    model_note: str = Field(default=MODEL_NOTE, description="Model scope reminder.")


@dataclass(frozen=True)
class ExpansionPlan:
    """Validated entities to add for an expansion scenario."""

    devices: tuple[Device, ...] = ()
    links: tuple[Link, ...] = ()
    demands: tuple[TrafficDemand, ...] = ()


@dataclass(frozen=True)
class ScenarioPlan:
    """Validated, typed changes to apply to a copy of the baseline twin."""

    down_devices: tuple[str, ...] = ()
    down_links: tuple[str, ...] = ()
    capacity_updates: tuple[tuple[str, float], ...] = ()
    cost_updates: tuple[tuple[str, float], ...] = ()
    demand_factors: tuple[tuple[str, float], ...] = ()
    expansion: ExpansionPlan = field(default_factory=ExpansionPlan)


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _finite_positive(value: object, label: str, issues: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.append(f"{label} must be a number")
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        issues.append(f"{label} must be a positive finite number")
        return None
    return number


def _one_parameter(
    parameters: dict[str, object],
    names: tuple[str, ...],
    label: str,
    issues: list[str],
) -> tuple[str, object] | None:
    present = [(name, parameters[name]) for name in names if name in parameters]
    if len(present) != 1:
        joined = ", ".join(repr(name) for name in names)
        issues.append(f"{label} requires exactly one of: {joined}")
        return None
    return present[0]


def _validate_affected(
    scenario: Scenario,
    *,
    known_links: set[str],
    known_devices: set[str],
    issues: list[str],
) -> None:
    link_duplicates = _duplicates(scenario.affected_links)
    if link_duplicates:
        issues.append("Duplicate affected link id(s): " + ", ".join(link_duplicates))
    device_duplicates = _duplicates(scenario.affected_nodes)
    if device_duplicates:
        issues.append(
            "Duplicate affected device id(s): " + ", ".join(device_duplicates)
        )
    unknown_links = sorted(set(scenario.affected_links) - known_links)
    if unknown_links:
        issues.append("Unknown affected link(s): " + ", ".join(unknown_links))
    unknown_devices = sorted(set(scenario.affected_nodes) - known_devices)
    if unknown_devices:
        issues.append("Unknown affected device(s): " + ", ".join(unknown_devices))


def _element_count(scenario: Scenario) -> int:
    count = len(scenario.affected_links) + len(scenario.affected_nodes)
    parameters = scenario.parameters
    for key in ("costs", "demand_factors"):
        value = parameters.get(key)
        if isinstance(value, dict):
            count += len(value)
    names = parameters.get("demand_names")
    if isinstance(names, list):
        count += len(names)
    expansion = parameters.get("expansion")
    if isinstance(expansion, dict):
        for key in ("devices", "links", "demands"):
            value = expansion.get(key)
            if isinstance(value, list):
                count += len(value)
    return count


def _parse_expansion(
    scenario: Scenario,
    *,
    known_devices: set[str],
    known_links: set[str],
    known_demands: set[str],
    issues: list[str],
) -> ExpansionPlan:
    raw = scenario.parameters.get("expansion")
    if not isinstance(raw, dict):
        issues.append("Expansion scenarios require a parameters['expansion'] object.")
        return ExpansionPlan()
    devices: list[Device] = []
    links: list[Link] = []
    demands: list[TrafficDemand] = []
    try:
        for value in raw.get("devices", []):
            devices.append(Device.model_validate(value))
        for value in raw.get("links", []):
            links.append(Link.model_validate(value))
        for value in raw.get("demands", []):
            demands.append(TrafficDemand.model_validate(value))
    except (ValidationError, TypeError) as error:
        issues.append(f"Expansion entity is invalid: {error}")
        return ExpansionPlan()
    if not devices and not links and not demands:
        issues.append("Expansion must add at least one device, link, or demand.")

    new_device_ids = [device.id for device in devices]
    duplicates = _duplicates(new_device_ids)
    if duplicates:
        issues.append("Duplicate expansion device id(s): " + ", ".join(duplicates))
    clashes = sorted(set(new_device_ids) & known_devices)
    if clashes:
        issues.append("Expansion device id(s) already exist: " + ", ".join(clashes))
    new_link_ids = [link.id for link in links]
    duplicates = _duplicates(new_link_ids)
    if duplicates:
        issues.append("Duplicate expansion link id(s): " + ", ".join(duplicates))
    clashes = sorted(set(new_link_ids) & known_links)
    if clashes:
        issues.append("Expansion link id(s) already exist: " + ", ".join(clashes))
    new_demand_names = [demand.name for demand in demands]
    duplicates = _duplicates(new_demand_names)
    if duplicates:
        issues.append("Duplicate expansion demand name(s): " + ", ".join(duplicates))
    clashes = sorted(set(new_demand_names) & known_demands)
    if clashes:
        issues.append("Expansion demand name(s) already exist: " + ", ".join(clashes))

    all_devices = known_devices | set(new_device_ids)
    for link in links:
        missing = [endpoint for endpoint in link.endpoints if endpoint not in all_devices]
        if missing:
            issues.append(
                f"Expansion link {link.id!r} references unknown device(s): "
                + ", ".join(sorted(set(missing)))
            )
    for demand in demands:
        missing = [
            endpoint
            for endpoint in (demand.source, demand.destination)
            if endpoint not in all_devices
        ]
        if missing:
            issues.append(
                f"Expansion demand {demand.name!r} references unknown device(s): "
                + ", ".join(sorted(set(missing)))
            )

    if len(known_devices) + len(devices) > MAX_NODES:
        issues.append(
            f"Expansion would exceed the {MAX_NODES}-device limit "
            f"({len(known_devices) + len(devices)} devices)."
        )
    if len(known_links) + len(links) > MAX_EDGES:
        issues.append(
            f"Expansion would exceed the {MAX_EDGES}-link limit "
            f"({len(known_links) + len(links)} links)."
        )
    if len(known_demands) + len(demands) > MAX_DEMANDS:
        issues.append(
            f"Expansion would exceed the {MAX_DEMANDS}-demand limit "
            f"({len(known_demands) + len(demands)} demands)."
        )
    return ExpansionPlan(
        devices=tuple(devices),
        links=tuple(links),
        demands=tuple(demands),
    )


def _plan_scenario(baseline_twin: DigitalTwin, scenario: Scenario) -> ScenarioPlan:
    """Validate ``scenario`` against ``baseline_twin`` and return its plan."""
    issues: list[str] = []
    if not scenario.id.strip():
        issues.append("Scenario id must not be empty.")
    if not scenario.name.strip():
        issues.append("Scenario name must not be empty.")
    count = _element_count(scenario)
    if count > MAX_SCENARIO_ELEMENTS:
        issues.append(
            f"Scenario names or adds {count} elements; the limit is "
            f"{MAX_SCENARIO_ELEMENTS}."
        )

    known_links = {link.id for link in baseline_twin.topology.links}
    known_devices = {device.id for device in baseline_twin.topology.devices}
    known_demands = {demand.name for demand in baseline_twin.demands}
    _validate_affected(
        scenario,
        known_links=known_links,
        known_devices=known_devices,
        issues=issues,
    )
    parameters = scenario.parameters
    kind = scenario.type

    down_links: tuple[str, ...] = ()
    down_devices: tuple[str, ...] = ()
    capacity_updates: tuple[tuple[str, float], ...] = ()
    cost_updates: tuple[tuple[str, float], ...] = ()
    demand_factors: tuple[tuple[str, float], ...] = ()
    expansion = ExpansionPlan()
    links_by_id = {link.id: link for link in baseline_twin.topology.links}

    if kind in {ScenarioType.single_link_failure, ScenarioType.multiple_link_failures}:
        if scenario.affected_nodes:
            issues.append("Link-failure scenarios must not name affected devices.")
        minimum = 1 if kind is ScenarioType.single_link_failure else 2
        if kind is ScenarioType.single_link_failure and len(scenario.affected_links) != 1:
            issues.append("A single-link failure requires exactly one affected link.")
        if (
            kind is ScenarioType.multiple_link_failures
            and len(scenario.affected_links) < minimum
        ):
            issues.append("Multiple-link failures require at least two affected links.")
        down_links = tuple(scenario.affected_links)

    elif kind is ScenarioType.node_failure:
        if scenario.affected_links:
            issues.append("Node-failure scenarios must not name affected links.")
        if len(scenario.affected_nodes) != 1:
            issues.append("A node failure requires exactly one affected device.")
        down_devices = tuple(scenario.affected_nodes)

    elif kind is ScenarioType.bandwidth_reduction:
        if scenario.affected_nodes:
            issues.append("Bandwidth reduction must not name affected devices.")
        if not scenario.affected_links:
            issues.append("Bandwidth reduction requires at least one affected link.")
        choice = _one_parameter(
            parameters,
            ("percent", "reduction_percent", "mbps", "reduction_mbps"),
            "Bandwidth reduction",
            issues,
        )
        if choice is not None:
            name, raw_value = choice
            value = _finite_positive(raw_value, f"Bandwidth reduction {name}", issues)
            if value is not None:
                is_percent = name in {"percent", "reduction_percent"}
                if is_percent and value >= 100:
                    issues.append(
                        "Bandwidth reduction percent must be below 100 so capacity "
                        "stays positive."
                    )
                for link_id in scenario.affected_links:
                    link = links_by_id.get(link_id)
                    if link is None:
                        continue
                    new_capacity = (
                        link.capacity_mbps * (1.0 - value / 100.0)
                        if is_percent
                        else link.capacity_mbps - value
                    )
                    if new_capacity <= 0:
                        issues.append(
                            f"Bandwidth reduction leaves link {link_id!r} with no "
                            "positive capacity."
                        )
                capacity_updates = tuple(
                    (
                        link_id,
                        (
                            links_by_id[link_id].capacity_mbps
                            * (1.0 - value / 100.0)
                            if is_percent
                            else links_by_id[link_id].capacity_mbps - value
                        ),
                    )
                    for link_id in scenario.affected_links
                    if link_id in links_by_id
                )

    elif kind is ScenarioType.increased_traffic_demand:
        if scenario.affected_links or scenario.affected_nodes:
            issues.append(
                "Traffic-increase scenarios use demand names, not affected "
                "links/devices."
            )
        choice = _one_parameter(
            parameters,
            ("factor", "demand_factors"),
            "Traffic increase",
            issues,
        )
        if choice is not None:
            name, raw_value = choice
            if name == "factor":
                factor = _finite_positive(raw_value, "Traffic factor", issues)
                names_raw = parameters.get("demand_names")
                names: list[str] = []
                if names_raw is not None:
                    if not isinstance(names_raw, list) or not all(
                        isinstance(item, str) for item in names_raw
                    ):
                        issues.append("demand_names must be a list of strings.")
                    else:
                        duplicates = _duplicates(names_raw)
                        if duplicates:
                            issues.append(
                                "Duplicate demand names: " + ", ".join(duplicates)
                            )
                        unknown = sorted(set(names_raw) - known_demands)
                        if unknown:
                            issues.append(
                                "Unknown demand name(s): " + ", ".join(unknown)
                            )
                        names = list(names_raw)
                if factor is not None:
                    targets = names or [demand.name for demand in baseline_twin.demands]
                    if not targets:
                        issues.append("The twin has no traffic demands to increase.")
                    demand_factors = tuple((item, factor) for item in targets)
            else:
                if not isinstance(raw_value, dict) or not raw_value:
                    issues.append("demand_factors must be a non-empty object.")
                else:
                    factors: list[tuple[str, float]] = []
                    for demand_name, factor_raw in raw_value.items():
                        if not isinstance(demand_name, str):
                            issues.append("demand_factors keys must be strings.")
                            continue
                        if demand_name not in known_demands:
                            issues.append(
                                f"Unknown demand name in demand_factors: "
                                f"{demand_name!r}"
                            )
                            continue
                        factor = _finite_positive(
                            factor_raw,
                            f"Traffic factor for {demand_name!r}",
                            issues,
                        )
                        if factor is not None:
                            factors.append((demand_name, factor))
                    demand_factors = tuple(factors)

    elif kind in {ScenarioType.new_department, ScenarioType.network_expansion}:
        if scenario.affected_links or scenario.affected_nodes:
            issues.append(
                "Expansion scenarios describe added entities in "
                "parameters['expansion'], not affected links/devices."
            )
        expansion = _parse_expansion(
            scenario,
            known_devices=known_devices,
            known_links=known_links,
            known_demands=known_demands,
            issues=issues,
        )

    elif kind is ScenarioType.routing_cost_change:
        if scenario.affected_nodes:
            issues.append("Routing-cost change must not name affected devices.")
        choice = _one_parameter(
            parameters,
            ("cost", "cost_factor", "costs"),
            "Routing-cost change",
            issues,
        )
        if choice is not None:
            name, raw_value = choice
            if name == "costs":
                if not isinstance(raw_value, dict) or not raw_value:
                    issues.append("costs must be a non-empty object of link id -> cost.")
                else:
                    unknown = sorted(set(raw_value) - known_links)
                    if unknown:
                        issues.append("Unknown link(s) in costs: " + ", ".join(unknown))
                    if scenario.affected_links and set(scenario.affected_links) != set(
                        raw_value
                    ):
                        issues.append(
                            "costs keys must match affected_links when both are given."
                        )
                    updates: list[tuple[str, float]] = []
                    for link_id, cost_raw in raw_value.items():
                        if not isinstance(link_id, str):
                            issues.append("costs keys must be link id strings.")
                            continue
                        cost = _finite_positive(
                            cost_raw, f"Routing cost for {link_id!r}", issues
                        )
                        if cost is not None:
                            updates.append((link_id, cost))
                    cost_updates = tuple(updates)
            else:
                if not scenario.affected_links:
                    issues.append(
                        "Routing-cost change requires at least one affected link."
                    )
                value = _finite_positive(raw_value, f"Routing {name}", issues)
                if value is not None:
                    updates = []
                    for link_id in scenario.affected_links:
                        link = links_by_id.get(link_id)
                        if link is None:
                            continue
                        new_cost = (
                            link.cost * value if name == "cost_factor" else value
                        )
                        updates.append((link_id, new_cost))
                    cost_updates = tuple(updates)

    elif kind is ScenarioType.redundancy_recovery_test:
        if not scenario.affected_links and not scenario.affected_nodes:
            issues.append(
                "A redundancy/recovery test requires at least one affected link "
                "or device."
            )
        down_links = tuple(scenario.affected_links)
        down_devices = tuple(scenario.affected_nodes)

    else:  # pragma: no cover - ScenarioType is exhaustive
        issues.append(f"Unsupported scenario type: {scenario.type!r}")

    if issues:
        raise ScenarioValidationError(
            f"Scenario {scenario.id!r} is invalid: " + "; ".join(issues)
        )
    return ScenarioPlan(
        down_devices=down_devices,
        down_links=down_links,
        capacity_updates=capacity_updates,
        cost_updates=cost_updates,
        demand_factors=demand_factors,
        expansion=expansion,
    )


def validate_scenario(baseline_twin: DigitalTwin, scenario: Scenario) -> None:
    """Raise :class:`ScenarioValidationError` if the scenario is invalid."""
    _plan_scenario(baseline_twin, scenario)


def _apply_plan(baseline_twin: DigitalTwin, plan: ScenarioPlan) -> DigitalTwin:
    twin = apply_failure(
        baseline_twin,
        device_ids=plan.down_devices,
        link_ids=plan.down_links,
    )
    for link_id, capacity in plan.capacity_updates:
        twin = set_link_capacity(twin, link_id, capacity)
    for link_id, cost in plan.cost_updates:
        twin = set_link_cost(twin, link_id, cost)
    if plan.demand_factors:
        factors = dict(plan.demand_factors)
        twin = set_demands(
            twin,
            tuple(
                demand.model_copy(
                    update={"bandwidth_mbps": demand.bandwidth_mbps * factors[demand.name]}
                )
                if demand.name in factors
                else demand
                for demand in twin.demands
            ),
        )
    if plan.expansion.devices or plan.expansion.links or plan.expansion.demands:
        topology = twin.topology
        for device in plan.expansion.devices:
            topology = add_device(topology, device)
        for link in plan.expansion.links:
            topology = add_link(topology, link)
        twin = set_topology(twin, topology)
        for demand in plan.expansion.demands:
            twin = add_demand(twin, demand)
    return twin


def _compare(
    baseline_state: NetworkState,
    scenario_state: NetworkState,
) -> ScenarioComparison:
    baseline_demands = {demand.name: demand for demand in baseline_state.demands}
    scenario_demands = {demand.name: demand for demand in scenario_state.demands}
    ordered_names = [
        *(demand.name for demand in scenario_state.demands),
        *(
            demand.name
            for demand in baseline_state.demands
            if demand.name not in scenario_demands
        ),
    ]
    newly_unserved: list[str] = []
    recovered: list[str] = []
    path_changes: list[PathChange] = []
    seen: set[str] = set()
    for name in ordered_names:
        if name in seen:
            continue
        seen.add(name)
        baseline = baseline_demands.get(name)
        scenario = scenario_demands.get(name)
        baseline_served = bool(baseline and baseline.served)
        scenario_served = bool(scenario and scenario.served)
        if baseline_served and not scenario_served:
            newly_unserved.append(name)
        if not baseline_served and scenario_served:
            recovered.append(name)
        baseline_path = format_path(baseline) if baseline else "not present"
        scenario_path = format_path(scenario) if scenario else "not present"
        if baseline_path != scenario_path:
            path_changes.append(
                PathChange(
                    name=name,
                    baseline_path=baseline_path,
                    scenario_path=scenario_path,
                    baseline_served=baseline_served,
                    scenario_served=scenario_served,
                )
            )

    baseline_links = {link.link_id: link for link in baseline_state.links}
    scenario_links = {link.link_id: link for link in scenario_state.links}
    ordered_links = [
        *(link.link_id for link in scenario_state.links),
        *(
            link.link_id
            for link in baseline_state.links
            if link.link_id not in scenario_links
        ),
    ]
    link_changes: list[LinkChange] = []
    new_congested: list[str] = []
    relieved: list[str] = []
    for link_id in ordered_links:
        baseline_link = baseline_links.get(link_id)
        scenario_link = scenario_links.get(link_id)
        baseline_level = baseline_link.level if baseline_link else None
        scenario_level = scenario_link.level if scenario_link else None
        baseline_congested = (
            baseline_level is not None and baseline_level is not CongestionLevel.normal
        )
        scenario_congested = (
            scenario_level is not None and scenario_level is not CongestionLevel.normal
        )
        if scenario_congested and not baseline_congested:
            new_congested.append(link_id)
        if baseline_congested and not scenario_congested:
            relieved.append(link_id)
        if baseline_link is None:
            kind = LinkChangeKind.added
        elif scenario_link is None:
            kind = LinkChangeKind.removed
        elif baseline_level is not scenario_level:
            kind = LinkChangeKind.level_changed
        else:
            continue
        link_changes.append(
            LinkChange(
                link_id=link_id,
                kind=kind,
                baseline_utilization_percent=(
                    baseline_link.utilization_percent if baseline_link else None
                ),
                scenario_utilization_percent=(
                    scenario_link.utilization_percent if scenario_link else None
                ),
                baseline_level=baseline_level,
                scenario_level=scenario_level,
            )
        )

    recovery_available = not newly_unserved
    if recovery_available:
        recovery_note = "All demands served at baseline remain served."
    else:
        recovery_note = (
            "Service was lost for: " + ", ".join(newly_unserved) + "."
        )
    summary = (
        f"Baseline served {baseline_state.served_demand_count} of "
        f"{baseline_state.demand_count} demand(s); scenario served "
        f"{scenario_state.served_demand_count} of {scenario_state.demand_count}. "
        f"Max utilization {baseline_state.max_utilization_percent:.2f}% -> "
        f"{scenario_state.max_utilization_percent:.2f}%. "
        f"Newly unserved: {len(newly_unserved)}; path changes: "
        f"{len(path_changes)}; new congested links: {len(new_congested)}."
    )
    return ScenarioComparison(
        baseline_served_demand_count=baseline_state.served_demand_count,
        scenario_served_demand_count=scenario_state.served_demand_count,
        baseline_served_demand_ratio=baseline_state.served_demand_ratio,
        scenario_served_demand_ratio=scenario_state.served_demand_ratio,
        newly_unserved_demands=tuple(newly_unserved),
        recovered_demands=tuple(recovered),
        path_changes=tuple(path_changes),
        link_changes=tuple(link_changes),
        new_congested_links=tuple(new_congested),
        relieved_links=tuple(relieved),
        max_utilization_delta_percent=(
            scenario_state.max_utilization_percent
            - baseline_state.max_utilization_percent
        ),
        congested_link_delta=(
            scenario_state.congested_link_count - baseline_state.congested_link_count
        ),
        overloaded_link_delta=(
            scenario_state.overloaded_link_count
            - baseline_state.overloaded_link_count
        ),
        disconnected_device_delta=(
            len(scenario_state.disconnected_devices)
            - len(baseline_state.disconnected_devices)
        ),
        recovery_available=recovery_available,
        recovery_note=recovery_note,
        summary=summary,
    )


def run_scenario(
    baseline_twin: DigitalTwin,
    scenario: Scenario,
    assumptions: SimulationAssumptions | None = None,
    *,
    max_runtime_seconds: float | None = None,
) -> ScenarioRun:
    """Validate and evaluate one scenario against an unmodified baseline twin.

    Both evaluations share one runtime budget, bounded by
    ``MAX_SIMULATION_RUNTIME_SECONDS`` unless the caller requests a smaller one.
    """
    resolved_assumptions = (
        SimulationAssumptions()
        if assumptions is None
        else assumptions
        if isinstance(assumptions, SimulationAssumptions)
        else SimulationAssumptions.model_validate(assumptions)
    )
    deadline = _resolve_deadline(max_runtime_seconds, None)
    plan = _plan_scenario(baseline_twin, scenario)
    _check_deadline(deadline, "scenario construction")
    scenario_twin = _apply_plan(baseline_twin, plan)
    baseline_state = evaluate(
        baseline_twin,
        resolved_assumptions,
        _deadline=deadline,
    )
    scenario_state = evaluate(
        scenario_twin,
        resolved_assumptions,
        _deadline=deadline,
    )
    warnings = tuple(
        dict.fromkeys((*baseline_state.warnings, *scenario_state.warnings))
    )
    return ScenarioRun(
        scenario=scenario.model_copy(deep=True),
        baseline_twin=twin_reference(baseline_twin),
        scenario_twin=twin_reference(scenario_twin),
        assumptions=resolved_assumptions,
        thresholds=resolved_assumptions.thresholds,
        baseline_state=baseline_state,
        scenario_state=scenario_state,
        comparison=_compare(baseline_state, scenario_state),
        warnings=warnings,
    )


def compare_runs(left: ScenarioRun, right: ScenarioRun) -> ScenarioComparison:
    """Compare the scenario states of two retained results.

    The right-hand run is treated as the "scenario" side of the comparison, so
    positive deltas mean the second result is higher.
    """
    return _compare(left.scenario_state, right.scenario_state)


__all__ = [
    "LinkChange",
    "LinkChangeKind",
    "PathChange",
    "ScenarioComparison",
    "ScenarioRun",
    "compare_runs",
    "run_scenario",
    "validate_scenario",
]
