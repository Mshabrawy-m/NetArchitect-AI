"""Deterministic Layer-2 switching design analysis (design model only).

This module reads modeled intent from a digital twin and returns typed,
hand-checkable results. It does not configure equipment, run STP, send
advertisements, or observe live protocol state. WAN link fields are ignored.

Modeled design rules
--------------------
1. VLAN ids come from ``twin.vlan_plan`` when ``plan`` is None; an explicitly
   supplied ``plan`` overrides the twin. An access-port VLAN id that is set but
   absent from that plan produces an informational ``l2_access_vlan_not_in_plan``
   finding. With no plan at all the planned set is empty.
2. For every up, unblocked trunk link, access-link VLANs reachable beyond either
   endpoint *without crossing that trunk* are found by a breadth-first walk
   over links that carry the same VLAN. Reachable access VLANs missing from the
   trunk's ``l2_allowed_vlans`` produce ``l2_trunk_missing_downstream_vlan``.
   The walk visits each device at most once per (trunk, VLAN), so it is bounded
   by topology size and uses no recursion.
3. A link with both ``l2_native_vlan`` and ``l2_peer_native_vlan`` set to
   different ids produces an error ``l2_native_vlan_mismatch``.
4. Gateway reachability uses ``design.gateway_by_vlan`` only (never DHCP scopes
   or addressing plans). For each planned VLAN with a modeled gateway, if at
   least one switch carries the VLAN and the gateway cannot reach any such
   switch over links that carry that VLAN, emit ``l2_vlan_no_gateway_path``.
   No finding is emitted when no switch carries the VLAN or no gateway is
   modeled. Devices modeled down are excluded from these graph walks.
5. VLAN sprawl counts distinct modeled switch/layer3_switch devices carrying a
   VLAN. A count greater than ``design.vlan_spread_threshold`` (default from
   the model) produces ``l2_vlan_sprawl``. This is a configurable, documented
   planning heuristic, NOT a protocol limit or a device capability.
6. Loop analysis runs per VLAN over the switch/layer3_switch graph.
   ``switch_ids`` and ``carrying_link_ids`` are sorted; ``carrying_link_ids``
   contains only carrying links whose two endpoints are switches. Components
   are counted over ``switch_ids`` (0 when there are none), and
   ``cycle_count = edges - vertices + components``: a triangle is 3-3+1=1, a
   square is 4-4+1=1, and two disjoint triangles are 6-6+2=2. The root bridge
   is the switch with the smallest ``(priority, device.id)`` where priority
   comes from ``design.root_priorities`` and unlisted switches default to
   32768; it is None when no switch carries the VLAN. Blocked links are exactly
   the carrying switch-to-switch links omitted from a deterministic minimum
   spanning forest built by Kruskal's rule: consider links in ascending
   ``(link.cost, link.id)`` order and keep one only if it joins two distinct
   components. Forwarding links are carrying links minus blocked links. A
   positive cycle count produces ``l2_loop_needs_blocking``. These are modeled
   design choices, not a running spanning-tree instance.
7. Each ``design.etherchannel_bundles`` entry is measured with
   :func:`bundle_capacity`. Existing member capacities (including failed ones)
   are preserved in ``member_speeds_mbps`` for review. Differing capacities
   produce ``l2_mismatched_bundle_speeds``; fewer than two existing members
   (missing link ids do not count) produce ``l2_single_member_bundle``.
8. ``effective_link_ids`` is every topology link id except the blocked ids;
   failed/down links remain listed because they still exist in the topology.
   ``blocked_link_ids`` is the sorted union of per-VLAN blocked links.

All findings carry stable codes and deterministic ``affected_entities``: entity
lists derived from sets are sorted, and VLAN ids use the ``vlan-<id>`` form.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.schemas.network import DeviceType, Link
from core.schemas.validation import Finding, Severity

from .models import EtherChannelBundle, L2Design, LinkL2Mode

if TYPE_CHECKING:
    from digital_twin.models import DigitalTwin
    from network.vlan.plan import VlanPlanResult

_DEFAULT_ROOT_PRIORITY = 32768
_SWITCH_TYPES = frozenset({DeviceType.switch, DeviceType.layer3_switch})


@dataclass(frozen=True)
class BundleCapacity:
    """Modeled aggregate capacity of one EtherChannel bundle."""

    bundle_id: str
    member_link_ids: tuple[str, ...]
    member_speeds_mbps: tuple[float, ...]
    capacity_mbps: float
    down: bool
    failed_member_link_ids: tuple[str, ...]


@dataclass(frozen=True)
class LoopAnalysis:
    """Per-VLAN cycle-rank and deterministic blocking result."""

    vlan_id: int
    switch_ids: tuple[str, ...]
    carrying_link_ids: tuple[str, ...]
    cycle_count: int
    component_count: int
    root_bridge: str | None
    blocked_link_ids: tuple[str, ...]
    forwarding_link_ids: tuple[str, ...]


@dataclass(frozen=True)
class L2Analysis:
    """Complete deterministic Layer-2 design review."""

    findings: tuple[Finding, ...]
    loops: tuple[LoopAnalysis, ...]
    blocked_link_ids: tuple[str, ...]
    effective_link_ids: tuple[str, ...]
    bundles: tuple[BundleCapacity, ...]


def _finding(
    severity: Severity,
    code: str,
    entities: Sequence[str],
    explanation: str,
    remediation: str,
) -> Finding:
    return Finding(
        severity=severity,
        code=code,
        affected_entities=list(entities),
        explanation=explanation,
        remediation=remediation,
    )


def _vlan_entity(vlan_id: int) -> str:
    return f"vlan-{vlan_id}"


def _state_value(state: object) -> str:
    return str(getattr(state, "value", state))


def _failed_link_ids(twin: DigitalTwin) -> frozenset[str]:
    return frozenset(
        entry.link_id
        for entry in twin.link_states
        if _state_value(entry.state) == "down"
    )


def _down_device_ids(twin: DigitalTwin) -> frozenset[str]:
    return frozenset(
        entry.device_id
        for entry in twin.device_states
        if _state_value(entry.state) == "down"
    )


def _switch_device_ids(twin: DigitalTwin, down_devices: frozenset[str]) -> frozenset[str]:
    return frozenset(
        device.id
        for device in twin.topology.devices
        if device.type in _SWITCH_TYPES and device.id not in down_devices
    )


def _resolve_design(twin: DigitalTwin, design: L2Design | None) -> L2Design:
    if design is not None:
        return design
    return twin.l2_design if twin.l2_design is not None else L2Design()


def _planned_vlan_ids(twin: DigitalTwin, plan: VlanPlanResult | None) -> tuple[int, ...]:
    source = plan if plan is not None else twin.vlan_plan
    if source is None:
        return ()
    return tuple(sorted({assignment.vlan_id for assignment in source.assignments}))


def _link_carries(link: Link, vlan_id: int) -> bool:
    if link.l2_mode is LinkL2Mode.trunk:
        return vlan_id in link.l2_allowed_vlans
    if link.l2_mode is LinkL2Mode.access:
        return link.l2_access_vlan == vlan_id
    return False


def _analysis_vlan_ids(twin: DigitalTwin, planned: Sequence[int]) -> tuple[int, ...]:
    modeled: set[int] = set()
    for link in twin.topology.links:
        if link.l2_mode is LinkL2Mode.access and link.l2_access_vlan is not None:
            modeled.add(link.l2_access_vlan)
        if link.l2_mode is LinkL2Mode.trunk:
            modeled.update(link.l2_allowed_vlans)
    return tuple(sorted(set(planned) | modeled))


def _usable_links(
    twin: DigitalTwin,
    vlan_id: int,
    *,
    blocked: frozenset[str],
    failed: frozenset[str],
    down_devices: frozenset[str] = frozenset(),
) -> tuple[Link, ...]:
    return tuple(
        link
        for link in twin.topology.links
        if link.id not in blocked
        and link.id not in failed
        and _link_carries(link, vlan_id)
        and not any(endpoint in down_devices for endpoint in link.endpoints)
    )


def _adjacency(twin: DigitalTwin) -> dict[str, tuple[Link, ...]]:
    neighbors: dict[str, list[Link]] = {device.id: [] for device in twin.topology.devices}
    for link in twin.topology.links:
        for endpoint in link.endpoints:
            neighbors.setdefault(endpoint, []).append(link)
    return {device_id: tuple(links) for device_id, links in neighbors.items()}


def _union_find_root(parent: dict[str, str], node: str) -> str:
    while parent[node] != node:
        parent[node] = parent[parent[node]]
        node = parent[node]
    return node


def bundle_capacity(
    bundle: EtherChannelBundle,
    links: Sequence[Link],
    failed_link_ids: Iterable[str] = (),
) -> BundleCapacity:
    """Sum capacities of surviving existing members of ``bundle``.

    Member ids are canonicalized by sorting. Missing link ids are ignored for
    capacity but remain visible in ``member_link_ids``. Speeds of all existing
    members (failed ones included) stay in ``member_speeds_mbps`` for mismatch
    review. The bundle is down only when no existing member survives.
    """
    failed = set(failed_link_ids)
    member_ids = tuple(sorted(set(bundle.link_ids)))
    links_by_id = {link.id: link for link in links}
    existing = tuple(
        (member_id, links_by_id[member_id])
        for member_id in member_ids
        if member_id in links_by_id
    )
    surviving = tuple(
        link for member_id, link in existing if member_id not in failed
    )
    failed_members = tuple(
        member_id for member_id, _ in existing if member_id in failed
    )
    return BundleCapacity(
        bundle_id=bundle.id,
        member_link_ids=member_ids,
        member_speeds_mbps=tuple(float(link.capacity_mbps) for _, link in existing),
        capacity_mbps=float(sum(link.capacity_mbps for link in surviving)),
        down=not surviving,
        failed_member_link_ids=failed_members,
    )


def _loop_analyses(
    twin: DigitalTwin,
    *,
    design: L2Design,
    vlan_ids: Sequence[int],
    failed: frozenset[str],
    down_devices: frozenset[str],
) -> tuple[LoopAnalysis, ...]:
    switches = _switch_device_ids(twin, down_devices)
    loops: list[LoopAnalysis] = []
    for vlan_id in vlan_ids:
        carrying = _usable_links(
            twin,
            vlan_id,
            blocked=frozenset(),
            failed=failed,
            down_devices=down_devices,
        )
        carrying_switches = tuple(
            sorted(
                {
                    endpoint
                    for link in carrying
                    for endpoint in link.endpoints
                    if endpoint in switches
                }
            )
        )
        switch_links = tuple(
            link
            for link in carrying
            if link.endpoints[0] in switches and link.endpoints[1] in switches
        )
        carrying_link_ids = tuple(sorted(link.id for link in switch_links))

        parent = {switch_id: switch_id for switch_id in carrying_switches}
        selected: set[str] = set()
        # Deterministic MST: ascending (cost, id), keep only join edges.
        for link in sorted(switch_links, key=lambda item: (item.cost, item.id)):
            first = _union_find_root(parent, link.endpoints[0])
            second = _union_find_root(parent, link.endpoints[1])
            if first != second:
                parent[first] = second
                selected.add(link.id)

        component_count = len(
            {_union_find_root(parent, switch_id) for switch_id in carrying_switches}
        )
        cycle_count = len(carrying_link_ids) - len(carrying_switches) + component_count
        blocked_ids = tuple(
            sorted(link_id for link_id in carrying_link_ids if link_id not in selected)
        )
        root_bridge = (
            min(
                carrying_switches,
                key=lambda switch_id: (
                    design.root_priorities.get(switch_id, _DEFAULT_ROOT_PRIORITY),
                    switch_id,
                ),
            )
            if carrying_switches
            else None
        )
        loops.append(
            LoopAnalysis(
                vlan_id=vlan_id,
                switch_ids=carrying_switches,
                carrying_link_ids=carrying_link_ids,
                cycle_count=cycle_count,
                component_count=component_count,
                root_bridge=root_bridge,
                blocked_link_ids=blocked_ids,
                forwarding_link_ids=tuple(
                    link_id for link_id in carrying_link_ids if link_id in selected
                ),
            )
        )
    return tuple(loops)


def _blocked_ids(loops: Sequence[LoopAnalysis]) -> tuple[str, ...]:
    return tuple(sorted({link_id for loop in loops for link_id in loop.blocked_link_ids}))


def _access_findings(
    twin: DigitalTwin, planned: Sequence[int]
) -> tuple[Finding, ...]:
    known = set(planned)
    findings: list[Finding] = []
    for link in sorted(twin.topology.links, key=lambda item: item.id):
        vlan_id = link.l2_access_vlan
        if vlan_id is not None and vlan_id not in known:
            findings.append(
                _finding(
                    Severity.info,
                    "l2_access_vlan_not_in_plan",
                    (link.id, _vlan_entity(vlan_id)),
                    f"Access link {link.id} uses VLAN {vlan_id}, which is not in the VLAN plan.",
                    "Add the VLAN to the plan or change the modeled access VLAN.",
                )
            )
    return tuple(findings)


def _native_findings(twin: DigitalTwin) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for link in sorted(twin.topology.links, key=lambda item: item.id):
        local = link.l2_native_vlan
        peer = link.l2_peer_native_vlan
        if local is not None and peer is not None and local != peer:
            findings.append(
                _finding(
                    Severity.error,
                    "l2_native_vlan_mismatch",
                    (link.id, *link.endpoints, _vlan_entity(local), _vlan_entity(peer)),
                    (
                        f"Link {link.id} models native VLAN {local} at "
                        f"{link.endpoints[0]} and {peer} at {link.endpoints[1]}."
                    ),
                    "Model the same native VLAN at both endpoints.",
                )
            )
    return tuple(findings)


def _reachable_access_vlan(
    adjacency: dict[str, tuple[Link, ...]],
    start: str,
    vlan_id: int,
    *,
    excluded_link_id: str,
    blocked: frozenset[str],
    failed: frozenset[str],
    down_devices: frozenset[str],
) -> bool:
    if start in down_devices:
        return False
    visited = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for link in adjacency.get(node, ()):
            if (
                link.id == excluded_link_id
                or link.id in blocked
                or link.id in failed
                or not _link_carries(link, vlan_id)
            ):
                continue
            if link.l2_mode is LinkL2Mode.access and link.l2_access_vlan == vlan_id:
                return True
            for endpoint in link.endpoints:
                if endpoint not in visited and endpoint not in down_devices:
                    visited.add(endpoint)
                    queue.append(endpoint)
    return False


def _trunk_findings(
    twin: DigitalTwin,
    *,
    blocked: frozenset[str],
    failed: frozenset[str],
    down_devices: frozenset[str],
) -> tuple[Finding, ...]:
    access_vlans = tuple(
        sorted(
            {
                link.l2_access_vlan
                for link in twin.topology.links
                if link.l2_mode is LinkL2Mode.access
                and link.l2_access_vlan is not None
            }
        )
    )
    if not access_vlans:
        return ()
    adjacency = _adjacency(twin)
    findings: list[Finding] = []
    for trunk in sorted(twin.topology.links, key=lambda item: item.id):
        if trunk.l2_mode is not LinkL2Mode.trunk or trunk.id in failed:
            continue
        if any(endpoint in down_devices for endpoint in trunk.endpoints):
            continue
        allowed = set(trunk.l2_allowed_vlans)
        for vlan_id in access_vlans:
            if vlan_id in allowed:
                continue
            beyond = any(
                _reachable_access_vlan(
                    adjacency,
                    endpoint,
                    vlan_id,
                    excluded_link_id=trunk.id,
                    blocked=blocked,
                    failed=failed,
                    down_devices=down_devices,
                )
                for endpoint in trunk.endpoints
            )
            if beyond:
                findings.append(
                    _finding(
                        Severity.warning,
                        "l2_trunk_missing_downstream_vlan",
                        (trunk.id, _vlan_entity(vlan_id)),
                        (
                            f"Trunk {trunk.id} does not allow VLAN {vlan_id}, but an "
                            "access port for that VLAN is reachable beyond one "
                            "endpoint without crossing this trunk."
                        ),
                        (
                            f"Add VLAN {vlan_id} to l2_allowed_vlans on {trunk.id} "
                            "or remove the downstream access port."
                        ),
                    )
                )
    return tuple(findings)


def _reaches_any_switch(
    adjacency: dict[str, tuple[Link, ...]],
    start: str,
    vlan_id: int,
    targets: frozenset[str],
    *,
    blocked: frozenset[str],
    failed: frozenset[str],
    down_devices: frozenset[str],
) -> bool:
    if start in targets:
        return True
    if start in down_devices:
        return False
    visited = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for link in adjacency.get(node, ()):
            if (
                link.id in blocked
                or link.id in failed
                or not _link_carries(link, vlan_id)
            ):
                continue
            for endpoint in link.endpoints:
                if endpoint in targets:
                    return True
                if endpoint not in visited and endpoint not in down_devices:
                    visited.add(endpoint)
                    queue.append(endpoint)
    return False


def _carrying_switches(
    twin: DigitalTwin,
    vlan_id: int,
    *,
    blocked: frozenset[str],
    failed: frozenset[str],
    down_devices: frozenset[str],
) -> tuple[str, ...]:
    switches = _switch_device_ids(twin, down_devices)
    carrying = _usable_links(
        twin,
        vlan_id,
        blocked=blocked,
        failed=failed,
        down_devices=down_devices,
    )
    return tuple(
        sorted(
            {
                endpoint
                for link in carrying
                for endpoint in link.endpoints
                if endpoint in switches
            }
        )
    )


def _gateway_findings(
    twin: DigitalTwin,
    *,
    design: L2Design,
    planned: Sequence[int],
    blocked: frozenset[str],
    failed: frozenset[str],
    down_devices: frozenset[str],
) -> tuple[Finding, ...]:
    adjacency = _adjacency(twin)
    findings: list[Finding] = []
    for vlan_id in planned:
        gateway = design.gateway_by_vlan.get(vlan_id)
        if gateway is None:
            continue
        carrying = _carrying_switches(
            twin,
            vlan_id,
            blocked=blocked,
            failed=failed,
            down_devices=down_devices,
        )
        if not carrying:
            continue
        reached = _reaches_any_switch(
            adjacency,
            gateway,
            vlan_id,
            frozenset(carrying),
            blocked=blocked,
            failed=failed,
            down_devices=down_devices,
        )
        if not reached:
            findings.append(
                _finding(
                    Severity.error,
                    "l2_vlan_no_gateway_path",
                    (_vlan_entity(vlan_id), gateway, *carrying),
                    (
                        f"Modeled gateway {gateway} cannot reach any switch carrying "
                        f"VLAN {vlan_id} over links that carry that VLAN."
                    ),
                    (
                        f"Carry VLAN {vlan_id} on a path from {gateway} to a "
                        "switch carrying the VLAN."
                    ),
                )
            )
    return tuple(findings)


def _sprawl_findings(
    twin: DigitalTwin,
    *,
    design: L2Design,
    vlan_ids: Sequence[int],
    blocked: frozenset[str],
    failed: frozenset[str],
    down_devices: frozenset[str],
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for vlan_id in vlan_ids:
        carrying = _carrying_switches(
            twin,
            vlan_id,
            blocked=blocked,
            failed=failed,
            down_devices=down_devices,
        )
        if len(carrying) > design.vlan_spread_threshold:
            findings.append(
                _finding(
                    Severity.warning,
                    "l2_vlan_sprawl",
                    (_vlan_entity(vlan_id), *carrying),
                    (
                        f"VLAN {vlan_id} is modeled on {len(carrying)} switches, "
                        f"above the configured heuristic threshold of "
                        f"{design.vlan_spread_threshold}. This is a planning "
                        "guideline, not a protocol limit."
                    ),
                    (
                        "Review whether the VLAN needs this spread or raise the "
                        "documented threshold if it is intentional."
                    ),
                )
            )
    return tuple(findings)


def _loop_findings(loops: Sequence[LoopAnalysis]) -> tuple[Finding, ...]:
    return tuple(
        _finding(
            Severity.warning,
            "l2_loop_needs_blocking",
            (_vlan_entity(loop.vlan_id), *loop.blocked_link_ids, *loop.switch_ids),
            (
                f"VLAN {loop.vlan_id} has cycle rank {loop.cycle_count}; the "
                f"deterministic minimum spanning forest blocks "
                f"{', '.join(loop.blocked_link_ids) or 'no links'}."
            ),
            "Confirm the modeled blocking choice is intended for this design.",
        )
        for loop in loops
        if loop.cycle_count > 0
    )


def _bundle_review(
    twin: DigitalTwin,
    *,
    design: L2Design,
    failed: frozenset[str],
) -> tuple[tuple[BundleCapacity, ...], tuple[Finding, ...]]:
    link_ids = {link.id for link in twin.topology.links}
    capacities: list[BundleCapacity] = []
    findings: list[Finding] = []
    for bundle in design.etherchannel_bundles:
        capacity = bundle_capacity(bundle, twin.topology.links, failed)
        capacities.append(capacity)
        existing = tuple(
            member_id for member_id in capacity.member_link_ids if member_id in link_ids
        )
        if len(set(capacity.member_speeds_mbps)) > 1:
            speeds = ", ".join(f"{speed:g}" for speed in capacity.member_speeds_mbps)
            findings.append(
                _finding(
                    Severity.warning,
                    "l2_mismatched_bundle_speeds",
                    (bundle.id, *existing),
                    f"Bundle {bundle.id} mixes member capacities ({speeds} Mbps).",
                    "Group links with equal modeled capacities into one bundle.",
                )
            )
        if len(existing) < 2:
            findings.append(
                _finding(
                    Severity.warning,
                    "l2_single_member_bundle",
                    (bundle.id, *existing),
                    (
                        f"Bundle {bundle.id} has {len(existing)} existing member "
                        "link(s); missing link ids do not count as members."
                    ),
                    "Model at least two existing parallel links in the bundle.",
                )
            )
    return tuple(capacities), tuple(findings)


def analyze_l2_design(
    twin: DigitalTwin,
    *,
    plan: VlanPlanResult | None = None,
    design: L2Design | None = None,
    include_loops: bool = True,
) -> L2Analysis:
    """Review modeled Layer-2 design intent and return deterministic results.

    ``plan`` and ``design`` override the twin copies when supplied. Setting
    ``include_loops`` to False skips per-VLAN loop analysis, blocking, and
    loop findings while leaving the other design checks intact.
    """
    resolved_design = _resolve_design(twin, design)
    planned = _planned_vlan_ids(twin, plan)
    vlan_ids = _analysis_vlan_ids(twin, planned)
    failed = _failed_link_ids(twin)
    down_devices = _down_device_ids(twin)
    loops = (
        _loop_analyses(
            twin,
            design=resolved_design,
            vlan_ids=vlan_ids,
            failed=failed,
            down_devices=down_devices,
        )
        if include_loops
        else ()
    )
    blocked = _blocked_ids(loops)

    findings: list[Finding] = []
    findings.extend(_access_findings(twin, planned))
    findings.extend(
        _trunk_findings(
            twin,
            blocked=blocked,
            failed=failed,
            down_devices=down_devices,
        )
    )
    findings.extend(_native_findings(twin))
    findings.extend(
        _gateway_findings(
            twin,
            design=resolved_design,
            planned=planned,
            blocked=blocked,
            failed=failed,
            down_devices=down_devices,
        )
    )
    findings.extend(
        _sprawl_findings(
            twin,
            design=resolved_design,
            vlan_ids=vlan_ids,
            blocked=blocked,
            failed=failed,
            down_devices=down_devices,
        )
    )
    findings.extend(_loop_findings(loops))
    bundles, bundle_findings = _bundle_review(
        twin, design=resolved_design, failed=failed
    )
    findings.extend(bundle_findings)

    effective = tuple(
        sorted({link.id for link in twin.topology.links}.difference(blocked))
    )
    return L2Analysis(
        findings=tuple(findings),
        loops=loops,
        blocked_link_ids=blocked,
        effective_link_ids=effective,
        bundles=bundles,
    )


def effective_l2_blocked_links(
    twin: DigitalTwin, *, design: L2Design | None = None
) -> frozenset[str]:
    """Return the sorted-per-VLAN blocked link ids as a set.

    Failed/down links are excluded from loop analysis by their modeled state.
    """
    resolved_design = _resolve_design(twin, design)
    planned = _planned_vlan_ids(twin, None)
    loops = _loop_analyses(
        twin,
        design=resolved_design,
        vlan_ids=_analysis_vlan_ids(twin, planned),
        failed=_failed_link_ids(twin),
        down_devices=_down_device_ids(twin),
    )
    return frozenset(_blocked_ids(loops))


def links_carrying_vlan(
    twin: DigitalTwin,
    vlan_id: int,
    *,
    design: L2Design | None = None,
    blocked_link_ids: Iterable[str] = (),
) -> tuple[Link, ...]:
    """Return up, unblocked links that model ``vlan_id`` in link id order.

    A trunk carries the VLAN when it appears in ``l2_allowed_vlans``; an access
    link carries it when ``l2_access_vlan`` matches. ``design`` is accepted for
    API symmetry and does not affect this raw link filter. Device state is not
    considered here; graph reachability rules apply it in the analysis above.
    """
    del design
    blocked = set(blocked_link_ids)
    failed = _failed_link_ids(twin)
    return tuple(
        link
        for link in sorted(twin.topology.links, key=lambda item: item.id)
        if link.id not in blocked
        and link.id not in failed
        and _link_carries(link, vlan_id)
    )


__all__ = [
    "BundleCapacity",
    "L2Analysis",
    "LoopAnalysis",
    "analyze_l2_design",
    "bundle_capacity",
    "effective_l2_blocked_links",
    "links_carrying_vlan",
]
