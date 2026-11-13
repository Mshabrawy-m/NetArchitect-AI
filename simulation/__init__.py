"""Bounded, reproducible abstract flow simulation.

The package is pure Python: it imports no Streamlit, no LLM client, and adds no
dependency. Every result is a frozen Pydantic model and every function is a
pure evaluation of its inputs. All numbers are modeled estimates from stated
assumptions, not packet-level or hardware-accurate measurements.
"""

from .evaluator import evaluate, link_by_id, twin_fingerprint, twin_reference
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
from .tables import (
    demand_rows,
    format_path,
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
    "LinkLoad",
    "NetworkState",
    "SimulationAssumptions",
    "TwinReference",
    "UnservedDemand",
    "demand_rows",
    "evaluate",
    "format_path",
    "link_by_id",
    "link_rows",
    "metric_rows",
    "path_change_rows",
    "twin_fingerprint",
    "twin_reference",
    "unserved_rows",
]
