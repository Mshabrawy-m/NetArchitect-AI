"""Deterministic explanation templates for report sections.

Every function returns prose built only from values the caller passed in. A
template never looks up a number, never estimates one, and never contains a
literal digit, so the consistency checker can trace each printed number back to
a :class:`~services.reporting.models.ValueRecord`.

The wording is deliberately restrained: these are engineering summaries of
computed data, not marketing copy.
"""

from __future__ import annotations

from .models import DISCLOSURE_TEXT


def architecture_summary(
    *,
    twin_name: str,
    device_count: str,
    link_count: str,
    site_count: str,
    demand_count: str,
    connected: bool,
    spof_count: str,
) -> str:
    """Summarize the twin at a glance."""
    connectivity = (
        "The physical topology forms a single connected component."
        if connected
        else "The physical topology is split into multiple components."
    )
    return (
        f"The digital twin {twin_name} models {device_count} devices connected "
        f"by {link_count} links across {site_count} sites, with "
        f"{demand_count} modeled traffic demands. {connectivity} "
        f"{spof_count} device or link removals would increase the component "
        f"count. Every quantity is a modeled estimate from the stored design."
    )


def topology_rationale(
    *,
    device_count: str,
    link_count: str,
    site_count: str,
    connected: bool,
    workflow_steps: str,
) -> str:
    """Explain how the stored topology is structured."""
    shape = (
        "All devices lie in one connected component, so every device has a "
        "modeled path to every other device."
        if connected
        else "At least one device is outside the largest connected component; "
        "the routing and analytics sections report the resulting "
        "unreachable pairs."
    )
    workflow_note = (
        f"The structured workflow recorded {workflow_steps} completed steps "
        f"and produced this topology from the structured requirements."
        if workflow_steps
        else "No agent workflow is attached to this report, so the rationale "
        "below is limited to the structural facts of the stored twin."
    )
    return (
        f"The twin contains {device_count} devices, {link_count} links, and "
        f"{site_count} sites. {shape} {workflow_note} Site and device-type "
        f"distributions are listed below; they are counts of stored model "
        f"objects, not measurements."
    )


def addressing_summary(
    *,
    subnet_count: str,
    vlan_subnet_count: str,
    standalone_subnet_count: str,
) -> str:
    """Summarize the stored addressing plan."""
    return (
        f"The addressing plan contains {subnet_count} subnets: "
        f"{vlan_subnet_count} attached to VLANs and {standalone_subnet_count} "
        f"standalone. Prefixes are copied from the validated addressing plan; "
        f"the report does not re-allocate or resize them."
    )


def vlan_dhcp_summary(
    *,
    vlan_count: str,
    dhcp_count: str,
) -> str:
    """Summarize VLAN assignments and DHCP scopes."""
    return (
        f"The twin stores {vlan_count} department-to-VLAN assignments and "
        f"{dhcp_count} DHCP scopes. VLAN identifiers and lease durations are "
        f"copied from the validated plan; no device configuration is applied."
    )


def routing_summary(
    *,
    source: str,
    device_count: str,
    unreachable_pairs: str,
    entry_count: str,
) -> str:
    """Summarize reachability and one routing table."""
    return (
        f"Reachability is evaluated over {device_count} devices on the modeled "
        f"graph. {unreachable_pairs} ordered device pairs have no directed "
        f"path. The routing table shown for source {source} contains "
        f"{entry_count} entries, selected by the deterministic lowest-cost "
        f"path with a lexicographic tie-break."
    )


def graph_summary(
    *,
    component_count: str,
    critical_device_count: str,
    critical_link_count: str,
    connected: bool,
) -> str:
    """Summarize structural analysis and single points of failure."""
    state = (
        "the topology is fully connected"
        if connected
        else "the topology is not fully connected"
    )
    return (
        f"Structural analysis finds {component_count} connected components; "
        f"{state}. {critical_device_count} devices and {critical_link_count} "
        f"links are single points of failure: removing one increases the "
        f"component count. These are design-time structural indicators, not "
        f"availability measurements."
    )


def simulation_summary(
    *,
    scenario_name: str,
    baseline_served: str,
    scenario_served: str,
    max_utilization_delta: str,
    recovery_available: bool,
) -> str:
    """Summarize a before/after what-if comparison."""
    recovery = (
        "A recovery path is available for the modeled failure."
        if recovery_available
        else "No recovery path is available for the modeled failure."
    )
    return (
        f"Scenario {scenario_name} compares the baseline with the changed "
        f"twin under identical assumptions. Served demands move from "
        f"{baseline_served} to {scenario_served}, and the maximum modeled link "
        f"utilization changes by {max_utilization_delta} percentage points. "
        f"{recovery} Values are modeled estimates; the model routes each "
        f"demand on one lowest-cost path without ECMP."
    )


def optimization_summary(
    *,
    algorithm: str,
    seed: str,
    evaluations: str,
    best_available: bool,
) -> str:
    """Summarize one bounded optimization run."""
    outcome = (
        "A feasible best candidate was found under the configured weighted "
        "score."
        if best_available
        else "No evaluated candidate satisfied every hard constraint, so no "
        "best candidate is reported."
    )
    return (
        f"The {algorithm} search used seed {seed} and evaluated "
        f"{evaluations} candidates against the unmodified baseline twin. "
        f"{outcome} The search is bounded; the result is the best candidate "
        f"found within the configured limits, not a proof of a global optimum."
    )


def trace_summary(
    *,
    task_count: str,
    trace_count: str,
    stop_reason: str,
) -> str:
    """Summarize a workflow execution trace."""
    return (
        f"The workflow executed {task_count} tasks and recorded {trace_count} "
        f"trace events. It stopped with reason {stop_reason}. Summaries in the "
        f"trace redact credential-looking fields and truncate long payloads."
    )


def assumptions_summary(*, count: str) -> str:
    """Introduce the assumptions section."""
    if count == "0":
        return (
            "No assumptions are recorded in the twin or the selected engine "
            "runs. This means the report cannot state what was assumed, not "
            "that no assumption was made."
        )
    return (
        f"{count} assumptions are recorded across the twin and the selected "
        f"engine runs. They are reproduced as recorded; the report does not "
        f"add or infer assumptions."
    )


LIMITATIONS: tuple[str, ...] = (
    (
        "All utilization, demand, latency, and cost figures are modeled estimates "
        "from stated assumptions. They are not measurements from live equipment."
    ),
    DISCLOSURE_TEXT,
    (
        "Simulation routes each demand on one deterministic lowest-cost path. It "
        "does not model packet behavior, queueing, ECMP, or hardware throughput."
    ),
    (
        "Structural metrics are design-time indicators derived from the stored "
        "topology. They do not establish real-world availability or resilience."
    ),
    (
        "Optimization is a bounded deterministic search. The reported candidate is "
        "the best found within the configured limits, not a proven global optimum."
    ),
    (
        "Configuration templates are generated from validated twin data only. They "
        "are not applied to any device, and the platform never connects to network "
        "equipment."
    ),
    (
        "Optional AI-written prose is labelled and is never used as a source of "
        "design values. Any numeric token that does not match a computed value "
        "causes the text to be rejected."
    ),
)


__all__ = [
    "LIMITATIONS",
    "addressing_summary",
    "architecture_summary",
    "assumptions_summary",
    "graph_summary",
    "optimization_summary",
    "routing_summary",
    "simulation_summary",
    "topology_rationale",
    "trace_summary",
    "vlan_dhcp_summary",
]
