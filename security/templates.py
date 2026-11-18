"""Vendor-neutral, data-only security templates.

Templates describe modeled policy intent as key/value records. They contain no
vendor syntax, no device commands, and no instructions to apply a configuration.
"""

from __future__ import annotations

from .models import (
    SECURITY_DISCLAIMER,
    ProposalSet,
    SecurityModel,
    TemplateDocument,
)

TEMPLATE_HEADER = "TEMPLATE - not applied to any device"


def _service_text(rule) -> str:
    if rule.any_service:
        return "any"
    return ",".join(sorted(rule.services))


def render_template(
    model: SecurityModel,
    proposals: ProposalSet | None = None,
    *,
    title: str = "Vendor-neutral modeled security policy intent",
) -> TemplateDocument:
    """Render a deterministic, data-only template for one modeled design."""
    lines: list[str] = [
        TEMPLATE_HEADER,
        SECURITY_DISCLAIMER,
        f"title={title}",
        "# Data-only policy intent. No device syntax or commands are represented.",
        f"DEFAULT_ACTION value={model.default_action.value}",
    ]
    for zone in model.zones:
        lines.append(
            f"ZONE id={zone.id} type={zone.type.value} "
            f"criticality={zone.criticality} name={zone.name}"
        )
    for service in model.services:
        lines.append(
            f"SERVICE name={service.name} protocol={service.protocol.value} "
            f"ports={service.port_start}-{service.port_end}"
        )
    for rule in model.ordered_rules:
        lines.append(
            f"RULE id={rule.id} order={rule.order} src={rule.src_zone} "
            f"dst={rule.dst_zone} service={_service_text(rule)} "
            f"action={rule.action.value} enabled={str(rule.enabled).lower()}"
        )
    if proposals is not None:
        for rule in proposals.rules:
            service_text = "any" if rule.any_service else ",".join(rule.services)
            reason = " ".join(rule.reason.split())
            lines.append(
                f"PROPOSED_RULE id={rule.id} src={rule.src_zone} "
                f"dst={rule.dst_zone} service={service_text} "
                f"action={rule.action.value} reason={reason}"
            )
    return TemplateDocument(title=title, lines=tuple(lines))


__all__ = ["TEMPLATE_HEADER", "render_template"]
