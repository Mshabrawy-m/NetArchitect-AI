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
import math
import time

from config.limits import MAX_ECMP_PATHS, MAX_SIMULATION_RUNTIME_SECONDS
from core.exceptions import LimitsExceededError, SimulationRuntimeExceeded
from core.schemas.network import Link, Topology
from core.schemas.routing import TrafficDemand
from digital_twin.adapters import failed_entities
from digital_twin.models import DigitalTwin
from digital_twin.serialization import canonical_payload
from network.routing.ha import active_member
from network.routing.paths import (
    RoutePath,
    component_summary_from_router,
    equal_cost_paths_from_router,
    shortest_path_from_router,
)
from network.routing.sparse import SparseRouter

from .models import (
    CongestionLevel,
    DemandEvaluation,
    FirstHopFailover,
    LinkLoad,
    NetworkState,
    PathSplit,
    RoutingMode,
    SimulationAssumptions,
    TwinReference,
    UnservedDemand,
)

INSUFFICIENT_CAPACITY_REASON = "insufficient capacity"


def twin_fingerprint(twin: DigitalTwin) -> str:
    """Return a stable SHA-256 fingerprint of the twin's canonical JSON.

    Field order is fixed by the models, and ``sort_keys`` removes any
    dependence on mapping insertion order. The fingerprint changes whenever
    the topology, demands, state, metadata, or stored security model change.
    An absent security model is omitted so legacy twin fingerprints are stable.
    """
    payload = json.dumps(
        canonical_payload(twin),
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


def _routing_key(
    topology: Topology,
    failed_devices: tuple[str, ...],
    failed_links: tuple[str, ...],
) -> tuple[object, ...]:
    """Identify a routing graph by the fields that affect path selection."""
    return (
        tuple(sorted(failed_devices)),
        tuple(sorted(failed_links)),
        tuple(
            (
                link.id,
                link.endpoints,
                float(link.cost),
                link.directed,
            )
            for link in topology.links
        ),
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
    demand: TrafficDemand,
    assumptions: SimulationAssumptions,
    *,
    router: SparseRouter,
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

    path = shortest_path_from_router(router, source, destination)
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


def _equal_shares(total: float, count: int) -> tuple[float, ...]:
    """Return ``count`` equal shares whose sum is exactly ``total`` in float."""
    if count < 1:
        raise ValueError("A split needs at least one path.")
    share = total / count
    shares = [share] * (count - 1)
    shares.append(total - sum(shares))
    return tuple(shares)


def _ecmp_demand_evaluation(
    demand: TrafficDemand,
    assumptions: SimulationAssumptions,
    *,
    router: SparseRouter,
    known_devices: set[str],
) -> tuple[DemandEvaluation, bool]:
    """Evaluate one demand with equal splitting over all capped equal-cost paths."""
    name = demand.name
    source = demand.source
    destination = demand.destination
    bandwidth = float(demand.bandwidth_mbps)

    if source not in known_devices:
        return (
            DemandEvaluation(
                name=name,
                source=source,
                destination=destination,
                bandwidth_mbps=bandwidth,
                served=False,
                reason=f"Source device {source!r} is not present in the twin topology",
            ),
            False,
        )
    if destination not in known_devices:
        return (
            DemandEvaluation(
                name=name,
                source=source,
                destination=destination,
                bandwidth_mbps=bandwidth,
                served=False,
                reason=(
                    f"Destination device {destination!r} is not present in the twin "
                    "topology"
                ),
            ),
            False,
        )

    paths, truncated = equal_cost_paths_from_router(
        router,
        source,
        destination,
        limit=MAX_ECMP_PATHS,
    )
    if not paths:
        path = shortest_path_from_router(router, source, destination)
        _, latency_note = _latency_for(path, assumptions)
        return (
            DemandEvaluation(
                name=name,
                source=source,
                destination=destination,
                bandwidth_mbps=bandwidth,
                served=False,
                reason=path.reason or "No path exists under the modeled state",
                latency_note=latency_note,
            ),
            False,
        )

    first = paths[0]
    latency, latency_note = _latency_for(first, assumptions)
    if latency is not None:
        latency_note = (
            "ECMP split: latency is shown for the lexicographically first "
            "equal-cost path. " + latency_note
        )
    shares = _equal_shares(bandwidth, len(paths))
    splits = tuple(
        PathSplit(
            path_device_ids=tuple(path.device_ids),
            link_ids=tuple(hop.link_id for hop in path.hops),
            bandwidth_mbps=share,
            share_percent=(100.0 / len(paths)),
            total_cost=path.total_cost,
            hop_count=path.hop_count,
        )
        for path, share in zip(paths, shares)
    )
    return (
        DemandEvaluation(
            name=name,
            source=source,
            destination=destination,
            bandwidth_mbps=bandwidth,
            served=True,
            path_device_ids=tuple(first.device_ids),
            link_ids=tuple(hop.link_id for hop in first.hops),
            total_cost=first.total_cost,
            hop_count=first.hop_count,
            latency_ms=latency,
            latency_note=latency_note,
            splits=splits,
        ),
        truncated,
    )


def _hop_available_mbps(
    link: Link,
    source: str,
    target: str,
    loads: dict[str, list[float]],
) -> float:
    """Return residual Mbps for one directed hop under the shared-capacity rule."""
    forward, reverse = loads.get(link.id, [0.0, 0.0])
    if link.directed:
        if not _hop_is_forward(link, source, target):
            return 0.0
        return max(0.0, float(link.capacity_mbps) - forward)
    return max(0.0, float(link.capacity_mbps) - forward - reverse)


def _consume_hop(
    link: Link,
    source: str,
    target: str,
    bandwidth: float,
    loads: dict[str, list[float]],
) -> None:
    """Add an admitted demand's bandwidth to the correct direction of a link."""
    if link.id not in loads:
        loads[link.id] = [0.0, 0.0]
    if _hop_is_forward(link, source, target):
        loads[link.id][0] += bandwidth
    else:
        loads[link.id][1] += bandwidth


def _path_bottleneck(
    path: RoutePath,
    link_index: dict[str, Link],
    loads: dict[str, list[float]],
) -> tuple[float, str]:
    """Return ``(residual Mbps, bottleneck link id)`` for one candidate path."""
    available = float("inf")
    bottleneck_id = ""
    for source, target, link_id in zip(
        path.device_ids,
        path.device_ids[1:],
        (hop.link_id for hop in path.hops),
    ):
        link = link_index[link_id]
        residual = _hop_available_mbps(link, source, target, loads)
        if residual < available or (residual == available and link_id < bottleneck_id):
            available = residual
            bottleneck_id = link_id
    return available, bottleneck_id


def _capacity_aware_evaluations(
    twin: DigitalTwin,
    *,
    router: SparseRouter,
    known_devices: set[str],
    deadline: float,
) -> tuple[tuple[DemandEvaluation, ...], bool]:
    """Place demands by capacity-aware admission control, in deterministic order.

    Demands are sorted by descending bandwidth, then by demand id. Each demand
    takes the first lexicographic lowest-cost path with enough residual
    capacity. Residual accounting follows the modeled direction rules: directed
    links consume only their permitted direction; undirected links consume one
    shared pool from both directions. A rejected demand keeps the best blocked
    path, defined as the equal-cost path with the largest bottleneck residual,
    with lexicographic path order as the tie-break.
    """
    link_index = {link.id: link for link in twin.topology.links}
    loads: dict[str, list[float]] = {}
    ordered = sorted(
        enumerate(twin.demands),
        key=lambda item: (-float(item[1].bandwidth_mbps), item[1].name),
    )
    results: list[DemandEvaluation | None] = [None] * len(twin.demands)
    truncated = False

    for index, demand in ordered:
        _check_deadline(deadline, "capacity-aware admission")
        name = demand.name
        source = demand.source
        destination = demand.destination
        bandwidth = float(demand.bandwidth_mbps)

        if source not in known_devices:
            results[index] = DemandEvaluation(
                name=name,
                source=source,
                destination=destination,
                bandwidth_mbps=bandwidth,
                served=False,
                reason=f"Source device {source!r} is not present in the twin topology",
            )
            continue
        if destination not in known_devices:
            results[index] = DemandEvaluation(
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
            continue

        paths, path_truncated = equal_cost_paths_from_router(
            router,
            source,
            destination,
            limit=MAX_ECMP_PATHS,
        )
        truncated = truncated or path_truncated
        if not paths:
            unreachable = shortest_path_from_router(router, source, destination)
            results[index] = DemandEvaluation(
                name=name,
                source=source,
                destination=destination,
                bandwidth_mbps=bandwidth,
                served=False,
                reason=unreachable.reason or "No path exists under the modeled state",
            )
            continue

        admitted = None
        for path in paths:
            residual, bottleneck_id = _path_bottleneck(path, link_index, loads)
            if bandwidth <= residual:
                admitted = (path, residual, bottleneck_id)
                break

        if admitted is None:
            best_path = paths[0]
            best_residual, best_bottleneck = _path_bottleneck(
                best_path, link_index, loads
            )
            for path in paths[1:]:
                residual, bottleneck_id = _path_bottleneck(path, link_index, loads)
                if residual > best_residual:
                    best_path = path
                    best_residual = residual
                    best_bottleneck = bottleneck_id
            results[index] = DemandEvaluation(
                name=name,
                source=source,
                destination=destination,
                bandwidth_mbps=bandwidth,
                served=False,
                reason=INSUFFICIENT_CAPACITY_REASON,
                blocked_path_device_ids=tuple(best_path.device_ids),
                blocked_link_ids=tuple(hop.link_id for hop in best_path.hops),
                bottleneck_link_id=best_bottleneck,
                bottleneck_available_mbps=(
                    None if math.isinf(best_residual) else max(0.0, best_residual)
                ),
            )
            continue

        path, _, _ = admitted
        for source_id, target_id, link_id in zip(
            path.device_ids,
            path.device_ids[1:],
            (hop.link_id for hop in path.hops),
        ):
            _consume_hop(
                link_index[link_id],
                source_id,
                target_id,
                bandwidth,
                loads,
            )
        results[index] = DemandEvaluation(
            name=name,
            source=source,
            destination=destination,
            bandwidth_mbps=bandwidth,
            served=True,
            path_device_ids=tuple(path.device_ids),
            link_ids=tuple(hop.link_id for hop in path.hops),
            total_cost=path.total_cost,
            hop_count=path.hop_count,
        )

    return tuple(item for item in results if item is not None), truncated


def _connected_devices(
    topology: Topology,
    *,
    router: SparseRouter,
    failed_devices: tuple[str, ...],
) -> tuple[
    tuple[tuple[str, ...], ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    summary = component_summary_from_router(router)
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
        if evaluation.splits:
            paths = [
                (
                    split.path_device_ids,
                    split.link_ids,
                    split.bandwidth_mbps,
                )
                for split in evaluation.splits
            ]
        else:
            paths = [
                (
                    evaluation.path_device_ids,
                    evaluation.link_ids,
                    evaluation.bandwidth_mbps,
                )
            ]
        for path_device_ids, path_link_ids, bandwidth in paths:
            for hop in zip(
                path_device_ids,
                path_device_ids[1:],
                path_link_ids,
            ):
                source, target, link_id = hop
                if link_id not in loads:
                    loads[link_id] = [0.0, 0.0]
                    forward[link_id] = []
                    reverse[link_id] = []
                link = link_index[link_id]
                if _hop_is_forward(link, source, target):
                    loads[link_id][0] += bandwidth
                    forward[link_id].append(evaluation.name)
                else:
                    loads[link_id][1] += bandwidth
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


def _first_hop_failovers(
    twin: DigitalTwin,
    assumptions: SimulationAssumptions,
    demand_tuple: tuple[DemandEvaluation, ...],
    *,
    failed_devices: tuple[str, ...],
    router_cache: dict[tuple[object, ...], SparseRouter],
    deadline: float,
) -> tuple[FirstHopFailover, ...]:
    """Return additive modeled first-hop re-homes for failed HA active members.

    This view is default-off and never changes the legacy demand paths, link
    loads, or metrics. For each group whose nominal active member is modeled
    down, the baseline (no-failure) path is compared with the evaluated path.
    A record is emitted when the baseline first hop was the failed active and
    the evaluated first hop is the next-highest-priority live member. Paths come
    from the routing engine; no packet behavior is simulated.
    """
    if not assumptions.enable_first_hop_failover or not twin.ha_groups:
        return ()

    failed_set = set(failed_devices)
    candidates: list[tuple[object, object, object]] = []
    for group in twin.ha_groups:
        nominal = active_member(group)
        if nominal is None or nominal.device_id not in failed_set:
            continue
        successor = active_member(group, failed_devices=failed_set)
        if successor is None or successor.device_id == nominal.device_id:
            continue
        candidates.append((group, nominal, successor))
    if not candidates:
        return ()

    baseline_key = _routing_key(twin.topology, (), ())
    baseline = router_cache.get(baseline_key)
    if baseline is None:
        baseline = SparseRouter.from_topology(twin.topology)
        router_cache[baseline_key] = baseline

    records: list[FirstHopFailover] = []
    for group, nominal, successor in candidates:
        for demand, evaluation in zip(twin.demands, demand_tuple):
            _check_deadline(deadline, "first-hop failover")
            before = shortest_path_from_router(
                baseline, demand.source, demand.destination
            )
            if (
                not before.reachable
                or len(before.device_ids) < 2
                or before.device_ids[1] != nominal.device_id
            ):
                continue
            if (
                not evaluation.served
                or len(evaluation.path_device_ids) < 2
                or evaluation.path_device_ids[1] != successor.device_id
            ):
                continue
            records.append(
                FirstHopFailover(
                    group_id=group.id,
                    demand_name=demand.name,
                    failed_active=nominal.device_id,
                    next_active=successor.device_id,
                    before_path_device_ids=tuple(before.device_ids),
                    after_path_device_ids=evaluation.path_device_ids,
                    before_link_ids=tuple(hop.link_id for hop in before.hops),
                    after_link_ids=evaluation.link_ids,
                    note=(
                        f"Modeled HA election: {nominal.device_id} (priority "
                        f"{nominal.priority}) is down; next-highest-priority live "
                        f"member {successor.device_id} (priority "
                        f"{successor.priority}) is the new first hop. Paths are "
                        "routing-engine paths, not simulated packets."
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
    _router_cache: dict[tuple[object, ...], SparseRouter] | None = None,
) -> NetworkState:
    """Evaluate one twin revision and return its modeled network state.

    ``assumptions`` carries the congestion thresholds and the optional per-link
    delay map. The twin is never modified. ``max_runtime_seconds`` may only
    lower the global limit; ``_deadline`` is an internal absolute monotonic
    deadline used by the scenario engine to share one budget across evaluations.
    ``_router_cache`` is an optional per-run cache of sparse routing arrays.
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

    router_cache = _router_cache if _router_cache is not None else {}
    routing_key = _routing_key(
        twin.topology, selection.devices, selection.links
    )
    router = router_cache.get(routing_key)
    if router is None:
        router = SparseRouter.from_topology(
            twin.topology,
            failed_devices=selection.devices,
            failed_links=selection.links,
        )
        router_cache[routing_key] = router

    known_devices = {device.id for device in twin.topology.devices}
    mode = resolved_assumptions.routing_mode
    truncated = False
    if mode is RoutingMode.single_path:
        demands: list[DemandEvaluation] = []
        for demand in twin.demands:
            _check_deadline(deadline, "demand routing")
            demands.append(
                _demand_evaluation(
                    demand,
                    resolved_assumptions,
                    router=router,
                    known_devices=known_devices,
                )
            )
        demand_tuple = tuple(demands)
    elif mode is RoutingMode.ecmp:
        ecmp_evaluations: list[DemandEvaluation] = []
        for demand in twin.demands:
            _check_deadline(deadline, "demand routing")
            evaluation, path_truncated = _ecmp_demand_evaluation(
                demand,
                resolved_assumptions,
                router=router,
                known_devices=known_devices,
            )
            ecmp_evaluations.append(evaluation)
            truncated = truncated or path_truncated
        demand_tuple = tuple(ecmp_evaluations)
    else:
        demand_tuple, truncated = _capacity_aware_evaluations(
            twin,
            router=router,
            known_devices=known_devices,
            deadline=deadline,
        )

    if truncated:
        if mode is RoutingMode.ecmp:
            warnings.append(
                f"ECMP used the lexicographically first {MAX_ECMP_PATHS} "
                "equal-cost paths; additional equal-cost paths were not split."
            )
        else:
            warnings.append(
                "Capacity-aware admission considered the lexicographically "
                f"first {MAX_ECMP_PATHS} equal-cost paths; additional "
                "equal-cost paths were not considered."
            )
    unserved = tuple(
        UnservedDemand(
            name=evaluation.name,
            source=evaluation.source,
            destination=evaluation.destination,
            bandwidth_mbps=evaluation.bandwidth_mbps,
            reason=evaluation.reason,
            blocked_path_device_ids=evaluation.blocked_path_device_ids,
            blocked_link_ids=evaluation.blocked_link_ids,
            bottleneck_link_id=evaluation.bottleneck_link_id,
            bottleneck_available_mbps=evaluation.bottleneck_available_mbps,
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
        router=router,
        failed_devices=selection.devices,
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
        first_hop_failovers=_first_hop_failovers(
            twin,
            resolved_assumptions,
            demand_tuple,
            failed_devices=selection.devices,
            router_cache=router_cache,
            deadline=deadline,
        ),
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
