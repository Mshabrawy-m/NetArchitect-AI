"""Local golden evaluation for the deterministic-first copilot interpreter.

Every case runs offline through :class:`FakeProvider`. No case contacts Groq,
reads a credential, or writes a file. Run locally with ``pytest -q tests/eval``.
See ``docs/LLM_EVALUATION.md`` for the separate, manual real-response recorder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from services.copilot import CopilotCache, PromptTrace, interpret_scenario
from services.llm import INTERPRET_SCENARIO
from services.llm.budget import RequestBudget
from services.llm.testing import FakeProvider
from tests.unit.simulation.helpers import diamond_twin, make_demand

CASES: tuple[dict[str, Any], ...] = tuple(
    json.loads(
        Path(__file__).with_name("golden_cases.json").read_text(encoding="utf-8")
    )
)


def _twin():
    return diamond_twin(demands=(make_demand("a-to-d", "a", "d"),))


def _check_expectation(result: Any, expect: dict[str, Any]) -> None:
    assert result.source.value == expect["source"]
    assert result.prompt_id == INTERPRET_SCENARIO.id
    assert result.prompt_version == INTERPRET_SCENARIO.version
    if expect["scenario_type"] is None:
        assert not result.ready
        assert result.scenario is None
        assert result.clarifications
        assert result.clarifications[0].code.value == expect["clarification_code"]
        return

    assert result.ready
    scenario = result.scenario
    assert scenario is not None
    assert scenario.type.value == expect["scenario_type"]
    assert list(scenario.affected_links) == expect["affected_links"]
    assert list(scenario.affected_nodes) == expect["affected_nodes"]
    if expect["factor"] is None:
        assert "factor" not in scenario.parameters
    else:
        assert scenario.parameters["factor"] == pytest.approx(expect["factor"])


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[case["id"] for case in CASES],
)
def test_golden_case(case: dict[str, Any]) -> None:
    twin = _twin()
    expect = case["expect"]

    if expect["source"] == "deterministic":
        provider = FakeProvider([])
        trace = PromptTrace()
        result = interpret_scenario(case["sentence"], twin, provider=provider, trace=trace)
        assert provider.calls == []
        assert trace.records == ()
        assert result.provider_used is False
        assert result.cache_hit is False
        _check_expectation(result, expect)
        return

    budget = RequestBudget()
    cache = CopilotCache()
    trace = PromptTrace()
    reply = json.dumps(case["draft"], ensure_ascii=False)
    provider = FakeProvider([reply], budget=budget)
    result = interpret_scenario(
        case["sentence"],
        twin,
        provider=provider,
        cache=cache,
        trace=trace,
        max_repair_retries=0,
    )
    assert len(provider.calls) == 1
    assert budget.used_calls == 1
    assert result.provider_used is True
    assert result.cache_hit is False
    assert trace.records[-1].cache_hit is False
    _check_expectation(result, expect)

    # The same typed input must be served from the bounded cache with no
    # provider request and no further budget consumption.
    second_provider = FakeProvider([reply], budget=budget)
    cached = interpret_scenario(
        case["sentence"],
        twin,
        provider=second_provider,
        cache=cache,
        trace=trace,
        max_repair_retries=0,
    )
    assert second_provider.calls == []
    assert budget.used_calls == 1
    assert cached.cache_hit is True
    assert cached.provider_used is False
    assert trace.records[-1].cache_hit is True
    _check_expectation(cached, expect)


def test_golden_set_has_language_and_case_coverage() -> None:
    assert len(CASES) >= 20
    assert {case["language"] for case in CASES} == {"en", "ar"}
    assert sum(case["language"] == "en" for case in CASES) >= 10
    assert sum(case["language"] == "ar" for case in CASES) >= 10
    assert len({case["id"] for case in CASES}) == len(CASES)
