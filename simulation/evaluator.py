"""Deterministic evaluation of one digital-twin revision.

The evaluator is a pure function of the twin and the explicit assumptions:
no randomness is used, iteration order is fixed, and the same inputs always
produce the same :class:`~simulation.models.NetworkState`. The supplied twin is
never mutated.

Model rules are documented in :mod:`simulation.models`. In short: each demand
takes the single lowest-cost path from the existing routing engine (no ECMP),
link load is the sum of the bandwidth of demands traversing that link, and
utilization may exceed 100 percent because it is never clamped.

Runtime is bounded by ``MAX_SIMULATION_RUNTIME_SECONDS``. A caller may request a
smaller bound; exceeding it raises :class:`SimulationRuntimeExceeded`.
"""

from __future__ import annotations

import hashlib
import json
import time

from config.limits import MAX_SIMULATION_RUNTIME_SECONDS
from core.exceptions import LimitsExceededError, SimulationRuntimeExceeded
from core.schemas.network import Link, Topology
from core.schemas.routing import TrafficDemand
from digital_twin.adapters import failed_entities
from digital_twin.models import DigitalTwin
from network.routing import component_summary, shortest_path
from network.routing.paths import RoutePath

from .models import (
    CongestionLevel,
    DemandEvaluation,
    LinkLoad,
    NetworkState,
    SimulationAssumptions,
    TwinReference,
    UnservedDemand,
)


