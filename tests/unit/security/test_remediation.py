"""Proposed-rule acceptance tests."""

from __future__ import annotations

import pytest

from core.exceptions import SchemaError
from security import (
    PolicyAction,
    accept_proposed_rules,
    analyze_design,
    build_proposals,
    get_security_model,
)

from .design_helpers import case_design


def _context():
    twin, model = case_design("SEC-DW-004")
    analysis = analyze_design(twin, model=model)
    return twin, model, analysis.proposals


def test_proposals_are_inert_until_explicitly_accepted() -> None:
    twin, model, proposals = _context()
    before_rules = model.rules

    assert [rule.id for rule in proposals.rules] == [
        "proposal-sec-dw-004-z-user-z-srv",
        "proposal-sec-dw-004-z-user-z-mgmt",
    ]
    assert get_security_model(twin).rules == before_rules
    assert all(rule.action is PolicyAction.deny for rule in proposals.rules)
    assert all(rule.any_service for rule in proposals.rules)
    assert all(rule.based_on_finding == "SEC-DW-004" for rule in proposals.rules)


def test_accepting_one_proposal_returns_a_new_twin() -> None:
    twin, model, proposals = _context()
    selected = "proposal-sec-dw-004-z-user-z-srv"

    updated, applied = accept_proposed_rules(twin, proposals, (selected,))

    assert applied == (selected,)
    assert updated is not twin
    assert get_security_model(twin) == model
    new_rules = get_security_model(updated).rules
    assert len(new_rules) == len(model.rules) + 1
    added = next(rule for rule in new_rules if rule.id == selected)
    assert added.order == 12
    assert added.src_zone == "z-user"
    assert added.dst_zone == "z-srv"
    assert added.any_service is True
    assert added.action is PolicyAction.deny
    assert added.note.startswith("User zone 'z-user' has no explicit deny rule")
    assert "proposal-sec-dw-004-z-user-z-mgmt" not in {
        rule.id for rule in new_rules
    }


def test_acceptance_order_follows_proposal_order_not_caller_order() -> None:
    twin, _, proposals = _context()
    first = "proposal-sec-dw-004-z-user-z-srv"
    second = "proposal-sec-dw-004-z-user-z-mgmt"

    updated, applied = accept_proposed_rules(twin, proposals, (second, first))

    assert applied == (first, second)
    rules = {rule.id: rule for rule in get_security_model(updated).rules}
    assert rules[first].order == 12
    assert rules[second].order == 13


def test_unknown_proposal_id_is_rejected_before_any_edit() -> None:
    twin, model, proposals = _context()

    with pytest.raises(SchemaError, match="Unknown proposed rule ids: ghost"):
        accept_proposed_rules(twin, proposals, ("ghost",))

    assert get_security_model(twin) == model


def test_empty_acceptance_applies_nothing() -> None:
    twin, model, proposals = _context()

    updated, applied = accept_proposed_rules(twin, proposals, ())

    assert applied == ()
    assert get_security_model(updated).rules == model.rules
    assert get_security_model(updated).model_dump() == model.model_dump()


def test_build_proposals_is_deterministic_and_deduplicates() -> None:
    twin, model = case_design("SEC-DW-004")
    finding = next(
        item
        for item in analyze_design(twin, model=model).findings
        if item.code == "SEC-DW-004"
    )

    rebuilt = build_proposals((finding, finding))

    assert rebuilt == build_proposals((finding,))
    assert len(rebuilt.rules) == 1
    assert rebuilt.rules[0].id == "proposal-sec-dw-004-z-user-z-srv"
