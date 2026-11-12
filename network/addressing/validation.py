"""Addressing validation findings.

Overlaps and duplicate addresses are returned as the project's existing
:class:`~core.schemas.validation.Finding` objects so they can be aggregated
with findings from other engines without a conversion layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field

from core.schemas.addressing import AddressType, Subnet
from core.schemas.validation import Finding, Severity, ValidationReport


class AddressAssignment(BaseModel):
    """An address assigned to a named entity (device, interface, or scope)."""

    entity: str = Field(min_length=1, description="Entity holding the address.")
    address: AddressType = Field(description="Assigned IP address.")


def detect_overlaps(subnets: Sequence[Subnet]) -> list[Finding]:
    """Return one finding per overlapping subnet pair.

    Touching blocks such as ``10.0.0.0/25`` and ``10.0.0.128/25`` do not
    overlap and produce no finding. IPv4 and IPv6 prefixes cannot overlap each
    other and are skipped pairwise.
    """
    findings: list[Finding] = []
    for index, subnet_a in enumerate(subnets):
        for subnet_b in subnets[index + 1 :]:
            if subnet_a.network.version != subnet_b.network.version:
                continue
            if not subnet_a.network.overlaps(subnet_b.network):
                continue
            findings.append(
                Finding(
                    severity=Severity.error,
                    code="subnet_overlap",
                    affected_entities=[subnet_a.name, subnet_b.name],
                    explanation=(
                        f"Subnet {subnet_a.name!r} ({subnet_a.network}) overlaps "
                        f"subnet {subnet_b.name!r} ({subnet_b.network})."
                    ),
                    remediation=(
                        "Reassign one subnet to a non-overlapping block or resize "
                        "the plan so no two prefixes share addresses."
                    ),
                )
            )
    return findings


def detect_duplicate_ips(assignments: Iterable[AddressAssignment]) -> list[Finding]:
    """Return one finding per address assigned to more than one entity."""
    by_address: dict[str, list[AddressAssignment]] = {}
    for assignment in assignments:
        by_address.setdefault(str(assignment.address), []).append(assignment)

    findings: list[Finding] = []
    for address in sorted(by_address):
        holders = by_address[address]
        if len(holders) < 2:
            continue
        findings.append(
            Finding(
                severity=Severity.error,
                code="duplicate_ip",
                affected_entities=[holder.entity for holder in holders],
                explanation=(
                    f"Address {address} is assigned to {len(holders)} entities: "
                    + ", ".join(holder.entity for holder in holders)
                    + "."
                ),
                remediation=(
                    "Assign a unique address to each entity, or release the "
                    "duplicate from all but one holder."
                ),
            )
        )
    return findings


def validate_addressing(
    subnets: Sequence[Subnet],
    assignments: Iterable[AddressAssignment] = (),
) -> ValidationReport:
    """Combine overlap and duplicate-address findings into one report."""
    findings = detect_overlaps(subnets)
    findings.extend(detect_duplicate_ips(assignments))
    is_valid = not any(
        finding.severity in {Severity.error, Severity.critical} for finding in findings
    )
    if findings:
        summary = f"{len(findings)} addressing finding(s)."
    else:
        summary = "No addressing findings."
    return ValidationReport(findings=findings, is_valid=is_valid, summary=summary)
