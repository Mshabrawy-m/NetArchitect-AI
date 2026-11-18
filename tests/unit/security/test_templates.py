"""Vendor-neutral template header and data-only tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from security import (
    SECURITY_DISCLAIMER,
    TEMPLATE_HEADER,
    TemplateDocument,
    analyze_design,
    render_template,
)

from .design_helpers import case_design

_ALLOWED_PREFIXES = (
    "#",
    "DEFAULT_ACTION ",
    "PROPOSED_RULE ",
    "RULE ",
    "SERVICE ",
    "ZONE ",
    "title=",
)
_BANNED_TOKENS = (
    "access-list",
    "commit",
    "configure",
    "device#",
    "ip route",
    "iptables",
    "netmiko",
    "no shutdown",
    "set ",
)


def test_template_header_disclaimer_and_data_only_records() -> None:
    twin, model = case_design("SEC-DW-004")
    analysis = analyze_design(twin, model=model)
    template = render_template(model, analysis.proposals)

    assert template.lines[0] == TEMPLATE_HEADER
    assert template.lines[0] == "TEMPLATE - not applied to any device"
    assert template.lines[1] == SECURITY_DISCLAIMER
    assert template.disclaimer == SECURITY_DISCLAIMER
    assert template.text() == "\n".join(template.lines)

    for line in template.lines:
        if line in (TEMPLATE_HEADER, SECURITY_DISCLAIMER):
            continue
        assert line.startswith(_ALLOWED_PREFIXES)

    lowered = template.text().lower()
    for token in _BANNED_TOKENS:
        assert token not in lowered, f"Template contains device syntax: {token!r}"

    assert f"PROPOSED_RULE id={analysis.proposals.rules[0].id} " in template.text()
    assert "DEFAULT_ACTION value=deny" in template.text()


def test_template_header_cannot_be_edited_or_omitted() -> None:
    with pytest.raises(ValidationError, match="first line"):
        TemplateDocument(title="Bad", lines=("RULE id=x",))

    with pytest.raises(ValidationError, match="exact disclaimer"):
        TemplateDocument(
            title="Bad",
            lines=(TEMPLATE_HEADER, "Wrong disclaimer"),
            disclaimer="Wrong disclaimer",
        )


def test_template_is_reproducible_without_proposals() -> None:
    _, model = case_design("SEC-DW-004")

    first = render_template(model)
    second = render_template(model)

    assert first == second
    assert all("PROPOSED_RULE" not in line for line in first.lines)
