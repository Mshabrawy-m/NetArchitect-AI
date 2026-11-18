"""One deterministic design-health entry point for a digital twin.

Pages call :func:`build_design_health` instead of running individual validators.
The function reuses the existing engines and only adds categorization, ordering,
and coverage notes. Every number it uses comes from those engines.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from time import perf_counter

from core.exceptions import NetArchitectError
from core.schemas.validation import Finding, Severity
from digital_twin import (
    DigitalTwin,
    analysis_arguments,
    routing_arguments,
    validate_twin,
)
from network.analysis import spof_findings, spof_report
from network.routing import reachability_matrix
from simulation import CongestionLevel, NetworkState, evaluate

from .constraints import constraint_findings
from .models import (
    BASIC_CHECK_NOTE,
    CATEGORY_ORDER,
    EXPENSIVE_CHECK_NOTE,
    SKIPPED_EXPENSIVE_NOTE,
    CategoryFindings,
    DesignHealth,
    ValidationCategory,
    finding_sort_key,
)

_TWIN_CODE_CATEGORY: dict[str, ValidationCategory] = {
    "twin_schema_version_unsupported": ValidationCategory.schema,
    "twin_topology_disconnected": ValidationCategory.topology,
    "twin_demand_same_endpoint": ValidationCategory.topology,
    "twin_nonpositive_link_capacity": ValidationCategory.capacity,
    "twin_demand_limit_exceeded": ValidationCategory.capacity,
    "twin_duplicate_device_state": ValidationCategory.references,
    "twin_unknown_device_state": ValidationCategory.references,
    "twin_duplicate_link_state": ValidationCategory.references,
    "twin_unknown_link_state": ValidationCategory.references,
    "twin_duplicate_demand_name": ValidationCategory.references,
    "twin_demand_unknown_device": ValidationCategory.references,
    "twin_duplicate_assumption": ValidationCategory.references,
    "twin_duplicate_vlan_id": ValidationCategory.vlan,
    "twin_vlan_subnet_missing": ValidationCategory.vlan,
    "twin_dhcp_scope_network_missing": ValidationCategory.dhcp,
    "subnet_overlap": ValidationCategory.addressing,
    "duplicate_ip": ValidationCategory.addressing,
    "spof_device": ValidationCategory.redundancy,
    "spof_link": ValidationCategory.redundancy,
}


def categorize_twin_finding(finding: Finding) -> ValidationCategory:
    """Return the category for a finding produced by ``validate_twin``."""
    known = _TWIN_CODE_CATEGORY.get(finding.code)
    if known is not None:
        return known
    if finding.code.startswith(("subnet_", "duplicate_ip")):
        return ValidationCategory.addressing
    if finding.code.startswith("dhcp_"):
        return ValidationCategory.dhcp
    if "vlan" in finding.code:
        return ValidationCategory.vlan
    if finding.code.startswith("twin_schema"):
        return ValidationCategory.schema
    if finding.code.startswith("twin_nonpositive"):
        return ValidationCategory.capacity
    if finding.code.startswith("twin_topology"):
        return ValidationCategory.topology
    return ValidationCategory.references


def categorize_security_finding(finding: Finding) -> ValidationCategory:
    """Return the design-health category for a supplied security finding."""
    if finding.code.startswith(("SEC-", "POLICY-")):
        return ValidationCategory.security
    return categorize_twin_finding(finding)


def _check_failure(check: str, error: Exception) -> Finding:
    return Finding(
        severity=Severity.warning,
        code="design_check_failed",
        affected_entities=[],
        explanation=f"The {check} check could not run: {error}",
        remediation=(
            "Resolve the reported error, then rerun validation. Findings from the "
            "remaining checks are still shown."
        ),
    )


def _capacity_state(
    twin: DigitalTwin,
    groups: dict[ValidationCategory, list[Finding]],
) -> NetworkState | None:
    if any(link.capacity_mbps <= 0 for link in twin.topology.links):
        # The schema check already reports every non-positive capacity.
        return None
    try:
        return evaluate(twin)
    except (NetArchitectError, ValueError) as error:
        groups[ValidationCategory.capacity].append(
            _check_failure("capacity", error)
        )
        return None


def _capacity_findings(
    state: NetworkState,
    groups: dict[ValidationCategory, list[Finding]],
) -> None:
    for link in state.links:
        if link.level is CongestionLevel.overloaded:
            groups[ValidationCategory.capacity].append(
                Finding(
                    severity=Severity.error,
                    code="capacity_link_overloaded",
                    affected_entities=[link.link_id],
                    explanation=(
                        f"Link {link.link_id!r} is modeled at "
                        f"{link.utilization_percent:.1f}% utilization "
                        f"({link.load_mbps:.1f} of {link.capacity_mbps:.1f} Mbps), "
                        "above the overload threshold."
                    ),
                    remediation=(
                        "Add capacity, add a parallel link, or move traffic to a "
                        "less-loaded path."
                    ),
                )
            )
        elif link.level is CongestionLevel.critical:
            groups[ValidationCategory.capacity].append(
                Finding(
                    severity=Severity.warning,
                    code="capacity_link_critical",
                    affected_entities=[link.link_id],
                    explanation=(
                        f"Link {link.link_id!r} is modeled at "
                        f"{link.utilization_percent:.1f}% utilization, at or above "
                        "the critical threshold."
                    ),
                    remediation=(
                        "Plan additional capacity before load grows, or reroute "
                        "traffic."
                    ),
                )
            )


def _routing_findings(
    twin: DigitalTwin,
    state: NetworkState,
    groups: dict[ValidationCategory, list[Finding]],
) -> None:
    device_ids = {device.id for device in twin.topology.devices}
    for evaluation in state.demands:
        if evaluation.served:
            continue
        if evaluation.source not in device_ids or evaluation.destination not in device_ids:
            # Stale endpoints are reported by the reference check.
            continue
        reason = evaluation.reason or "no path exists in the modeled topology"
        groups[ValidationCategory.routing].append(
            Finding(
                severity=Severity.error,
                code="routing_demand_unreachable",
                affected_entities=[
                    evaluation.name,
                    evaluation.source,
                    evaluation.destination,
                ],
                explanation=(
                    f"Demand {evaluation.name!r} from {evaluation.source} to "
                    f"{evaluation.destination} is not served: {reason}."
                ),
                remediation=(
                    "Add links that connect the endpoints, restore failed "
                    "entities, or change the demand endpoints."
                ),
            )
        )


def _expensive_reachability(
    twin: DigitalTwin,
    groups: dict[ValidationCategory, list[Finding]],
) -> None:
    try:
        matrix = reachability_matrix(**routing_arguments(twin))  # type: ignore[arg-type]
    except (NetArchitectError, ValueError) as error:
        groups[ValidationCategory.routing].append(
            _check_failure("all-pairs reachability", error)
        )
        return
    if matrix.unreachable_pairs:
        groups[ValidationCategory.routing].append(
            Finding(
                severity=Severity.warning,
                code="routing_unreachable_pairs",
                affected_entities=list(matrix.excluded_device_ids),
                explanation=(
                    f"All-pairs reachability found {matrix.unreachable_pairs} "
                    "ordered device pair(s) with no directed path, excluding "
                    "modeled failures."
                ),
                remediation=(
                    "Add return paths for directed links or connect the affected "
                    "components."
                ),
            )
        )


def _expensive_redundancy(
    twin: DigitalTwin,
    groups: dict[ValidationCategory, list[Finding]],
) -> None:
    try:
        report = spof_report(**analysis_arguments(twin))  # type: ignore[arg-type]
    except (NetArchitectError, ValueError) as error:
        groups[ValidationCategory.redundancy].append(
            _check_failure("redundancy", error)
        )
        return
    groups[ValidationCategory.redundancy].extend(spof_findings(report))


def _summary(findings: Sequence[Finding]) -> str:
    if not findings:
        return "No design-health findings."
    counts = {severity: 0 for severity in Severity}
    for finding in findings:
        counts[finding.severity] += 1
    parts = [
        f"{counts[severity]} {severity.value}"
        for severity in (
            Severity.critical,
            Severity.error,
            Severity.warning,
            Severity.info,
        )
        if counts[severity]
    ]
    return f"{len(findings)} design-health finding(s): " + ", ".join(parts) + "."


def build_design_health(
    twin: DigitalTwin,
    *,
    include_expensive: bool = False,
    constraints: Sequence[str] | Iterable[str] = (),
    security_findings: Sequence[Finding] | Iterable[Finding] = (),
) -> DesignHealth:
    """Run every deterministic design check and return one categorized report.

    ``include_expensive`` adds all-pairs reachability and redundancy analysis.
    Those checks cost one Dijkstra search per device and one removal analysis
    per device and link, so they are opt-in. ``security_findings`` accepts
    findings copied from a design-time security analysis; they are basic checks
    and are included whether or not expensive checks run. ``constraints``
    accepts free-form requirement text; only the documented forms are
    machine-checked.
    """
    started = perf_counter()
    groups: dict[ValidationCategory, list[Finding]] = {
        category: [] for category in CATEGORY_ORDER
    }

    for finding in validate_twin(twin).findings:
        groups[categorize_twin_finding(finding)].append(finding)

    state = _capacity_state(twin, groups)
    if state is not None:
        _capacity_findings(state, groups)
        _routing_findings(twin, state, groups)

    if include_expensive:
        _expensive_reachability(twin, groups)
        _expensive_redundancy(twin, groups)

    groups[ValidationCategory.constraints].extend(
        constraint_findings(
            constraints,
            state=state,
            redundancy=groups[ValidationCategory.redundancy],
            include_expensive=include_expensive,
        )
    )
    for finding in security_findings:
        groups[categorize_security_finding(finding)].append(finding)

    items: list[tuple[ValidationCategory, Finding]] = [
        (category, finding)
        for category in CATEGORY_ORDER
        for finding in groups[category]
    ]
    items.sort(key=finding_sort_key)

    grouped = tuple(
        CategoryFindings(
            category=category,
            findings=tuple(
                finding for item_category, finding in items if item_category is category
            ),
        )
        for category in CATEGORY_ORDER
    )
    findings = tuple(finding for _, finding in items)
    notes = [BASIC_CHECK_NOTE]
    notes.append(EXPENSIVE_CHECK_NOTE if include_expensive else SKIPPED_EXPENSIVE_NOTE)

    return DesignHealth(
        findings=findings,
        groups=grouped,
        include_expensive=include_expensive,
        is_valid=not any(
            finding.severity in {Severity.error, Severity.critical}
            for finding in findings
        ),
        summary=_summary(findings),
        notes=tuple(notes),
        elapsed_seconds=perf_counter() - started,
    )


__all__ = [
    "build_design_health",
    "categorize_security_finding",
    "categorize_twin_finding",
]
