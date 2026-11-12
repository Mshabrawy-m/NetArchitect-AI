"""Cross-part validation for a digital twin.

Validation reuses the existing addressing, DHCP, and topology validators and
adds only the cross-checks that no single part can perform:

* stored device/link states must reference real entities;
* traffic demands must reference real devices and have unique names;
* VLAN planner assignments must exist in the addressing plan;
* DHCP scope networks should map to an addressed subnet;
* the twin schema version must be one this build understands.

Stale references are reported as findings instead of being pruned. That keeps
a topology change from silently leaving an inconsistent twin: the Digital Twin
page and the Topology Editor show the findings until the user resolves them.
"""

from __future__ import annotations

from collections.abc import Sequence

from config.limits import MAX_DEMANDS
from core.schemas.addressing import AddressingPlan, Subnet
from core.schemas.validation import Finding, Severity, ValidationReport
from network.addressing.validation import validate_addressing
from network.topology import analyze_connectivity
from network.vlan import validate_dhcp_scope

from .models import TWIN_SCHEMA_VERSION, DigitalTwin

_SEVERITY_ORDER = {
    Severity.critical: 0,
    Severity.error: 1,
    Severity.warning: 2,
    Severity.info: 3,
}


def addressing_subnets(addressing: AddressingPlan) -> list[Subnet]:
    """Return every subnet in an addressing plan, VLAN-tagged first."""
    subnets: list[Subnet] = []
    for vlan_plan in addressing.vlan_plans:
        subnets.extend(vlan_plan.subnets)
    subnets.extend(addressing.subnets)
    return subnets


def _ordered(findings: Sequence[Finding]) -> list[Finding]:
    """Return findings in a deterministic severity/code/entity order."""
    return sorted(
        findings,
        key=lambda finding: (
            _SEVERITY_ORDER[finding.severity],
            finding.code,
            tuple(finding.affected_entities),
            finding.explanation,
        ),
    )


