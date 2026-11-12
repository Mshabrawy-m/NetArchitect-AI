"""Machine-readable findings derived from structural analysis."""

from __future__ import annotations

from core.schemas.validation import Finding, Severity

from .metrics import ComponentAnalysis
from .spof import SpofEntry, SpofReport


def _isolated_phrase(entry: SpofEntry) -> str:
    if not entry.isolated_device_ids:
        return "No device becomes isolated."
    return (
        "Isolated device(s): "
        + ", ".join(entry.isolated_device_ids)
        + "."
    )


def spof_findings(report: SpofReport) -> list[Finding]:
    """Return one critical finding per single point of failure.

    A device finding lists the device plus any devices that become isolated.
    A link finding lists the link plus its endpoints. Codes are stable:
    ``spof_device`` and ``spof_link``.
    """
    findings: list[Finding] = []
    for entry in report.entries:
        if entry.kind == "device":
            findings.append(
                Finding(
                    severity=Severity.critical,
                    code="spof_device",
                    affected_entities=[
                        entry.entity_id,
                        *entry.isolated_device_ids,
                    ],
                    explanation=(
                        f"Removing device {entry.entity_id} raises the "
                        f"connected-component count from "
                        f"{report.baseline_component_count} to "
                        f"{entry.components_after_removal}. "
                        f"{_isolated_phrase(entry)}"
                    ),
                    remediation=(
                        "Add an independent path through the affected section "
                        "or dual-home devices that depend on this device."
                    ),
                )
            )
        else:
            endpoints = " - ".join(entry.endpoints)
            findings.append(
                Finding(
                    severity=Severity.critical,
                    code="spof_link",
                    affected_entities=[
                        entry.entity_id,
                        *entry.endpoints,
                    ],
                    explanation=(
                        f"Removing link {entry.entity_id} ({endpoints}) raises "
                        f"the connected-component count from "
                        f"{report.baseline_component_count} to "
                        f"{entry.components_after_removal}. "
                        f"{_isolated_phrase(entry)}"
                    ),
                    remediation=(
                        f"Provision a parallel or alternate path between "
                        f"{endpoints}."
                    ),
                )
            )
    return findings


def analysis_findings(
    report: SpofReport,
    components: ComponentAnalysis,
) -> list[Finding]:
    """Return SPOF findings plus connectivity warnings.

    The extra warnings are informational for the design review; they do not
    replace the per-entity critical findings.
    """
    findings = spof_findings(report)
    if components.component_count > 1:
        findings.append(
            Finding(
                severity=Severity.warning,
                code="topology_disconnected",
                affected_entities=[],
                explanation=(
                    f"The physical topology has "
                    f"{components.component_count} connected components; "
                    f"devices in different components cannot reach each "
                    f"other."
                ),
                remediation=(
                    "Add links between the components or confirm that the "
                    "separation is intentional."
                ),
            )
        )
    for device_id in components.isolated_device_ids:
        findings.append(
            Finding(
                severity=Severity.warning,
                code="isolated_device",
                affected_entities=[device_id],
                explanation=(
                    f"Device {device_id} has no links and cannot participate "
                    f"in forwarding."
                ),
                remediation=(
                    "Connect the device to the topology or remove it from the "
                    "design."
                ),
            )
        )
    return findings
