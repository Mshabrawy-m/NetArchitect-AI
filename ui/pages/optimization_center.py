"""Optimization Center page.

The page is presentation and orchestration only. Candidate evaluation, hard
constraints, greedy search, the Genetic Algorithm, NSGA-II, comparison, history,
and exports are delegated to :mod:`optimization`; the baseline twin is read and
edited through :mod:`ui.state`.

Every value shown here is a *modeled estimate*. The search is a heuristic over
a bounded, stated design space and never claims a global optimum.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pydantic import ValidationError

import config.limits
from config.limits import (
    MAX_EVALUATIONS,
    MAX_OPTIMIZATION_RUNS,
    MAX_OPTIMIZATION_RUNTIME_SECONDS,
    MAX_POPULATION,
)
from core.exceptions import NetArchitectError
from core.schemas.network import Link
from digital_twin import DigitalTwin
from optimization import (
    DEFAULT_TIERS,
    OBJECTIVE_DEFINITIONS,
    SEARCH_NOTE,
    Algorithm,
    CapacityTier,
    CostModel,
    HardConstraints,
    ObjectiveKind,
    ObjectiveSpec,
    OptimizationRun,
    OptimizationSettings,
    build_candidate_twin,
    candidate_changes,
    compare_runs,
    objective_deltas,
    pareto_front,
    run_optimization,
    run_to_csv,
    run_to_json_bytes,
)
from ui import state
from ui.components import csv_bytes, format_error

VIEW_RUN_KEY = "optimization_view_run"
FLASH_KEY = "optimization_flash"
HISTORY_SELECT_KEY = "optimization_history_select"
INSPECT_KEY = "optimization_candidate_select"
SNAPSHOT_LABEL_KEY = "optimization_snapshot_label"

ALGORITHM_LABELS: dict[Algorithm, str] = {
    Algorithm.greedy: "Greedy hill-climb (deterministic baseline)",
    Algorithm.genetic: "Genetic algorithm (weighted sum)",
    Algorithm.nsga2: "NSGA-II (Pareto front, no weights in selection)",
}
ALGORITHM_OPTIONS = list(ALGORITHM_LABELS.values())
ALGORITHM_BY_LABEL = {label: kind for kind, label in ALGORITHM_LABELS.items()}

DEFAULT_SELECTED = {
    ObjectiveKind.infrastructure_cost,
    ObjectiveKind.max_utilization,
}
DEFAULT_WEIGHTS = {
    ObjectiveKind.infrastructure_cost: 0.5,
    ObjectiveKind.max_utilization: 0.5,
}
DIRECTION_TEXT = {
    "minimize": "lower is better",
    "maximize": "higher is better",
}


def _flash(level: str, message: str) -> None:
    messages = state.session_get(FLASH_KEY, [])
    state.session_set(FLASH_KEY, [*messages, (level, message)])


def _render_flash() -> None:
    for level, message in state.session_pop(FLASH_KEY, []):
        getattr(st, level)(message)


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "optimization"


def _text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) and pd.isna(value):
        return ""
    return str(value).strip()


def _flag(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, str) and pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _positive_number(value: object, label: str, entity: str) -> float:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        raise ValueError(f"{entity}: {label} is required.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{entity}: {label} must be a number.") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{entity}: {label} must be a positive number.")
    return number


def _non_negative_number(value: object, label: str, entity: str) -> float:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        raise ValueError(f"{entity}: {label} is required.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{entity}: {label} must be a number.") from error
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{entity}: {label} must be a non-negative number.")
    return number


# ---------------------------------------------------------------------------
# Design-space inputs
# ---------------------------------------------------------------------------


def _pool_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "id",
            "source",
            "destination",
            "capacity_mbps",
            "cost",
            "directed",
        ]
    )


def _tier_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": tier.name,
                "capacity_mbps": tier.capacity_mbps,
                "link_cost_proxy": tier.link_cost_proxy,
            }
            for tier in DEFAULT_TIERS
        ],
        columns=["name", "capacity_mbps", "link_cost_proxy"],
    )


def _parse_pool(
    twin: DigitalTwin,
    edited: pd.DataFrame,
) -> tuple[Link, ...]:
    """Return validated candidate links from an edited table."""
    known_devices = {device.id for device in twin.topology.devices}
    baseline_links = {link.id for link in twin.topology.links}
    links: list[Link] = []
    for _, row in edited.iterrows():
        link_id = _text(row["id"])
        if not link_id:
            raise ValueError("Every candidate-pool row needs a non-empty link id.")
        source = _text(row["source"])
        destination = _text(row["destination"])
        if not source or not destination:
            raise ValueError(f"Candidate link {link_id!r} needs both endpoints.")
        unknown = sorted(
            endpoint
            for endpoint in (source, destination)
            if endpoint not in known_devices
        )
        if unknown:
            raise ValueError(
                f"Candidate link {link_id!r} references unknown device(s): "
                + ", ".join(unknown)
            )
        links.append(
            Link(
                id=link_id,
                endpoints=(source, destination),
                capacity_mbps=_positive_number(
                    row["capacity_mbps"],
                    "capacity",
                    f"Candidate link {link_id!r}",
                ),
                cost=_positive_number(
                    row["cost"],
                    "routing cost",
                    f"Candidate link {link_id!r}",
                ),
                directed=_flag(row["directed"]),
            )
        )

    ids = [link.id for link in links]
    if len(set(ids)) != len(ids):
        raise ValueError("Candidate-pool link ids must be unique.")
    clashes = sorted(set(ids) & baseline_links)
    if clashes:
        raise ValueError(
            "Candidate-pool ids must not already exist in the baseline: "
            + ", ".join(clashes)
            + ". Use a capacity tier to upgrade a baseline link."
        )
    return tuple(links)


def _parse_tiers(edited: pd.DataFrame) -> tuple[CapacityTier, ...]:
    """Return validated capacity tiers from an edited table."""
    tiers: list[CapacityTier] = []
    for _, row in edited.iterrows():
        name = _text(row["name"])
        if not name:
            raise ValueError("Every capacity tier needs a non-empty name.")
        tiers.append(
            CapacityTier(
                name=name,
                capacity_mbps=_positive_number(
                    row["capacity_mbps"],
                    "capacity",
                    f"Capacity tier {name!r}",
                ),
                link_cost_proxy=_non_negative_number(
                    row["link_cost_proxy"],
                    "link cost proxy",
                    f"Capacity tier {name!r}",
                ),
            )
        )
    if not tiers:
        raise ValueError("At least one capacity tier is required.")
    return tuple(tiers)


def _default_bounds(
    twin: DigitalTwin,
    pool: tuple[Link, ...],
    kind: ObjectiveKind,
) -> tuple[float, float]:
    links = len(twin.topology.links) + len(pool)
    devices = len(twin.topology.devices)
    if kind is ObjectiveKind.infrastructure_cost:
        return 0.0, 10_000.0
    if kind is ObjectiveKind.max_utilization:
        return 0.0, 200.0
    if kind is ObjectiveKind.mean_path_cost:
        return 0.0, 100.0
    if kind is ObjectiveKind.spof_count:
        return 0.0, float(max(1, devices + links))
    if kind is ObjectiveKind.min_edge_disjoint_paths:
        return 0.0, float(max(1, links))
    return 0.0, float(max(1, links))


def _render_pool_editor(twin: DigitalTwin) -> pd.DataFrame:
    st.markdown("**Candidate-link pool**")
    st.caption(
        "Links the optimizer may add. Ids must be new; upgrade an existing link "
        "with a capacity tier instead. Routing cost is the path metric, not money."
    )
    device_options = sorted(device.id for device in twin.topology.devices)
    return st.data_editor(
        _pool_frame(),
        key="optimization_pool_editor",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "id": st.column_config.TextColumn("Link id", required=True),
            "source": st.column_config.SelectboxColumn(
                "Source",
                options=device_options,
                required=True,
            ),
            "destination": st.column_config.SelectboxColumn(
                "Destination",
                options=device_options,
                required=True,
            ),
            "capacity_mbps": st.column_config.NumberColumn(
                "Seed capacity (Mbps)",
                min_value=0.001,
                format="%.2f",
            ),
            "cost": st.column_config.NumberColumn(
                "Routing cost",
                min_value=0.001,
                format="%.2f",
            ),
            "directed": st.column_config.CheckboxColumn(
                "Directed",
                default=False,
            ),
        },
    )


def _render_cost_model() -> tuple[pd.DataFrame, float, tuple[float, ...]]:
    st.markdown("**Cost model**")
    st.caption(
        "Tier costs and device cost are modeled proxies in arbitrary cost "
        "units. They are not vendor quotes, budgets, or measured expenses."
    )
    tiers = st.data_editor(
        _tier_frame(),
        key="optimization_tier_editor",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "name": st.column_config.TextColumn("Tier name", required=True),
            "capacity_mbps": st.column_config.NumberColumn(
                "Capacity (Mbps)",
                min_value=0.001,
                format="%.2f",
            ),
            "link_cost_proxy": st.column_config.NumberColumn(
                "Link cost proxy",
                min_value=0.0,
                format="%.2f",
            ),
        },
    )
    columns = st.columns(2)
    with columns[0]:
        device_cost = st.number_input(
            "Device cost proxy (per device)",
            min_value=0.0,
            value=0.0,
            step=10.0,
            key="optimization_device_cost",
        )
    with columns[1]:
        multiplier_options = st.multiselect(
            "Allowed routing-cost multipliers",
            options=(1.25, 1.5, 2.0, 3.0),
            default=(),
            key="optimization_multiplier_options",
            help=(
                "Optional. When empty, the search cannot adjust routing costs. "
                "A multiplier scales an existing link's path metric."
            ),
        )
    return tiers, float(device_cost), tuple(float(v) for v in multiplier_options)


def _render_objective_controls(
    twin: DigitalTwin,
    pool: tuple[Link, ...],
) -> None:
    st.markdown("**Objectives and weights**")
    st.caption(
        "Bounds are fixed references for min-max normalization; values outside "
        "them are clamped. Selected weights must sum to exactly 1. NSGA-II uses "
        "objectives without weights for selection, but still records the "
        "weighted score for comparability."
    )
    for kind in ObjectiveKind:
        definition = OBJECTIVE_DEFINITIONS[kind]
        lower_default, upper_default = _default_bounds(twin, pool, kind)
        columns = st.columns([1.4, 1, 1, 1, 2.6])
        used = columns[0].checkbox(
            definition.label,
            value=kind in DEFAULT_SELECTED,
            key=f"optimization_obj_use_{kind.value}",
        )
        columns[1].number_input(
            "Weight",
            min_value=0.0,
            max_value=1.0,
            value=float(DEFAULT_WEIGHTS.get(kind, 0.0)),
            step=0.05,
            format="%.3f",
            key=f"optimization_obj_weight_{kind.value}",
            disabled=not used,
        )
        columns[2].number_input(
            "Lower bound",
            value=float(lower_default),
            step=1.0,
            key=f"optimization_obj_lower_{kind.value}",
            disabled=not used,
        )
        columns[3].number_input(
            "Upper bound",
            value=float(upper_default),
            step=1.0,
            key=f"optimization_obj_upper_{kind.value}",
            disabled=not used,
        )
        columns[4].caption(
            f"{definition.unit} ({DIRECTION_TEXT[definition.direction.value]})"
        )


def _render_constraints() -> HardConstraints:
    st.markdown("**Hard constraints**")
    st.caption(
        "Violating any enforced constraint makes a candidate infeasible. "
        "Infeasible candidates are recorded but never recommended."
    )
    columns = st.columns(3)
    with columns[0]:
        require_connectivity = st.checkbox(
            "Require connectivity",
            value=True,
            key="optimization_require_connectivity",
            help="At most one weak component and no isolated device.",
        )
        min_served = st.slider(
            "Minimum served-demand ratio",
            min_value=0.0,
            max_value=1.0,
            value=0.95,
            step=0.01,
            key="optimization_min_served_ratio",
        )
    with columns[1]:
        enforce_utilization = st.checkbox(
            "Enforce maximum utilization",
            value=True,
            key="optimization_enforce_utilization",
        )
        max_utilization = st.number_input(
            "Maximum utilization (%)",
            min_value=0.1,
            value=100.0,
            step=1.0,
            key="optimization_max_utilization",
            disabled=not enforce_utilization,
        )
        enforce_budget = st.checkbox(
            "Enforce infrastructure budget",
            value=False,
            key="optimization_enforce_budget",
        )
        budget = st.number_input(
            "Maximum cost proxy",
            min_value=0.0,
            value=5_000.0,
            step=100.0,
            key="optimization_max_budget",
            disabled=not enforce_budget,
        )
    with columns[2]:
        max_nodes = st.number_input(
            "Maximum devices",
            min_value=0,
            max_value=config.limits.MAX_NODES,
            value=config.limits.MAX_NODES,
            step=1,
            key="optimization_max_nodes",
        )
        max_edges = st.number_input(
            "Maximum links",
            min_value=0,
            max_value=config.limits.MAX_EDGES,
            value=config.limits.MAX_EDGES,
            step=1,
            key="optimization_max_edges",
        )
        enforce_redundancy = st.checkbox(
            "Require minimum edge-disjoint paths",
            value=False,
            key="optimization_enforce_redundancy",
        )
        min_paths = st.number_input(
            "Minimum edge-disjoint paths",
            min_value=0,
            value=1,
            step=1,
            key="optimization_min_paths",
            disabled=not enforce_redundancy,
        )

    return HardConstraints(
        require_connectivity=bool(require_connectivity),
        min_served_demand_ratio=float(min_served),
        max_utilization_percent=(
            float(max_utilization) if enforce_utilization else None
        ),
        max_budget_proxy=float(budget) if enforce_budget else None,
        max_nodes=int(max_nodes),
        max_edges=int(max_edges),
        min_edge_disjoint_paths=(
            int(min_paths) if enforce_redundancy else None
        ),
    )


def _render_search_controls() -> tuple[Algorithm, int, int, int, int, float]:
    st.markdown("**Search settings**")
    columns = st.columns(3)
    with columns[0]:
        algorithm_label = st.selectbox(
            "Algorithm",
            ALGORITHM_OPTIONS,
            index=0,
            key="optimization_algorithm",
        )
        seed = st.number_input(
            "Random seed",
            min_value=0,
            max_value=2**31 - 1,
            value=42,
            step=1,
            key="optimization_seed",
            help="Identical seed and settings reproduce identical output.",
        )
    with columns[1]:
        population = st.slider(
            "Population size",
            min_value=2,
            max_value=MAX_POPULATION,
            value=50,
            step=1,
            key="optimization_population",
            help="Used by the Genetic Algorithm and NSGA-II.",
        )
        iterations = st.slider(
            "Maximum iterations",
            min_value=1,
            max_value=config.limits.MAX_OPTIMIZATION_ITERATIONS,
            value=100,
            step=1,
            key="optimization_iterations",
        )
    with columns[2]:
        evaluations = st.slider(
            "Maximum evaluations",
            min_value=1,
            max_value=MAX_EVALUATIONS,
            value=2_000,
            step=100,
            key="optimization_evaluations",
        )
        runtime = st.number_input(
            "Runtime limit (seconds)",
            min_value=1.0,
            max_value=float(MAX_OPTIMIZATION_RUNTIME_SECONDS),
            value=30.0,
            step=5.0,
            key="optimization_runtime",
        )
    return (
        ALGORITHM_BY_LABEL[algorithm_label],
        int(seed),
        int(population),
        int(iterations),
        int(evaluations),
        float(runtime),
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def _build_settings(
    twin: DigitalTwin,
    *,
    pool: tuple[Link, ...],
    tiers: tuple[CapacityTier, ...],
    device_cost: float,
    multiplier_options: tuple[float, ...],
    objectives: tuple[ObjectiveSpec, ...],
    constraints: HardConstraints,
    seed: int,
    population: int,
    iterations: int,
    evaluations: int,
    runtime: float,
) -> OptimizationSettings:
    return OptimizationSettings(
        candidate_pool=pool,
        cost_model=CostModel(
            tiers=tiers,
            device_cost_proxy=device_cost,
        ),
        objectives=objectives,
        constraints=constraints,
        seed=seed,
        population_size=population,
        max_iterations=iterations,
        max_evaluations=evaluations,
        max_runtime_seconds=runtime,
        cost_multiplier_options=multiplier_options,
    )


def _render_optimization_form(
    twin: DigitalTwin,
) -> tuple[OptimizationSettings, Algorithm] | None:
    with st.form("optimization_form"):
        st.subheader("Design space")
        pool_table = _render_pool_editor(twin)
        st.divider()
        tier_table, device_cost, multipliers = _render_cost_model()
        st.divider()
        _render_objective_controls(twin, ())
        st.divider()
        constraints = _render_constraints()
        st.divider()
        (
            algorithm,
            seed,
            population,
            iterations,
            evaluations,
            runtime,
        ) = _render_search_controls()
        submitted = st.form_submit_button(
            "Run optimization",
            key="optimization_run",
            type="primary",
        )

    if not submitted:
        return None

    try:
        pool = _parse_pool(twin, pool_table)
        tiers = _parse_tiers(tier_table)
        objectives = _render_objectives_values(twin, pool)
        settings = _build_settings(
            twin,
            pool=pool,
            tiers=tiers,
            device_cost=device_cost,
            multiplier_options=multipliers,
            objectives=objectives,
            constraints=constraints,
            seed=seed,
            population=population,
            iterations=iterations,
            evaluations=evaluations,
            runtime=runtime,
        )
    except (NetArchitectError, ValidationError, TypeError, ValueError) as error:
        st.error(format_error(error), title="Optimization settings rejected")
        return None
    return settings, algorithm


def _render_objectives_values(
    twin: DigitalTwin,
    pool: tuple[Link, ...],
) -> tuple[ObjectiveSpec, ...]:
    """Collect objective values already committed by the form widgets."""
    objectives: list[ObjectiveSpec] = []
    for kind in ObjectiveKind:
        if not state.session_get(f"optimization_obj_use_{kind.value}", False):
            continue
        lower_default, upper_default = _default_bounds(twin, pool, kind)
        objectives.append(
            ObjectiveSpec(
                kind=kind,
                weight=float(
                    state.session_get(
                        f"optimization_obj_weight_{kind.value}",
                        DEFAULT_WEIGHTS.get(kind, 0.0),
                    )
                ),
                lower_bound=float(
                    state.session_get(
                        f"optimization_obj_lower_{kind.value}",
                        lower_default,
                    )
                ),
                upper_bound=float(
                    state.session_get(
                        f"optimization_obj_upper_{kind.value}",
                        upper_default,
                    )
                ),
            )
        )
    if not objectives:
        raise ValueError("Select at least one objective.")
    total = sum(objective.weight for objective in objectives)
    if abs(total - 1.0) > 1e-9:
        raise ValueError(
            "Selected objective weights must sum to 1; got "
            f"{total:.12g}. Adjust the weights before running."
        )
    return tuple(objectives)


def _run_and_store(twin: DigitalTwin, settings: OptimizationSettings, algorithm: Algorithm) -> None:
    history = state.get_optimization_history()
    if len(history) >= MAX_OPTIMIZATION_RUNS:
        st.error(
            f"The history holds the maximum {MAX_OPTIMIZATION_RUNS} runs. "
            "Delete one below before running another.",
            title="History full",
        )
        return

    with st.status(
        f"Running {ALGORITHM_LABELS[algorithm]}...",
        expanded=True,
    ) as status:
        st.write(
            f"Seed {settings.seed}; population {settings.population_size}; "
            f"max {settings.max_iterations} iterations, "
            f"{settings.max_evaluations} evaluations, "
            f"{settings.max_runtime_seconds:g} s."
        )
        progress = st.progress(0.0, text="Evaluating the baseline and candidates...")
        try:
            run = run_optimization(twin, settings, algorithm)
        except (NetArchitectError, ValidationError, RuntimeError, ValueError) as error:
            progress.empty()
            status.update(
                label="Optimization failed",
                state="error",
                expanded=True,
            )
            st.error(format_error(error), title="Optimization failed")
            return

        progress.progress(
            1.0,
            text=(
                f"Stopped: {run.stop_reason.value}. "
                f"{run.evaluations} evaluation(s), "
                f"{len(run.pareto_front)} Pareto candidate(s)."
            ),
        )
        status.update(
            label="Optimization run complete",
            state="complete",
            expanded=False,
        )

    try:
        state.add_optimization_run(run)
    except NetArchitectError as error:
        st.error(format_error(error), title="History limit reached")
        return
    state.session_set(VIEW_RUN_KEY, run)
    if run.best is None:
        _flash(
            "warning",
            f"{ALGORITHM_LABELS[algorithm]} found no feasible candidate; "
            "inspect the violations below.",
        )
    else:
        _flash(
            "success",
            f"{ALGORITHM_LABELS[algorithm]} stopped at "
            f"{run.stop_reason.value} after {run.evaluations} evaluation(s).",
        )
    st.rerun()


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def _active_run() -> OptimizationRun | None:
    run = state.session_get(VIEW_RUN_KEY)
    if isinstance(run, OptimizationRun):
        return run
    runs = state.get_optimization_runs()
    return runs[-1] if runs else None


def _run_front(run: OptimizationRun) -> tuple:
    """Return the reported front, computing one for weighted-sum runs."""
    if run.pareto_front:
        return run.pareto_front
    evaluations = [
        record.evaluation
        for record in run.candidates
        if record.evaluation.feasible
    ]
    front = pareto_front(evaluations)
    from optimization import CandidateRecord, crowding_distance

    distances = crowding_distance(front)
    return tuple(
        CandidateRecord(evaluation=value, rank=0, crowding_distance=distance)
        for value, distance in zip(front, distances)
    )


def _objective_pair(run: OptimizationRun) -> tuple[ObjectiveSpec, ObjectiveSpec] | None:
    if len(run.settings.objectives) != 2:
        return None
    return run.settings.objectives[0], run.settings.objectives[1]


def _baseline_value(run: OptimizationRun, kind: ObjectiveKind) -> float | None:
    for value in run.baseline.objectives:
        if value.kind is kind:
            return value.raw_value
    return None


def _weight_map(run: OptimizationRun) -> dict[ObjectiveKind, float]:
    return {objective.kind: objective.weight for objective in run.settings.objectives}


def _render_headline(run: OptimizationRun) -> None:
    columns = st.columns(4)
    columns[0].metric("Algorithm", ALGORITHM_LABELS[run.algorithm].split(" (")[0])
    columns[1].metric("Stop reason", run.stop_reason.value)
    columns[2].metric("Evaluations", run.evaluations)
    columns[3].metric(
        "Best weighted score",
        "none feasible" if run.best is None else f"{run.best.evaluation.weighted_score:.4f}",
    )
    st.caption(
        f"Seed {run.seed}; limits: population {run.limits.max_population}, "
        f"iterations {run.limits.max_iterations}, evaluations "
        f"{run.limits.max_evaluations}, runtime "
        f"{run.limits.max_runtime_seconds:g} s. Cache hits "
        f"{run.cache_hits}. {SEARCH_NOTE}"
    )


def _delta_frame(run: OptimizationRun, evaluation) -> pd.DataFrame:
    deltas = objective_deltas(
        run.baseline,
        evaluation,
        weights=_weight_map(run),
    )
    return pd.DataFrame(
        [
            {
                "Objective": delta.label,
                "Unit": delta.unit,
                "Direction": delta.direction.value,
                "Baseline": delta.baseline_value,
                "Optimized": delta.candidate_value,
                "Change": delta.absolute_change,
                "Relative change": (
                    None if delta.relative_change is None else delta.relative_change
                ),
                "Improved": delta.improved,
                "Weight": delta.weight,
            }
            for delta in deltas
        ]
    )


def _render_best_comparison(run: OptimizationRun) -> None:
    st.subheader("Baseline versus optimized design")
    if run.best is None:
        st.warning(
            "No evaluated candidate satisfies every enforced hard constraint, "
            "so no design is recommended. Infeasible candidates and their "
            "violations are listed below.",
            title="No feasible design",
        )
        return
    evaluation = run.best.evaluation
    st.caption(
        "The optimized column is the best feasible weighted score under the "
        "stated weights. It is not a global optimum or an unconditional best."
    )
    st.dataframe(
        _delta_frame(run, evaluation),
        hide_index=True,
        width="stretch",
    )
    metrics = evaluation.metrics
    columns = st.columns(5)
    columns[0].metric("Links", metrics.link_count)
    columns[1].metric("Served demands", f"{metrics.served_demand_count}/{metrics.demand_count}")
    columns[2].metric("Max utilization", f"{metrics.max_utilization_percent:.2f}%")
    columns[3].metric("Cost proxy", f"{metrics.infrastructure_cost_proxy:.2f}")
    columns[4].metric(
        "SPOFs",
        "not evaluated" if metrics.spof_count is None else metrics.spof_count,
    )
    trade_offs = objective_deltas(
        run.baseline,
        evaluation,
        weights=_weight_map(run),
    )
    worsened = [
        delta for delta in trade_offs if not delta.improved and delta.absolute_change != 0
    ]
    if worsened:
        st.warning(
            "Trade-offs: "
            + "; ".join(
                f"{delta.label} worsened to {delta.candidate_value:g} "
                f"{delta.unit}"
                for delta in worsened
            ),
            title="Objectives that got worse",
        )
    else:
        st.success("No selected objective got worse than the baseline.")


def _render_pareto_chart(run: OptimizationRun) -> None:
    st.subheader("Pareto trade-off")
    pair = _objective_pair(run)
    if pair is None:
        st.info(
            "The Pareto scatter needs exactly two selected objectives; "
            f"this run selected {len(run.settings.objectives)}."
        )
        return
    first, second = pair
    feasible = [
        record.evaluation for record in run.candidates if record.evaluation.feasible
    ]
    if not feasible:
        st.info("No feasible candidate was evaluated, so there is no front to plot.")
        return
    front = _run_front(run)
    front_hashes = {record.evaluation.candidate_hash for record in front}
    baseline = run.baseline

    def values(evaluation) -> tuple[float, float] | None:
        by_kind = {value.kind: value.raw_value for value in evaluation.objectives}
        if first.kind not in by_kind or second.kind not in by_kind:
            return None
        return by_kind[first.kind], by_kind[second.kind]

    figure = go.Figure()
    evaluated_points = [
        point for evaluation in feasible if (point := values(evaluation)) is not None
    ]
    figure.add_trace(
        go.Scatter(
            x=[point[0] for point in evaluated_points],
            y=[point[1] for point in evaluated_points],
            mode="markers",
            name="Evaluated feasible",
            marker={"color": "#b8c4d0", "size": 7, "opacity": 0.6},
            hoverinfo="skip",
        )
    )
    front_points = [
        point
        for record in front
        if record.evaluation.candidate_hash in front_hashes
        and (point := values(record.evaluation)) is not None
    ]
    figure.add_trace(
        go.Scatter(
            x=[point[0] for point in front_points],
            y=[point[1] for point in front_points],
            mode="markers",
            name="Reported Pareto front",
            marker={
                "color": "#2f6690",
                "size": 11,
                "line": {"color": "#ffffff", "width": 1},
            },
        )
    )
    base_point = values(baseline)
    if base_point is not None:
        figure.add_trace(
            go.Scatter(
                x=[base_point[0]],
                y=[base_point[1]],
                mode="markers+text",
                name="Baseline",
                text=["Baseline"],
                textposition="top center",
                marker={
                    "color": "#b23c3c",
                    "size": 15,
                    "symbol": "diamond",
                    "line": {"color": "#ffffff", "width": 1},
                },
            )
        )
    figure.update_layout(
        height=420,
        margin={"l": 10, "r": 10, "t": 30, "b": 60},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        xaxis_title=(
            f"{first.label} ({first.unit}) - "
            f"{DIRECTION_TEXT[first.direction.value]}"
        ),
        yaxis_title=(
            f"{second.label} ({second.unit}) - "
            f"{DIRECTION_TEXT[second.direction.value]}"
        ),
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        hovermode="closest",
    )
    st.plotly_chart(
        figure,
        width="stretch",
        config={"displayModeBar": False},
        alt="Scatter of evaluated candidates with the Pareto front and baseline marked",
    )
    st.caption(
        "The front contains evaluated feasible candidates only. Unevaluated "
        "designs cannot be ranked, and a front is not a claim of optimality."
    )


def _inspectable(run: OptimizationRun) -> list:
    """Return a bounded, deduplicated list of candidates worth inspecting."""
    seen: set[str] = set()
    records = []
    ordered = []
    if run.best is not None:
        ordered.append(run.best)
    ordered.extend(run.pareto_front)
    infeasible = [
        record for record in run.candidates if not record.evaluation.feasible
    ][:10]
    feasible = [
        record
        for record in sorted(
            run.candidates,
            key=lambda item: item.evaluation.weighted_score,
        )
        if record.evaluation.feasible
    ][:10]
    ordered.extend([*infeasible, *feasible])
    for record in ordered:
        if record.evaluation.candidate_hash in seen:
            continue
        seen.add(record.evaluation.candidate_hash)
        records.append(record)
    return records


def _candidate_label(record) -> str:
    evaluation = record.evaluation
    state_text = "feasible" if evaluation.feasible else "infeasible"
    return (
        f"{state_text} | score {evaluation.weighted_score:.4f} | "
        f"{evaluation.candidate_hash[:10]}"
    )


def _render_candidates(run: OptimizationRun, twin: DigitalTwin) -> None:
    st.subheader("Evaluated candidates")
    total = len(run.candidates)
    feasible = sum(1 for record in run.candidates if record.evaluation.feasible)
    st.caption(
        f"{total} candidate evaluation(s): {feasible} feasible and "
        f"{total - feasible} infeasible. Infeasible candidates are retained for "
        "audit but can never be recommended."
    )

    rows = []
    for record in sorted(
        run.candidates,
        key=lambda item: (
            not item.evaluation.feasible,
            item.evaluation.weighted_score,
            item.evaluation.candidate_hash,
        ),
    )[:100]:
        evaluation = record.evaluation
        rows.append(
            {
                "Feasible": evaluation.feasible,
                "Weighted score": evaluation.weighted_score,
                "Rank": record.rank,
                "Selected links": ", ".join(evaluation.candidate.selected_link_ids),
                "Violated constraints": "; ".join(evaluation.violated_constraints),
                "Hash": evaluation.candidate_hash[:12],
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if total > 100:
        st.caption("The table shows at most 100 candidates, best feasible first.")

    records = _inspectable(run)
    labels = [_candidate_label(record) for record in records]
    current = state.session_get(INSPECT_KEY)
    if current not in range(len(records)):
        current = 0
        state.session_set(INSPECT_KEY, current)
    selected = st.selectbox(
        "Candidate to inspect",
        options=range(len(records)),
        index=current,
        format_func=lambda index: labels[index],
        key=INSPECT_KEY,
    )
    record = records[selected]
    evaluation = record.evaluation
    if evaluation.feasible:
        st.success("This candidate satisfies every enforced hard constraint.")
    else:
        st.error(
            "Violations: " + "; ".join(evaluation.violated_constraints),
            title="Infeasible candidate",
        )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Objective": value.label,
                    "Raw value": value.raw_value,
                    "Unit": value.unit,
                    "Normalized": value.normalized_value,
                    "Weight": value.weight,
                    "Contribution": value.contribution,
                }
                for value in evaluation.objectives
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.markdown("**Constraint checks**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Constraint": result.name,
                    "Enforced": result.enforced,
                    "Passed": result.passed,
                    "Actual": result.actual,
                    "Threshold": result.threshold,
                    "Unit": result.unit,
                    "Detail": result.detail,
                }
                for result in evaluation.constraints
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.markdown("**Changes from the baseline**")
    try:
        changes = candidate_changes(twin, evaluation.candidate, run.settings)
    except (NetArchitectError, ValidationError, ValueError) as error:
        st.warning(
            "The current baseline no longer matches this run's design space: "
            + format_error(error)
        )
        return
    if changes:
        for change in changes:
            st.write(f"- {change}")
    else:
        st.info("This candidate keeps the baseline design unchanged.")
    _render_apply(run, twin, evaluation)


def _render_apply(run: OptimizationRun, twin: DigitalTwin, evaluation) -> None:
    st.markdown("**Apply this design**")
    st.caption(
        "Applying is explicit. Saving a snapshot leaves the baseline untouched; "
        "replacing the baseline changes the session's working design. Nothing is "
        "applied automatically."
    )
    try:
        built = build_candidate_twin(twin, evaluation.candidate, run.settings)
    except (NetArchitectError, ValidationError, ValueError) as error:
        st.error(format_error(error), title="Design cannot be applied")
        return

    label = st.text_input(
        "Snapshot label",
        value=f"{twin.metadata.name} optimized {datetime.now(UTC).strftime('%H:%M:%S')}",
        key=SNAPSHOT_LABEL_KEY,
    )
    columns = st.columns(2)
    with columns[0]:
        if st.button(
            "Save optimized design as snapshot",
            key="optimization_save_snapshot",
        ):
            try:
                state.save_twin_snapshot(built, label)
            except NetArchitectError as error:
                st.error(format_error(error), title="Snapshot rejected")
            else:
                _flash("success", f"Saved snapshot {label!r}.")
                st.rerun()
    with columns[1], st.expander("Replace baseline twin"):
        st.warning(
            "This replaces the session baseline with the optimized design. "
            "Existing snapshots and historical results are retained; other "
            "pages will read the new twin."
        )
        if st.button(
            "Replace baseline now",
            key="optimization_replace_baseline",
        ):
            state.replace_twin(built)
            _flash("success", "Replaced the baseline twin with the optimized design.")
            st.rerun()


def _render_exports(run: OptimizationRun) -> None:
    st.subheader("Export")
    st.caption(
        "JSON contains the seed, every setting, the baseline, and every "
        "evaluated candidate. CSV has one baseline row plus one row per "
        "candidate. Both are deterministic for this run."
    )
    slug = _safe_slug(f"{run.algorithm.value}-seed-{run.seed}")
    columns = st.columns(2)
    with columns[0]:
        st.download_button(
            "Download run JSON",
            data=run_to_json_bytes(run),
            file_name=f"{slug}-optimization.json",
            mime="application/json",
            key="optimization_download_json",
        )
    with columns[1]:
        st.download_button(
            "Download candidates CSV",
            data=run_to_csv(run).encode("utf-8"),
            file_name=f"{slug}-candidates.csv",
            mime="text/csv",
            key="optimization_download_csv",
        )


def _render_results(twin: DigitalTwin) -> None:
    run = _active_run()
    if run is None:
        st.info("Run an optimization to see baseline and optimized designs.")
        return
    _render_headline(run)
    _render_best_comparison(run)
    st.divider()
    _render_pareto_chart(run)
    st.divider()
    _render_candidates(run, twin)
    st.divider()
    _render_exports(run)


# ---------------------------------------------------------------------------
# History and algorithm comparison
# ---------------------------------------------------------------------------


def _run_label(index: int, run: OptimizationRun) -> str:
    best = "none" if run.best is None else f"{run.best.evaluation.weighted_score:.4f}"
    return (
        f"{index + 1}. {ALGORITHM_LABELS[run.algorithm].split(' (')[0]} | "
        f"seed {run.seed} | {run.stop_reason.value} | score {best}"
    )


def _render_history() -> None:
    runs = state.get_optimization_runs()
    st.subheader("Session history")
    st.caption(
        f"History is bounded to {MAX_OPTIMIZATION_RUNS} runs and lives only in "
        "this session. Each run records its algorithm, seed, settings, limits, "
        "evaluation count, and stop reason."
    )
    if not runs:
        st.info("No optimization runs retained yet.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Algorithm": ALGORITHM_LABELS[run.algorithm],
                    "Seed": run.seed,
                    "Stop reason": run.stop_reason.value,
                    "Evaluations": run.evaluations,
                    "Feasible best score": (
                        None
                        if run.best is None
                        else run.best.evaluation.weighted_score
                    ),
                    "Pareto candidates": len(run.pareto_front),
                }
                for run in runs
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    current = state.session_get(HISTORY_SELECT_KEY)
    if current not in range(len(runs)):
        current = len(runs) - 1
        state.session_set(HISTORY_SELECT_KEY, current)
    selected = st.selectbox(
        "Result to inspect",
        options=range(len(runs)),
        index=current,
        format_func=lambda index: _run_label(index, runs[index]),
        key=HISTORY_SELECT_KEY,
    )
    columns = st.columns(3)
    with columns[0]:
        if st.button("Load selected result", key="optimization_load_run"):
            state.session_set(VIEW_RUN_KEY, runs[selected])
            _flash("success", "Loaded the selected optimization run.")
            st.rerun()
    with columns[1]:
        if st.button("Delete selected result", key="optimization_delete_run"):
            removed = state.remove_optimization_run(selected)
            active = state.session_get(VIEW_RUN_KEY)
            remaining = state.get_optimization_runs()
            if active == removed:
                if remaining:
                    state.session_set(VIEW_RUN_KEY, remaining[-1])
                else:
                    state.session_delete(VIEW_RUN_KEY)
            _flash("success", "Deleted the selected optimization run.")
            st.rerun()
    with columns[2]:
        if st.button("Clear history", key="optimization_clear_history"):
            state.clear_optimization_history()
            state.session_delete(VIEW_RUN_KEY)
            _flash("success", "Cleared the optimization history.")
            st.rerun()


def _comparable_runs(active: OptimizationRun) -> tuple[OptimizationRun, ...]:
    settings = active.settings.model_dump(mode="json")
    return tuple(
        run
        for run in state.get_optimization_runs()
        if run.settings.model_dump(mode="json") == settings
        and run.baseline.candidate_hash == active.baseline.candidate_hash
    )


def _render_comparison() -> None:
    active = _active_run()
    st.subheader("Algorithm comparison")
    if active is None:
        st.info("Run at least one optimization to compare algorithms.")
        return
    runs = _comparable_runs(active)
    st.caption(
        "Only runs with identical settings, limits, and baseline are compared. "
        "Per-objective deltas are relative to the shared baseline; a trade-off "
        "is an objective that got worse."
    )
    if not runs:
        runs = (active,)
    if len(runs) < 2:
        st.info(
            "Run the same settings with another algorithm to compare best "
            "feasible candidates."
        )
    report = compare_runs(runs)
    st.caption(report.weight_note)
    rows = []
    for comparison in report.comparisons:
        deltas = {delta.kind.value: delta for delta in comparison.deltas}
        for delta in deltas.values():
            rows.append(
                {
                    "Algorithm": ALGORITHM_LABELS[comparison.algorithm],
                    "Stop reason": comparison.stop_reason.value,
                    "Evaluations": comparison.evaluations,
                    "Pareto candidates": len(comparison.pareto_front),
                    "Objective": delta.label,
                    "Baseline": delta.baseline_value,
                    "Best feasible": delta.candidate_value,
                    "Change": delta.absolute_change,
                    "Improved": delta.improved,
                    "Trade-off": (
                        ""
                        if delta.improved or delta.absolute_change == 0
                        else f"{delta.label} worsened"
                    ),
                }
            )
        if comparison.best is None:
            rows.append(
                {
                    "Algorithm": ALGORITHM_LABELS[comparison.algorithm],
                    "Stop reason": comparison.stop_reason.value,
                    "Evaluations": comparison.evaluations,
                    "Pareto candidates": len(comparison.pareto_front),
                    "Objective": "No feasible candidate",
                    "Baseline": None,
                    "Best feasible": None,
                    "Change": None,
                    "Improved": False,
                    "Trade-off": "no recommendation",
                }
            )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    for note in report.notes:
        st.caption(note)
    st.download_button(
        "Download comparison as CSV",
        data=csv_bytes(pd.DataFrame(rows)),
        file_name="optimization-comparison.csv",
        mime="text/csv",
        key="optimization_download_comparison",
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def _render_empty_state() -> None:
    st.info(
        "No digital twin with a topology is loaded. Open the Topology Editor "
        "from the sidebar to create, generate, or import one, then return here.",
        title="Digital twin required",
    )
    st.caption(
        "Optimization reads the baseline twin and never modifies it. Applying a "
        "result is a separate, explicit action."
    )


def _render_no_demands() -> None:
    st.info(
        "The baseline twin has no traffic demands. Add at least one demand on "
        "the Simulation Lab page so connectivity, served-demand ratio, and "
        "utilization can be evaluated.",
        title="Traffic demands required",
    )


def render() -> None:
    """Render the Optimization Center page."""
    st.title("Optimization Center")
    st.caption(
        "Bounded, reproducible multi-objective search over link additions, "
        "capacity tiers, and optional routing-cost adjustments. Every metric is "
        "a modeled estimate from stated assumptions."
    )
    st.info(SEARCH_NOTE, title="Search scope")
    _render_flash()

    twin = state.get_twin()
    if twin is None or not twin.topology.devices:
        _render_empty_state()
        return
    if not twin.demands:
        _render_no_demands()
        return

    prepared = _render_optimization_form(twin)
    if prepared is not None:
        settings, algorithm = prepared
        _run_and_store(twin, settings, algorithm)

    st.divider()
    _render_results(twin)
    st.divider()
    _render_history()
    st.divider()
    _render_comparison()
