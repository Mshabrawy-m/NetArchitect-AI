"""S5: fixed, versioned design checklist derived only from modeled facts.

The checklist is data, not advice from a language model and not a compliance
assessment. Each item has a stable ``ID``, fixed text, explicit links to the rule
or finding codes that can change its status, and a short evidence tuple. The
three allowed statuses are ``pass``, ``fail``, and ``not-modeled``.

``not-modeled`` is used whenever the design model has no fact for an item. In
particular the security model has no logging field at all, so the logging item
is always ``not-modeled``; an absent logging configuration is never reported as
a pass or a failure. The wording is deliberately limited to "design checklist
aligned with common practice (design-level)" and makes no compliance claim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import (
    DESIGN_CHECKLIST_VERSION,
    ChecklistStatus,
    DesignChecklist,
    DesignChecklistItem,
    FlowVerdict,
    PolicyAction,
    ZoneType,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin

    from .models import SecurityAnalysis, SecurityModel

_LOWER_TRUST = frozenset(
    {ZoneType.untrusted_external, ZoneType.guest, ZoneType.iot}
)
_HIGH_CRITICALITY = 4


def _item(
    identifier: str,
    text: str,
    linkage: tuple[str, ...],
    status: ChecklistStatus,
    evidence: str,
) -> DesignChecklistItem:
    """Build one checklist item with a single deterministic evidence string."""
    return DesignChecklistItem(
        id=identifier,
        text=text,
        rule_linkage=linkage,
        status=status,
        evidence=(evidence,),
    )


def build_design_checklist(
    twin: DigitalTwin,
    analysis: SecurityAnalysis,
) -> DesignChecklist:
    """Evaluate the fixed checklist against one deterministic analysis result."""
    model: SecurityModel = analysis.model
    codes = {finding.code for finding in analysis.findings}
    zones = model.zones
    items: list[DesignChecklistItem] = []

    items.append(
        _item(
            "CHK-01",
            "An explicit default deny is modeled for unmatched inter-zone flows.",
            ("POLICY-DEFAULT-ALLOW",),
            (
                ChecklistStatus.fail
                if "POLICY-DEFAULT-ALLOW" in codes
                else ChecklistStatus.pass_
            ),
            f"model.default_action={model.default_action.value}",
        )
    )

    device_count = len(twin.topology.devices)
    if device_count == 0:
        items.append(
            _item(
                "CHK-02",
                "Every topology device is assigned to a modeled zone.",
                ("SEC-DW-008",),
                ChecklistStatus.not_modeled,
                "No topology devices are modeled.",
            )
        )
    else:
        items.append(
            _item(
                "CHK-02",
                "Every topology device is assigned to a modeled zone.",
                ("SEC-DW-008",),
                ChecklistStatus.fail if "SEC-DW-008" in codes else ChecklistStatus.pass_,
                f"topology_devices={device_count}",
            )
        )

    any_allow_rules = tuple(
        rule.id
        for rule in model.rules
        if rule.enabled and rule.any_service and rule.action is PolicyAction.allow
    )
    items.append(
        _item(
            "CHK-03",
            "No enabled rule allows any service across a zone boundary.",
            ("POLICY-ANY-ALLOW",),
            ChecklistStatus.fail if any_allow_rules else ChecklistStatus.pass_,
            f"any_service_allow_rules={len(any_allow_rules)}",
        )
    )

    lower_trust = any(zone.type in _LOWER_TRUST for zone in zones)
    high_criticality = any(
        zone.criticality >= _HIGH_CRITICALITY for zone in zones
    )
    exposure_count = (
        len(analysis.reachability.exposure_findings)
        if analysis.reachability is not None
        else 0
    )
    if not lower_trust or not high_criticality:
        exposure_status = ChecklistStatus.not_modeled
        exposure_evidence = (
            f"lower_trust_zones={lower_trust}, high_criticality_zones={high_criticality}"
        )
    else:
        exposure_status = (
            ChecklistStatus.fail if exposure_count else ChecklistStatus.pass_
        )
        exposure_evidence = f"exposure_findings={exposure_count}"
    items.append(
        _item(
            "CHK-04",
            "Lower-trust zones are not modeled as reaching criticality >= 4 zones by policy.",
            ("REACH-EXPOSURE-HIGH-CRITICALITY", "SEC-DW-005"),
            exposure_status,
            exposure_evidence,
        )
    )

    items.append(
        _item(
            "CHK-05",
            "Policy decision logging is modeled in this design.",
            (),
            ChecklistStatus.not_modeled,
            "The security design model has no logging field; absence is not a pass or fail.",
        )
    )

    if not analysis.flow_checks:
        flow_status = ChecklistStatus.not_modeled
        flow_evidence = "flows_modeled=0"
    else:
        denied = sum(
            check.verdict is not FlowVerdict.allowed for check in analysis.flow_checks
        )
        flow_status = ChecklistStatus.fail if denied else ChecklistStatus.pass_
        flow_evidence = (
            f"flows_checked={len(analysis.flow_checks)}, not_allowed={denied}"
        )
    items.append(
        _item(
            "CHK-06",
            "Modeled flows have a route and are permitted by policy.",
            ("POLICY-FLOW-DENIED",),
            flow_status,
            flow_evidence,
        )
    )

    high_zones = tuple(
        zone for zone in zones if zone.criticality >= _HIGH_CRITICALITY
    )
    if len(high_zones) < 2:
        separation_status = ChecklistStatus.not_modeled
        separation_evidence = f"high_criticality_zones={len(high_zones)}"
    else:
        separation_status = (
            ChecklistStatus.fail if "SEC-DW-009" in codes else ChecklistStatus.pass_
        )
        separation_evidence = f"high_criticality_zones={len(high_zones)}"
    items.append(
        _item(
            "CHK-07",
            "High-criticality zones are separated by explicit modeled deny rules.",
            ("SEC-DW-009",),
            separation_status,
            separation_evidence,
        )
    )

    known = {service.name for service in model.services}
    unknown_refs = tuple(
        rule.id
        for rule in model.rules
        if not rule.any_service and any(name not in known for name in rule.services)
    )
    if not model.rules:
        service_status = ChecklistStatus.not_modeled
    else:
        service_status = (
            ChecklistStatus.fail if unknown_refs else ChecklistStatus.pass_
        )
    items.append(
        _item(
            "CHK-08",
            "Every rule service reference names a modeled service.",
            (),
            service_status,
            f"unknown_service_refs={len(unknown_refs)}",
        )
    )

    return DesignChecklist(
        version=DESIGN_CHECKLIST_VERSION,
        items=tuple(items),
        pass_count=sum(item.status is ChecklistStatus.pass_ for item in items),
        fail_count=sum(item.status is ChecklistStatus.fail for item in items),
        not_modeled_count=sum(
            item.status is ChecklistStatus.not_modeled for item in items
        ),
    )


__all__ = ["DESIGN_CHECKLIST_VERSION", "build_design_checklist"]
