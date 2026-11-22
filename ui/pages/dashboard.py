"""Dashboard page: a read-only overview of the current session.

The page reports only data already stored in session state. It does not create
a design, run an engine, or show placeholder numbers.
"""

from __future__ import annotations

import streamlit as st

from ui import formatting, i18n, state
from ui.components import (
    callout,
    empty_state,
    page_header,
    render_design_health,
    section_header,
)
from ui.sample_projects import (
    SAMPLE_PROJECTS,
    SampleProject,
    cancel_sample,
    load_sample,
    pending_sample,
    request_sample,
)


def _sample_summary(sample: SampleProject) -> str:
    """Render a sample summary from its stable display counts."""
    counts = [int(part.strip().split(" ", 1)[0]) for part in sample.summary.split("|")]
    return i18n.t(
        "sample.summary",
        devices=counts[0],
        links=counts[1],
        demands=counts[2],
    )


def _render_quick_start() -> None:
    """Render labeled samples; load one only after an explicit confirmation."""
    with st.container(border=True):
        section_header(
            i18n.t("dashboard.quick_start"),
            description=i18n.t("dashboard.quick_start.description"),
        )
        columns = st.columns(len(SAMPLE_PROJECTS))
        for column, sample in zip(columns, SAMPLE_PROJECTS, strict=True):
            with column:
                st.markdown(
                    f"**{i18n.sample_name(sample.key, sample.name)}**"
                )
                st.caption(i18n.sample_description(sample.key, sample.description))
                st.caption(_sample_summary(sample))
                st.button(
                    i18n.t("dashboard.sample.select"),
                    key=f"sample_select_{sample.key}",
                    help=i18n.t("dashboard.sample.select_help"),
                    on_click=request_sample,
                    args=(sample.key,),
                )

        pending = pending_sample()
        if pending is None:
            return

        current = state.peek_twin()
        if current is not None:
            target = i18n.t(
                "dashboard.sample.replace", name=i18n.ltr(current.metadata.name)
            )
        else:
            target = i18n.t("dashboard.sample.new")
        callout(
            i18n.t(
                "dashboard.sample.confirm_body",
                name=i18n.sample_name(pending.key, pending.name),
                target=target,
            ),
            kind="warn",
            title=i18n.t("dashboard.sample.confirm_title"),
        )
        confirm, cancel = st.columns(2)
        confirm.button(
            i18n.t("dashboard.sample.confirm"),
            key="sample_confirm_load",
            type="primary",
            on_click=load_sample,
            args=(pending.key,),
            kwargs={"confirmed": True},
        )
        cancel.button(
            i18n.t("common.cancel"),
            key="sample_cancel",
            on_click=cancel_sample,
        )


def render_dashboard() -> None:
    """Render the application overview from twin and session data."""
    page_header(i18n.t("page.dashboard"), i18n.t("page.dashboard.description"))
    _render_quick_start()

    twin = state.get_twin()
    if twin is None:
        empty_state(
            i18n.t("dashboard.empty.message"),
            title=i18n.t("dashboard.empty.title"),
            hint=i18n.t("dashboard.empty.hint"),
        )
        return

    if state.has_unsaved_bundle_changes():
        callout(i18n.t("bundle.unsaved"), kind="warn")

    topology = twin.topology
    snapshots = state.peek_snapshots()
    scenarios = state.peek_simulation_runs()
    optimizations = state.peek_optimization_runs()

    columns = st.columns(6)
    columns[0].metric(i18n.t("dashboard.metric.devices"), len(topology.devices))
    columns[1].metric(i18n.t("dashboard.metric.links"), len(topology.links))
    columns[2].metric(i18n.t("dashboard.metric.demands"), len(twin.demands))
    columns[3].metric(i18n.t("dashboard.metric.snapshots"), len(snapshots))
    columns[4].metric(i18n.t("dashboard.metric.scenario_runs"), len(scenarios))
    columns[5].metric(
        i18n.t("dashboard.metric.optimization_runs"), len(optimizations)
    )

    addressing = twin.addressing
    st.caption(
        i18n.t(
            "dashboard.twin_caption",
            name=i18n.ltr(twin.metadata.name),
            schema=i18n.ltr(twin.metadata.schema_version),
            created=i18n.ltr(twin.metadata.created_at.isoformat()),
            subnets=len(addressing.subnets) if addressing is not None else 0,
            vlans=len(addressing.vlan_plans) if addressing is not None else 0,
            dhcp=len(twin.dhcp_scopes),
        )
    )

    render_design_health(twin)

    st.subheader(i18n.t("dashboard.retained_runs"))
    if not scenarios and not optimizations:
        empty_state(i18n.t("dashboard.runs_empty"))
        return

    latest_columns = st.columns(2)
    with latest_columns[0]:
        if scenarios:
            run = scenarios[-1]
            status = (
                i18n.t("dashboard.recovery")
                if run.comparison.recovery_available
                else i18n.t("dashboard.not_recovered")
            )
            st.metric(
                i18n.t("dashboard.latest_scenario"),
                formatting.ratio(
                    run.comparison.scenario_served_demand_ratio, decimals=1
                ),
                help=i18n.t(
                    "dashboard.scenario_help",
                    name=i18n.ltr(run.scenario.name),
                    status=status,
                ),
            )
            st.caption(
                i18n.t(
                    "dashboard.scenario_caption",
                    name=i18n.ltr(run.scenario.name),
                    type=i18n.ltr(run.scenario.type.value),
                    status=status,
                    count=len(run.comparison.newly_unserved_demands),
                )
            )
        else:
            st.caption(i18n.t("dashboard.no_scenarios"))

    with latest_columns[1]:
        if optimizations:
            run = optimizations[-1]
            st.metric(
                i18n.t("dashboard.latest_optimization"),
                run.evaluations,
                help=i18n.t(
                    "dashboard.optimization_help",
                    algorithm=i18n.ltr(run.algorithm.value),
                    reason=i18n.ltr(run.stop_reason.value),
                ),
            )
            st.caption(
                i18n.t(
                    "dashboard.optimization_caption",
                    algorithm=i18n.ltr(run.algorithm.value),
                    reason=i18n.ltr(run.stop_reason.value),
                    count=len(run.pareto_front),
                    best=(
                        i18n.t("dashboard.feasible_best")
                        if run.best is not None
                        else i18n.t("dashboard.no_feasible_best")
                    ),
                )
            )
        else:
            st.caption(i18n.t("dashboard.no_optimizations"))


__all__ = ["render_dashboard"]
