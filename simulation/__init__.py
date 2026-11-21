"""Bounded, reproducible abstract flow simulation.

The package is pure Python: it imports no Streamlit, no LLM client, and adds no
dependency. Every result is a frozen Pydantic model and every function is a
pure evaluation of its inputs. All numbers are modeled estimates from stated
assumptions, not packet-level or hardware-accurate measurements.
"""

from .comparison import (
    DEFAULT_COMPARISON_MODES,
    ModeState,
    RoutingModeComparison,
    compare_routing_modes,
)
from .evaluator import (
    INSUFFICIENT_CAPACITY_REASON,
    evaluate,
    link_by_id,
    twin_fingerprint,
    twin_reference,
)
from .export import run_to_csv, run_to_json, run_to_json_bytes
from .failure_sweep import (
    FailureCase,
    FailureCasePlan,
    FailureImpact,
    FailureSweepDepth,
    FailureSweepPlan,
    FailureSweepResult,
    FailureSweepStopReason,
    failure_sweep_rows,
    failure_sweep_to_csv,
    failure_sweep_to_json,
    plan_failure_sweep,
    run_failure_sweep,
)
from .history import ScenarioHistory
from .models import (
    MODEL_NOTE,
    CongestionLevel,
    CongestionThresholds,
    DemandEvaluation,
    LinkLoad,
    NetworkState,
    PathSplit,
    RoutingMode,
    SimulationAssumptions,
    TwinReference,
    UnservedDemand,
)
from .scenarios import (
    LinkChange,
    LinkChangeKind,
    PathChange,
    ScenarioComparison,
    ScenarioRun,
    build_scenario_twin,
    compare_runs,
    run_scenario,
    validate_scenario,
)
from .tables import (
    demand_rows,
    format_path,
    link_comparison_rows,
    link_rows,
    metric_rows,
    path_change_rows,
    unserved_rows,
)

__all__ = [
    "DEFAULT_COMPARISON_MODES",
    "INSUFFICIENT_CAPACITY_REASON",
    "MODEL_NOTE",
    "CongestionLevel",
    "CongestionThresholds",
    "DemandEvaluation",
    "FailureCase",
    "FailureCasePlan",
    "FailureImpact",
    "FailureSweepDepth",
    "FailureSweepPlan",
    "FailureSweepResult",
    "FailureSweepStopReason",
    "LinkChange",
    "LinkChangeKind",
    "LinkLoad",
    "ModeState",
    "NetworkState",
    "PathChange",
    "PathSplit",
    "RoutingMode",
    "RoutingModeComparison",
    "ScenarioComparison",
    "ScenarioHistory",
    "ScenarioRun",
    "SimulationAssumptions",
    "TwinReference",
    "UnservedDemand",
    "build_scenario_twin",
    "compare_routing_modes",
    "compare_runs",
    "demand_rows",
    "evaluate",
    "failure_sweep_rows",
    "failure_sweep_to_csv",
    "failure_sweep_to_json",
    "format_path",
    "link_by_id",
    "link_comparison_rows",
    "link_rows",
    "metric_rows",
    "path_change_rows",
    "plan_failure_sweep",
    "run_failure_sweep",
    "run_scenario",
    "run_to_csv",
    "run_to_json",
    "run_to_json_bytes",
    "twin_fingerprint",
    "twin_reference",
    "unserved_rows",
    "validate_scenario",
]
