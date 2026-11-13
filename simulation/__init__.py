"""Bounded, reproducible abstract flow simulation.

The package is pure Python: it imports no Streamlit, no LLM client, and adds no
dependency. Every result is a frozen Pydantic model and every function is a
pure evaluation of its inputs. All numbers are modeled estimates from stated
assumptions, not packet-level or hardware-accurate measurements.
"""

from .evaluator import evaluate, link_by_id, twin_fingerprint, twin_reference
from .export import run_to_csv, run_to_json, run_to_json_bytes
from .history import ScenarioHistory
from .models import (
    MODEL_NOTE,
    CongestionLevel,
    CongestionThresholds,
    DemandEvaluation,
    LinkLoad,
    NetworkState,
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
    "MODEL_NOTE",
    "CongestionLevel",
    "CongestionThresholds",
    "DemandEvaluation",
    "LinkChange",
    "LinkChangeKind",
    "LinkLoad",
    "NetworkState",
    "PathChange",
    "ScenarioComparison",
    "ScenarioHistory",
    "ScenarioRun",
    "SimulationAssumptions",
    "TwinReference",
    "UnservedDemand",
    "compare_runs",
    "demand_rows",
    "evaluate",
    "format_path",
    "link_by_id",
    "link_comparison_rows",
    "link_rows",
    "metric_rows",
    "path_change_rows",
    "run_scenario",
    "run_to_csv",
    "run_to_json",
    "run_to_json_bytes",
    "twin_fingerprint",
    "twin_reference",
    "unserved_rows",
    "validate_scenario",
]
