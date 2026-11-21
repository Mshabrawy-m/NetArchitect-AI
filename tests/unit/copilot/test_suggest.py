"""C2 coverage: deterministic, engine-evaluated design suggestions."""

from __future__ import annotations

import pytest

from config.limits import MAX_COPILOT_SUGGESTIONS
from digital_twin import apply_failure
from optimization import Candidate, build_candidate_twin, evaluate_candidate
from security import analyze_design
from services.copilot import (
    CandidateProposal,
    SecurityProposal,
    Suggestion,
    SuggestionKind,
    apply_suggestion,
    suggest,
)
from services.copilot.suggest import _metrics, _score, _security_metrics, _settings
from services.llm.provider import LLMProvider
from simulation import (
    FailureSweepDepth,
    evaluate,
    run_failure_sweep,
    twin_fingerprint,
)
from tests.unit.security.design_helpers import case_design
from tests.unit.simulation.helpers import line_twin, make_demand


def _overloaded_twin():
    return line_twin(
        demands=(make_demand("a-to-c", "a", "c", bandwidth_mbps=150.0),),
        capacity_mbps=100.0,
    )


def _direct_candidate_metrics(twin, suggestion: Suggestion) -> dict[str, float]:
    """Re-evaluate a candidate exactly as the optimization engine would."""
    proposal = suggestion.proposal
    assert isinstance(proposal, CandidateProposal)
    settings = _settings(twin, proposal.assumptions, proposal.pool)
    built = build_candidate_twin(twin, proposal.candidate, settings)
    return _metrics(evaluate_candidate(built, Candidate(), settings))


def _select(report, suggestion_id: str) -> Suggestion:
    return next(item for item in report.suggestions if item.id == suggestion_id)


def test_spof_and_overload_suggestions_match_direct_evaluation() -> None:
    twin = _overloaded_twin()
    report = suggest(twin)

    ids = {item.id for item in report.suggestions}
    assert "overload:ab" in ids
    assert "overload:bc" in ids
    assert "spof-link:ab" in ids
    assert "spof-link:bc" in ids

    for suggestion in report.suggestions:
        assert isinstance(suggestion.proposal, CandidateProposal)
        assert suggestion.after == _direct_candidate_metrics(twin, suggestion)
        expected_score = _score(
            suggestion.primary_before,
            suggestion.primary_after,
            direction=suggestion.direction,
        )
        assert suggestion.score == expected_score

    assert report.suggestions == tuple(
        sorted(report.suggestions, key=lambda item: (-item.score, item.id))
    )


def test_baseline_is_untouched_and_apply_returns_a_new_twin() -> None:
    twin = _overloaded_twin()
    original = twin.model_dump_json()
    original_fingerprint = twin_fingerprint(twin)

    report = suggest(twin)
    assert twin.model_dump_json() == original
    assert report.baseline_fingerprint == original_fingerprint

    suggestion = report.suggestions[0]
    built = apply_suggestion(twin, suggestion)
    assert twin.model_dump_json() == original
    assert twin_fingerprint(twin) == original_fingerprint
    assert built is not twin
    assert twin_fingerprint(built) != original_fingerprint

    assert isinstance(suggestion.proposal, CandidateProposal)
    for new_link in suggestion.proposal.pool:
        assert any(link.id == new_link.id for link in built.topology.links)


def test_security_suggestion_uses_deterministic_proposals() -> None:
    twin, _ = case_design("SEC-DW-004")
    original_rules = tuple(rule.id for rule in twin.security.rules)

    report = suggest(twin)
    security = [
        item for item in report.suggestions if item.kind is SuggestionKind.security
    ]
    assert security
    for suggestion in security:
        assert isinstance(suggestion.proposal, SecurityProposal)
        assert suggestion.proposal.rule_ids
        assert suggestion.before["findings"] == float(
            len(analyze_design(twin).findings)
        )
        assert suggestion.after["findings"] < suggestion.before["findings"]

        built = apply_suggestion(twin, suggestion)
        after = analyze_design(built)
        assert _security_metrics(after)["findings"] == suggestion.after["findings"]
        assert tuple(rule.id for rule in twin.security.rules) == original_rules
        assert all(
            rule_id in tuple(rule.id for rule in built.security.rules)
            for rule_id in suggestion.proposal.rule_ids
        )


def test_failure_sweep_worst_case_is_reevaluated_on_a_new_twin() -> None:
    twin = _overloaded_twin()
    sweep = run_failure_sweep(
        twin,
        depth=FailureSweepDepth.n1,
        limit=MAX_COPILOT_SUGGESTIONS,
    )
    assert sweep.cases

    report = suggest(twin, sweep=sweep)
    sweep_suggestions = [
        item
        for item in report.suggestions
        if item.kind is SuggestionKind.failure_sweep
    ]
    assert sweep_suggestions
    suggestion = sweep_suggestions[0]
    assert suggestion.primary_metric == "served_demand_ratio"
    assert suggestion.primary_before == pytest.approx(0.0)
    assert suggestion.primary_after == pytest.approx(1.0)

    built = apply_suggestion(twin, suggestion)
    assert isinstance(suggestion.proposal, CandidateProposal)
    added_ids = {link.id for link in suggestion.proposal.pool}
    assert added_ids
    assert any(link.id in added_ids for link in built.topology.links)

    worst = max(
        sweep.cases,
        key=lambda case: (case.impact.impact_score, case.plan.case_id),
    )
    failed = apply_failure(
        built,
        link_ids=worst.plan.failed_link_ids,
        device_ids=worst.plan.failed_device_ids,
    )
    assert evaluate(failed).served_demand_ratio == pytest.approx(1.0)


def test_suggestion_count_is_bounded_and_warns_when_truncated() -> None:
    twin = _overloaded_twin()
    full = suggest(twin)
    capped = suggest(twin, max_suggestions=2)

    assert len(full.suggestions) > 2
    assert len(capped.suggestions) == 2
    assert capped.suggestions == full.suggestions[:2]
    assert any("top 2" in warning for warning in capped.warnings)
    assert not full.warnings

    with pytest.raises(ValueError, match="at least 1"):
        suggest(twin, max_suggestions=0)


def test_suggestion_never_calls_an_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def _must_not_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("suggest called an LLM provider")

    monkeypatch.setattr(LLMProvider, "complete", _must_not_call)
    report = suggest(_overloaded_twin())
    assert report.suggestions
