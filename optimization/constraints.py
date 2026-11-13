"""Hard-constraint checks for optimization candidates.

Constraints are evaluated separately from objectives. A candidate that fails
any enforced constraint is infeasible and is never eligible for recommendation.
"""

from __future__ import annotations

from simulation.models import NetworkState

from .models import CandidateMetrics, ConstraintResult, HardConstraints


def _result(
    name: str,
    *,
    enforced: bool,
    passed: bool,
    actual: float | None,
    threshold: float | None,
    unit: str,
    detail: str,
) -> ConstraintResult:
    return ConstraintResult(
        name=name,
        enforced=enforced,
        passed=passed if enforced else True,
        actual=actual,
        threshold=threshold,
        unit=unit,
        detail=detail,
    )


def evaluate_constraints(
    state: NetworkState,
    metrics: CandidateMetrics,
    constraints: HardConstraints,
) -> tuple[ConstraintResult, ...]:
    """Return one typed result per hard constraint, including skipped ones."""
    results: list[ConstraintResult] = []

    connectivity_ok = (
        metrics.weak_component_count <= 1
        and metrics.disconnected_device_count == 0
        and len(state.isolated_devices) == 0
    )
    results.append(
        _result(
            "connectivity",
            enforced=constraints.require_connectivity,
            passed=connectivity_ok,
            actual=float(metrics.weak_component_count),
            threshold=1.0,
            unit="weak components",
            detail=(
                "All devices must share one weak component with no isolated "
                "device."
            ),
        )
    )

    if constraints.min_served_demand_ratio is None:
        results.append(
            _result(
                "served_demand_ratio",
                enforced=False,
                passed=True,
                actual=metrics.served_demand_ratio,
                threshold=None,
                unit="ratio",
                detail="Served-demand ratio constraint is disabled.",
            )
        )
    else:
        # A twin with no demands has no service requirement to violate.
        ratio_ok = (
            metrics.demand_count == 0
            or metrics.served_demand_ratio + 1e-12
            >= constraints.min_served_demand_ratio
        )
        results.append(
            _result(
                "served_demand_ratio",
                enforced=True,
                passed=ratio_ok,
                actual=metrics.served_demand_ratio,
                threshold=constraints.min_served_demand_ratio,
                unit="ratio",
                detail="Served demands divided by total demands.",
            )
        )

    if constraints.max_utilization_percent is None:
        results.append(
            _result(
                "max_utilization",
                enforced=False,
                passed=True,
                actual=metrics.max_utilization_percent,
                threshold=None,
                unit="percent",
                detail="Maximum-utilization constraint is disabled.",
            )
        )
    else:
        results.append(
            _result(
                "max_utilization",
                enforced=True,
                passed=(
                    metrics.max_utilization_percent
                    <= constraints.max_utilization_percent + 1e-12
                ),
                actual=metrics.max_utilization_percent,
                threshold=constraints.max_utilization_percent,
                unit="percent",
                detail="Highest modeled link utilization.",
            )
        )

    if constraints.max_budget_proxy is None:
        results.append(
            _result(
                "budget",
                enforced=False,
                passed=True,
                actual=metrics.infrastructure_cost_proxy,
                threshold=None,
                unit="modeled cost units",
                detail="Budget constraint is disabled.",
            )
        )
    else:
        results.append(
            _result(
                "budget",
                enforced=True,
                passed=(
                    metrics.infrastructure_cost_proxy
                    <= constraints.max_budget_proxy + 1e-9
                ),
                actual=metrics.infrastructure_cost_proxy,
                threshold=constraints.max_budget_proxy,
                unit="modeled cost units",
                detail="Infrastructure cost proxy must not exceed the cap.",
            )
        )

    results.append(
        _result(
            "max_nodes",
            enforced=True,
            passed=metrics.device_count <= constraints.max_nodes,
            actual=float(metrics.device_count),
            threshold=float(constraints.max_nodes),
            unit="devices",
            detail="Candidate device count must stay within the node limit.",
        )
    )
    results.append(
        _result(
            "max_edges",
            enforced=True,
            passed=metrics.link_count <= constraints.max_edges,
            actual=float(metrics.link_count),
            threshold=float(constraints.max_edges),
            unit="links",
            detail="Candidate link count must stay within the edge limit.",
        )
    )

    if constraints.min_edge_disjoint_paths is None:
        results.append(
            _result(
                "redundancy",
                enforced=False,
                passed=True,
                actual=metrics.min_edge_disjoint_paths,
                threshold=None,
                unit="paths",
                detail="Redundancy constraint is disabled.",
            )
        )
    else:
        actual = metrics.min_edge_disjoint_paths
        if metrics.demand_count == 0:
            passed = True
        else:
            passed = (
                actual is not None
                and actual >= constraints.min_edge_disjoint_paths
            )
        results.append(
            _result(
                "redundancy",
                enforced=True,
                passed=passed,
                actual=None if actual is None else float(actual),
                threshold=float(constraints.min_edge_disjoint_paths),
                unit="edge-disjoint paths",
                detail=(
                    "Every demand endpoint pair needs at least this many "
                    "physical-link-disjoint paths."
                ),
            )
        )

    return tuple(results)


__all__ = ["evaluate_constraints"]
