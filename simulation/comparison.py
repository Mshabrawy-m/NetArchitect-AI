"""Pure side-by-side comparison of the modeled routing modes.

Every result in this module is a modeled estimate from the supplied twin and
assumptions. The comparison never mutates its inputs, uses no randomness, and
evaluates each mode against the exact same post-scenario twin. A shared router
cache and one deadline keep the work bounded on the free tier.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.scenario import Scenario
from digital_twin import DigitalTwin
from network.routing.sparse import SparseRouter

from .evaluator import _resolve_deadline, evaluate, twin_reference
from .models import (
    MODEL_NOTE,
    NetworkState,
    RoutingMode,
    SimulationAssumptions,
    TwinReference,
)
from .scenarios import build_scenario_twin

DEFAULT_COMPARISON_MODES: tuple[RoutingMode, ...] = (
    RoutingMode.single_path,
    RoutingMode.ecmp,
    RoutingMode.capacity_aware,
)


class ModeState(BaseModel):
    """One routing mode's modeled state for the same twin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: RoutingMode
    state: NetworkState


class RoutingModeComparison(BaseModel):
    """Deterministic side-by-side routing-mode results."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    twin: TwinReference = Field(description="Twin revision evaluated by every mode.")
    scenario_id: str = Field(
        default="",
        description="Scenario id when a scenario was supplied; empty for the baseline twin.",
    )
    assumptions: SimulationAssumptions = Field(
        description="Common assumptions; each mode is applied as an override."
    )
    modes: tuple[RoutingMode, ...]
    results: tuple[ModeState, ...]
    model_note: str = Field(default=MODEL_NOTE)


def compare_routing_modes(
    baseline_twin: DigitalTwin,
    assumptions: SimulationAssumptions | None = None,
    *,
    modes: tuple[RoutingMode, ...] = DEFAULT_COMPARISON_MODES,
    scenario: Scenario | None = None,
    max_runtime_seconds: float | None = None,
) -> RoutingModeComparison:
    """Evaluate ``modes`` against one twin (or one validated scenario state).

    The default mode is included first, so callers can compare new behavior
    against the legacy result without changing the baseline inputs. An empty
    ``modes`` tuple is invalid because a comparison needs at least one mode.
    """
    if not modes:
        raise ValueError("A routing-mode comparison needs at least one mode.")
    if len(set(modes)) != len(modes):
        raise ValueError("Routing modes in a comparison must be unique.")

    resolved = (
        SimulationAssumptions()
        if assumptions is None
        else assumptions
        if isinstance(assumptions, SimulationAssumptions)
        else SimulationAssumptions.model_validate(assumptions)
    )
    target_twin = (
        baseline_twin
        if scenario is None
        else build_scenario_twin(baseline_twin, scenario)
    )
    deadline = _resolve_deadline(max_runtime_seconds, None)
    router_cache: dict[tuple[object, ...], SparseRouter] = {}
    results: list[ModeState] = []
    for mode in modes:
        mode_assumptions = resolved.model_copy(update={"routing_mode": mode})
        state = evaluate(
            target_twin,
            mode_assumptions,
            _deadline=deadline,
            _router_cache=router_cache,
        )
        results.append(ModeState(mode=mode, state=state))
    return RoutingModeComparison(
        twin=twin_reference(target_twin),
        scenario_id="" if scenario is None else scenario.id,
        assumptions=resolved,
        modes=tuple(modes),
        results=tuple(results),
    )


__all__ = [
    "DEFAULT_COMPARISON_MODES",
    "ModeState",
    "RoutingModeComparison",
    "compare_routing_modes",
]
