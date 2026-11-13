"""Presentation-neutral row helpers for simulation results.

The functions return plain dictionaries so the Streamlit layer can render them
with its table and CSV helpers without the simulation package importing any UI
library. Ordering follows the evaluated state, which is deterministic.
"""

from __future__ import annotations

from .models import DemandEvaluation, NetworkState


def format_path(evaluation: DemandEvaluation) -> str:
    """Return a readable one-line path, or a reason when it is unserved."""
    if not evaluation.served:
        return f"Unserved: {evaluation.reason}"
    return " -> ".join(evaluation.path_device_ids)


def link_rows(state: NetworkState) -> list[dict[str, object]]:
    """Return one row per surviving link, in topology order."""
    rows: list[dict[str, object]] = []
    for link in state.links:
        rows.append(
            {
                "Link": link.link_id,
                "From": link.endpoints[0],
                "To": link.endpoints[1],
                "Directed": "yes" if link.directed else "no",
                "Capacity (Mbps)": round(link.capacity_mbps, 2),
                "Load (Mbps)": round(link.load_mbps, 2),
                "Utilization (%)": round(link.utilization_percent, 2),
                "Congestion": link.level.value,
                "Demands": ", ".join(link.demand_names) or "none",
            }
        )
    return rows


def demand_rows(state: NetworkState) -> list[dict[str, object]]:
    """Return one row per demand, in twin order."""
    rows: list[dict[str, object]] = []
    for demand in state.demands:
        rows.append(
            {
                "Demand": demand.name,
                "Source": demand.source,
                "Destination": demand.destination,
                "Bandwidth (Mbps)": round(demand.bandwidth_mbps, 2),
                "Served": "yes" if demand.served else "no",
                "Path": format_path(demand),
                "Cost": round(demand.total_cost, 2),
                "Hops": demand.hop_count,
                "Latency (ms)": (
                    round(demand.latency_ms, 2)
                    if demand.latency_ms is not None
                    else "not estimated"
                ),
            }
        )
    return rows


def unserved_rows(state: NetworkState) -> list[dict[str, object]]:
    """Return one row per unserved demand."""
    return [
        {
            "Demand": demand.name,
            "Source": demand.source,
            "Destination": demand.destination,
            "Bandwidth (Mbps)": round(demand.bandwidth_mbps, 2),
            "Reason": demand.reason,
        }
        for demand in state.unserved_demands
    ]


def metric_rows(before: NetworkState, after: NetworkState) -> list[dict[str, object]]:
    """Return before/after headline metrics with a numeric delta."""
    metrics: list[tuple[str, float, float, str]] = [
        (
            "Served demands",
            float(before.served_demand_count),
            float(after.served_demand_count),
            "",
        ),
        (
            "Served demand ratio (%)",
            before.served_demand_ratio * 100.0,
            after.served_demand_ratio * 100.0,
            "%",
        ),
        (
            "Unserved demands",
            float(len(before.unserved_demands)),
            float(len(after.unserved_demands)),
            "",
        ),
        (
            "Served bandwidth (Mbps)",
            before.served_demand_mbps,
            after.served_demand_mbps,
            "",
        ),
        (
            "Max utilization (%)",
            before.max_utilization_percent,
            after.max_utilization_percent,
            "%",
        ),
        (
            "Congested links",
            float(before.congested_link_count),
            float(after.congested_link_count),
            "",
        ),
        (
            "Overloaded links",
            float(before.overloaded_link_count),
            float(after.overloaded_link_count),
            "",
        ),
        (
            "Weak components",
            float(len(before.weak_components)),
            float(len(after.weak_components)),
            "",
        ),
        (
            "Disconnected devices",
            float(len(before.disconnected_devices)),
            float(len(after.disconnected_devices)),
            "",
        ),
    ]
    rows: list[dict[str, object]] = []
    for label, baseline, scenario, suffix in metrics:
        delta = scenario - baseline
        if suffix == "%":
            rendered = f"{delta:+.2f}%"
        else:
            rendered = f"{delta:+.0f}"
        rows.append(
            {
                "Metric": label,
                "Baseline": round(baseline, 2),
                "Scenario": round(scenario, 2),
                "Delta": rendered,
            }
        )
    return rows


def path_change_rows(
    before: NetworkState,
    after: NetworkState,
    *,
    only_changed: bool = False,
) -> list[dict[str, object]]:
    """Return per-demand path changes between two evaluated states."""
    before_by_name = {demand.name: demand for demand in before.demands}
    after_by_name = {demand.name: demand for demand in after.demands}
    ordered_names = [
        *(demand.name for demand in after.demands),
        *(demand.name for demand in before.demands if demand.name not in after_by_name),
    ]
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for name in ordered_names:
        if name in seen:
            continue
        seen.add(name)
        baseline = before_by_name.get(name)
        scenario = after_by_name.get(name)
        baseline_path = format_path(baseline) if baseline else "not present"
        scenario_path = format_path(scenario) if scenario else "not present"
        changed = baseline_path != scenario_path
        if only_changed and not changed:
            continue
        rows.append(
            {
                "Demand": name,
                "Baseline path": baseline_path,
                "Scenario path": scenario_path,
                "Changed": "yes" if changed else "no",
            }
        )
    return rows


__all__ = [
    "demand_rows",
    "format_path",
    "link_rows",
    "metric_rows",
    "path_change_rows",
    "unserved_rows",
]