def twin_fingerprint(twin: DigitalTwin) -> str:
    """Return a stable SHA-256 fingerprint of the twin's canonical JSON.

    Field order is fixed by the models, and ``sort_keys`` removes any
    dependence on mapping insertion order. The fingerprint changes whenever
    the topology, demands, state, or metadata change.
    """
    payload = json.dumps(
        twin.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def twin_reference(twin: DigitalTwin) -> TwinReference:
    """Build the traceability reference recorded with every result."""
    return TwinReference(
        name=twin.metadata.name,
        created_at=twin.metadata.created_at,
        schema_version=twin.metadata.schema_version,
        fingerprint=twin_fingerprint(twin),
    )


def _resolve_deadline(
    max_runtime_seconds: float | None,
    deadline: float | None,
) -> float:
    if deadline is not None:
        return deadline
    limit = (
        float(MAX_SIMULATION_RUNTIME_SECONDS)
        if max_runtime_seconds is None
        else float(max_runtime_seconds)
    )
    if limit <= 0:
        raise ValueError(f"max_runtime_seconds must be positive, got {limit}")
    if limit > MAX_SIMULATION_RUNTIME_SECONDS:
        raise LimitsExceededError(
            f"Requested a {limit:g}s simulation budget; the limit is "
            f"{MAX_SIMULATION_RUNTIME_SECONDS}s"
        )
    return time.perf_counter() + limit


def _check_deadline(deadline: float, phase: str) -> None:
    if time.perf_counter() > deadline:
        raise SimulationRuntimeExceeded(
            "Simulation exceeded its configured runtime limit during "
            f"{phase}. Reduce the topology or demand count and try again."
        )


def _hop_is_forward(link: Link, source: str, target: str) -> bool:
    return link.endpoints[0] == source and link.endpoints[1] == target


def _latency_for(
    path: RoutePath,
    assumptions: SimulationAssumptions,
) -> tuple[float | None, str]:
    if not path.reachable:
        return None, "No path, so latency is not estimated."
    if not path.hops:
        return 0.0, "No links traversed; latency is zero by definition."
    delays = assumptions.link_delay_ms
    missing = [hop.link_id for hop in path.hops if hop.link_id not in delays]
    if missing:
        return (
            None,
            "Latency not estimated because no delay assumption exists for "
            + ", ".join(sorted(set(missing)))
            + ".",
        )
    return (
        float(sum(delays[hop.link_id] for hop in path.hops)),
        "Estimated as the sum of the assumed one-way delay of every hop.",
    )


def _demand_evaluation(
    topology: Topology,
    demand: TrafficDemand,
    assumptions: SimulationAssumptions,
    *,
    failed_devices: tuple[str, ...],
    failed_links: tuple[str, ...],
    known_devices: set[str],
) -> DemandEvaluation:
    name = demand.name
    source = demand.source
    destination = demand.destination
    bandwidth = float(demand.bandwidth_mbps)

    if source not in known_devices:
        return DemandEvaluation(
            name=name,
            source=source,
            destination=destination,
            bandwidth_mbps=bandwidth,
            served=False,
            reason=f"Source device {source!r} is not present in the twin topology",
        )
    if destination not in known_devices:
        return DemandEvaluation(
            name=name,
            source=source,
            destination=destination,
            bandwidth_mbps=bandwidth,
            served=False,
            reason=(
                f"Destination device {destination!r} is not present in the twin "
                "topology"
            ),
        )

    path = shortest_path(
        topology,
        source,
        destination,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    latency, latency_note = _latency_for(path, assumptions)
    if not path.reachable:
        return DemandEvaluation(
            name=name,
            source=source,
            destination=destination,
            bandwidth_mbps=bandwidth,
            served=False,
            reason=path.reason or "No path exists under the modeled state",
            latency_note=latency_note,
        )
    return DemandEvaluation(
        name=name,
        source=source,
        destination=destination,
        bandwidth_mbps=bandwidth,
        served=True,
        path_device_ids=tuple(path.device_ids),
        link_ids=tuple(hop.link_id for hop in path.hops),
        total_cost=path.total_cost,
        hop_count=path.hop_count,
        latency_ms=latency,
        latency_note=latency_note,
    )


def _connected_devices(
    topology: Topology,
    *,
    failed_devices: tuple[str, ...],
    failed_links: tuple[str, ...],
) -> tuple[
    tuple[tuple[str, ...], ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    summary = component_summary(
        topology,
        failed_devices=failed_devices,
        failed_links=failed_links,
    )
    components = tuple(tuple(component) for component in summary.weak_components)
    isolated = tuple(summary.isolated_device_ids)
    if not components:
        return components, isolated, ()
    largest = min(
        components,
        key=lambda component: (-len(component), component[0]),
    )
    largest_ids = set(largest)
    disconnected = tuple(
        sorted(
            device.id
            for device in topology.devices
            if device.id not in largest_ids
            and device.id not in set(failed_devices)
        )
    )
    return components, isolated, disconnected


def _link_loads(
    topology: Topology,
    demands: tuple[DemandEvaluation, ...],
    assumptions: SimulationAssumptions,
    *,
    failed_devices: tuple[str, ...],
    failed_links: tuple[str, ...],
    deadline: float,
) -> tuple[LinkLoad, ...]:
    failed_device_ids = set(failed_devices)
    failed_link_ids = set(failed_links)
    link_index = {link.id: link for link in topology.links}
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}
    loads: dict[str, list[float]] = {}

    for evaluation in demands:
        if not evaluation.served:
            continue
        for hop in zip(
            evaluation.path_device_ids,
            evaluation.path_device_ids[1:],
            evaluation.link_ids,
        ):
            source, target, link_id = hop
            if link_id not in loads:
                loads[link_id] = [0.0, 0.0]
                forward[link_id] = []
                reverse[link_id] = []
            link = link_index[link_id]
            if _hop_is_forward(link, source, target):
                loads[link_id][0] += evaluation.bandwidth_mbps
                forward[link_id].append(evaluation.name)
            else:
                loads[link_id][1] += evaluation.bandwidth_mbps
                reverse[link_id].append(evaluation.name)

    records: list[LinkLoad] = []
    for link in topology.links:
        _check_deadline(deadline, "link-load accounting")
        if link.id in failed_link_ids:
            continue
        if any(endpoint in failed_device_ids for endpoint in link.endpoints):
            continue
        link_forward = tuple(forward.get(link.id, ()))
        link_reverse = tuple(reverse.get(link.id, ()))
        forward_load, reverse_load = loads.get(link.id, [0.0, 0.0])
        if link.directed:
            load = forward_load
            reverse_load = 0.0
            link_reverse = ()
        else:
            load = forward_load + reverse_load
        utilization = load / float(link.capacity_mbps) * 100.0
        records.append(
            LinkLoad(
                link_id=link.id,
                endpoints=link.endpoints,
                directed=link.directed,
                capacity_mbps=float(link.capacity_mbps),
                forward_load_mbps=forward_load,
                reverse_load_mbps=reverse_load,
                load_mbps=load,
                utilization_percent=utilization,
                level=assumptions.thresholds.level_for(utilization),
                forward_demand_names=link_forward,
                reverse_demand_names=link_reverse,
                demand_names=tuple(
                    dict.fromkeys((*link_forward, *link_reverse))
                ),
            )
        )
    return tuple(records)


def evaluate(
    twin: DigitalTwin,
    assumptions: SimulationAssumptions | None = None,
    *,
    max_runtime_seconds: float | None = None,
    _deadline: float | None = None,
) -> NetworkState:
    """Evaluate one twin revision and return its modeled network state.

    ``assumptions`` carries the congestion thresholds and the optional per-link
    delay map. The twin is never modified. ``max_runtime_seconds`` may only
    lower the global limit; ``_deadline`` is an internal absolute monotonic
    deadline used by the scenario engine to share one budget across evaluations.
    """
    resolved_assumptions = (
        SimulationAssumptions() if assumptions is None else assumptions
    )
    if not isinstance(resolved_assumptions, SimulationAssumptions):
        resolved_assumptions = SimulationAssumptions.model_validate(assumptions)

    deadline = _resolve_deadline(max_runtime_seconds, _deadline)
    selection = failed_entities(twin)
    warnings: list[str] = []
    if selection.stale_devices or selection.stale_links:
        warnings.append(
            "Twin has stale operational state for entities no longer in the "
            "topology; stale entries are ignored by the model. "
            f"Devices: {', '.join(selection.stale_devices) or 'none'}. "
            f"Links: {', '.join(selection.stale_links) or 'none'}."
        )

    known_devices = {device.id for device in twin.topology.devices}
    demands: list[DemandEvaluation] = []
    for demand in twin.demands:
        _check_deadline(deadline, "demand routing")
        demands.append(
            _demand_evaluation(
                twin.topology,
                demand,
                resolved_assumptions,
                failed_devices=selection.devices,
                failed_links=selection.links,
                known_devices=known_devices,
            )
        )
    demand_tuple = tuple(demands)
    unserved = tuple(
        UnservedDemand(
            name=evaluation.name,
            source=evaluation.source,
            destination=evaluation.destination,
            bandwidth_mbps=evaluation.bandwidth_mbps,
            reason=evaluation.reason,
        )
        for evaluation in demand_tuple
        if not evaluation.served
    )

    links = _link_loads(
        twin.topology,
        demand_tuple,
        resolved_assumptions,
        failed_devices=selection.devices,
        failed_links=selection.links,
        deadline=deadline,
    )

    _check_deadline(deadline, "connectivity summary")
    components, isolated, disconnected = _connected_devices(
        twin.topology,
        failed_devices=selection.devices,
        failed_links=selection.links,
    )

    served = tuple(evaluation for evaluation in demand_tuple if evaluation.served)
    served_mbps = float(sum(evaluation.bandwidth_mbps for evaluation in served))
    total_mbps = float(
        sum(evaluation.bandwidth_mbps for evaluation in demand_tuple)
    )
    return NetworkState(
        twin=twin_reference(twin),
        assumptions=resolved_assumptions,
        thresholds=resolved_assumptions.thresholds,
        device_count=len(twin.topology.devices),
        link_count=len(twin.topology.links),
        demand_count=len(twin.demands),
        demands=demand_tuple,
        links=links,
        unserved_demands=unserved,
        failed_devices=selection.devices,
        failed_links=selection.links,
        weak_components=components,
        isolated_devices=isolated,
        disconnected_devices=disconnected,
        max_utilization_percent=max(
            (link.utilization_percent for link in links),
            default=0.0,
        ),
        congested_link_count=sum(
            1 for link in links if link.level is not CongestionLevel.normal
        ),
        overloaded_link_count=sum(
            1 for link in links if link.level is CongestionLevel.overloaded
        ),
        served_demand_count=len(served),
        served_demand_ratio=(
            len(served) / len(demand_tuple) if demand_tuple else 0.0
        ),
        total_demand_mbps=total_mbps,
        served_demand_mbps=served_mbps,
        total_path_cost=float(sum(evaluation.total_cost for evaluation in served)),
        warnings=tuple(warnings),
    )


def link_by_id(links: tuple[LinkLoad, ...], link_id: str) -> LinkLoad | None:
    """Return the load record for ``link_id``, if it survived the scenario."""
    for link in links:
        if link.link_id == link_id:
            return link
    return None


__all__ = [
    "evaluate",
    "link_by_id",
    "twin_fingerprint",
    "twin_reference",
]