def validate_twin(twin: DigitalTwin) -> ValidationReport:
    """Return a validation report for the complete twin.

    ``is_valid`` is false only when a finding is an error or critical. Warnings
    and informational findings describe drift that the user should review.
    """
    findings: list[Finding] = []

    if twin.metadata.schema_version != TWIN_SCHEMA_VERSION:
        findings.append(
            Finding(
                severity=Severity.error,
                code="twin_schema_version_unsupported",
                affected_entities=[],
                explanation=(
                    f"Twin schema version {twin.metadata.schema_version} is not "
                    f"supported; this build supports version {TWIN_SCHEMA_VERSION}."
                ),
                remediation="Re-import a twin produced by a supported application version.",
            )
        )

    device_ids = {device.id for device in twin.topology.devices}
    link_ids = {link.id for link in twin.topology.links}

    seen_devices: set[str] = set()
    for entry in twin.device_states:
        if entry.device_id in seen_devices:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="twin_duplicate_device_state",
                    affected_entities=[entry.device_id],
                    explanation=(
                        f"Device {entry.device_id!r} has more than one stored state."
                    ),
                    remediation="Keep one state entry per device.",
                )
            )
        seen_devices.add(entry.device_id)
        if entry.device_id not in device_ids:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="twin_unknown_device_state",
                    affected_entities=[entry.device_id],
                    explanation=(
                        f"Stored state references device {entry.device_id!r}, which "
                        "is not in the twin topology."
                    ),
                    remediation=(
                        "Remove the stale state entry or restore the device in the "
                        "topology."
                    ),
                )
            )

    seen_links: set[str] = set()
    for entry in twin.link_states:
        if entry.link_id in seen_links:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="twin_duplicate_link_state",
                    affected_entities=[entry.link_id],
                    explanation=(
                        f"Link {entry.link_id!r} has more than one stored state."
                    ),
                    remediation="Keep one state entry per link.",
                )
            )
        seen_links.add(entry.link_id)
        if entry.link_id not in link_ids:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="twin_unknown_link_state",
                    affected_entities=[entry.link_id],
                    explanation=(
                        f"Stored state references link {entry.link_id!r}, which is "
                        "not in the twin topology."
                    ),
                    remediation=(
                        "Remove the stale state entry or restore the link in the "
                        "topology."
                    ),
                )
            )

    seen_demands: set[str] = set()
    for demand in twin.demands:
        if demand.name in seen_demands:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="twin_duplicate_demand_name",
                    affected_entities=[demand.name],
                    explanation=f"Traffic demand name {demand.name!r} is repeated.",
                    remediation="Give every traffic demand a unique name.",
                )
            )
        seen_demands.add(demand.name)
        unknown = sorted(
            {demand.source, demand.destination} - device_ids
        )
        if unknown:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="twin_demand_unknown_device",
                    affected_entities=[demand.name, *unknown],
                    explanation=(
                        f"Demand {demand.name!r} references device(s) not in the "
                        f"topology: {', '.join(unknown)}."
                    ),
                    remediation=(
                        "Update the demand endpoints or restore the devices in the "
                        "topology."
                    ),
                )
            )
        if demand.source == demand.destination:
            findings.append(
                Finding(
                    severity=Severity.warning,
                    code="twin_demand_same_endpoint",
                    affected_entities=[demand.name, demand.source],
                    explanation=(
                        f"Demand {demand.name!r} has the same source and destination."
                    ),
                    remediation="Use distinct source and destination devices.",
                )
            )
    if len(twin.demands) > MAX_DEMANDS:
        findings.append(
            Finding(
                severity=Severity.error,
                code="twin_demand_limit_exceeded",
                affected_entities=[],
                explanation=(
                    f"The twin has {len(twin.demands)} demands; the limit is "
                    f"{MAX_DEMANDS}."
                ),
                remediation="Remove unused demands before adding more.",
            )
        )

    for link in twin.topology.links:
        if link.capacity_mbps <= 0:
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="twin_nonpositive_link_capacity",
                    affected_entities=[link.id],
                    explanation=(
                        f"Link {link.id!r} has capacity {link.capacity_mbps} Mbps; "
                        "capacity must be greater than zero."
                    ),
                    remediation="Set a positive link capacity.",
                )
            )

    if twin.topology.devices:
        connectivity = analyze_connectivity(twin.topology)
        if not connectivity.is_connected:
            findings.append(
                Finding(
                    severity=Severity.warning,
                    code="twin_topology_disconnected",
                    affected_entities=list(connectivity.isolated_device_ids),
                    explanation=(
                        f"The twin topology has {connectivity.component_count} "
                        "connected components."
                    ),
                    remediation=(
                        "Add links so every modeled device is reachable, or confirm "
                        "that the partition is intentional."
                    ),
                )
            )

    addressing: AddressingPlan | None = twin.addressing
    addressed_networks: set[object] = set()
    if addressing is not None:
        subnets = addressing_subnets(addressing)
        addressed_networks = {subnet.network for subnet in subnets}
        findings.extend(validate_addressing(subnets).findings)

    vlan_plan = twin.vlan_plan
    if vlan_plan is not None:
        seen_vlan_ids: set[int] = set()
        for assignment in vlan_plan.assignments:
            if assignment.vlan_id in seen_vlan_ids:
                findings.append(
                    Finding(
                        severity=Severity.error,
                        code="twin_duplicate_vlan_id",
                        affected_entities=[str(assignment.vlan_id)],
                        explanation=(
                            f"VLAN id {assignment.vlan_id} is assigned to more than "
                            "one department."
                        ),
                        remediation="Assign a unique VLAN id to each department.",
                    )
                )
            seen_vlan_ids.add(assignment.vlan_id)
            if addressing is not None and assignment.network not in addressed_networks:
                findings.append(
                    Finding(
                        severity=Severity.warning,
                        code="twin_vlan_subnet_missing",
                        affected_entities=[
                            assignment.department,
                            assignment.subnet_name,
                        ],
                        explanation=(
                            f"VLAN {assignment.vlan_id} subnet "
                            f"{assignment.network} is not present in the addressing "
                            "plan."
                        ),
                        remediation=(
                            "Rebuild the addressing plan so every VLAN subnet exists, "
                            "or remove the stale VLAN assignment."
                        ),
                    )
                )

    for scope in twin.dhcp_scopes:
        findings.extend(validate_dhcp_scope(scope))
        if addressing is not None and scope.network not in addressed_networks:
            findings.append(
                Finding(
                    severity=Severity.warning,
                    code="twin_dhcp_scope_network_missing",
                    affected_entities=[scope.name],
                    explanation=(
                        f"DHCP scope {scope.name!r} uses network {scope.network}, "
                        "which is not present in the addressing plan."
                    ),
                    remediation=(
                        "Add the subnet to the addressing plan or remove the stale "
                        "scope."
                    ),
                )
            )

    seen_assumptions: set[str] = set()
    for assumption in twin.assumptions:
        if assumption.id in seen_assumptions:
            findings.append(
                Finding(
                    severity=Severity.warning,
                    code="twin_duplicate_assumption",
                    affected_entities=[assumption.id],
                    explanation=(
                        f"Assumption id {assumption.id!r} is repeated."
                    ),
                    remediation="Give every assumption a unique id.",
                )
            )
        seen_assumptions.add(assumption.id)

    ordered = _ordered(findings)
    is_valid = not any(
        finding.severity in {Severity.error, Severity.critical}
        for finding in ordered
    )
    if ordered:
        summary = f"{len(ordered)} digital-twin finding(s)."
    else:
        summary = "No digital-twin findings."
    return ValidationReport(findings=ordered, is_valid=is_valid, summary=summary)
