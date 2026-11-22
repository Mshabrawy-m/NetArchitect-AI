"""L2 Design page for bounded, deterministic L2/WAN/wireless/QoS planning.

The page is presentation only. Every modeled value comes from the W1-W4
engines; applying an editor stores a typed plan on the in-memory digital twin.
Nothing here configures equipment, exchanges a protocol, estimates RF, or
simulates queues or packets.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.exceptions import NetArchitectError
from digital_twin import DigitalTwin
from network.l2.models import EtherChannelBundle, L2Design
from network.l2.switching import analyze_l2_design
from network.qos.admission import build_qos_admission_plan
from network.qos.models import ClassShareCap, QosDesign, TrafficClass
from network.qos.review import qos_findings
from network.wan.models import SiteType, WanDesign
from network.wan.planning import analyze_wan_design
from network.wireless.models import WirelessArea, WirelessDesign
from network.wireless.planning import analyze_wireless_design
from services.copilot import (
    l2_design_request,
    qos_design_request,
    wan_design_request,
    wireless_design_request,
)
from simulation import SimulationAssumptions
from simulation.evaluator import evaluate
from simulation.models import RoutingMode
from ui import i18n, state, theme
from ui.cache import (
    L2_REVIEW_SECTIONS,
    L2DesignReview,
    cached_l2_design_review,
    l2_review_key,
    twin_cache_key,
    twin_payload,
)
from ui.components import (
    empty_state,
    format_error,
    page_header,
    render_design_health,
    section_header,
)
from ui.components.copilot import why_button
from ui.components.editors import bump_editor_key, editor_key
from ui.components.notices import queue_notice, render_notices

PAGE_TITLE = "L2 Design"
MODEL_NOTE = (
    "Modeled design rules only: no device access, protocol exchange, RF survey, "
    "queue simulation, packet behavior, or live measurement is performed."
)

L2_EDITOR_BASE = "l2_design_editor"
L2_GATEWAYS_KEY = "l2_gateway_by_vlan"
L2_ROOTS_KEY = "l2_root_priorities"
L2_THRESHOLD_KEY = "l2_vlan_spread_threshold"
L2_APPLY_KEY = "l2_apply_design"
L2_CLEAR_KEY = "l2_clear_design"
L2_WHY_KEY = "l2_why_l2_design"
L2_COLUMNS = ("id", "name", "link_ids", "rationale")

WAN_EDITOR_BASE = "wan_design_editor"
WAN_APPLY_KEY = "wan_apply_design"
WAN_CLEAR_KEY = "wan_clear_design"
WAN_WHY_KEY = "l2_why_wan_design"
WAN_COLUMNS = ("site_id", "site_type", "hq")

WIRELESS_EDITOR_BASE = "wireless_editor"
WIRELESS_APPLY_KEY = "wireless_apply_design"
WIRELESS_CLEAR_KEY = "wireless_clear_design"
WIRELESS_WHY_KEY = "l2_why_wireless_design"
WIRELESS_COLUMNS = (
    "id",
    "name",
    "area_m2",
    "clients",
    "client_density_per_100m2",
    "client_mbps",
    "ap_capacity_mbps",
    "coverage_radius_m",
    "utilization_target",
    "overlap_factor",
    "uplink_switch_id",
)

QOS_EDITOR_BASE = "qos_editor"
QOS_DEFAULT_CLASS_KEY = "l2_qos_default_class"
QOS_APPLY_KEY = "qos_apply_design"
QOS_CLEAR_KEY = "qos_clear_design"
QOS_WHY_KEY = "l2_why_qos_design"
QOS_COLUMNS = ("link_id", "traffic_class", "share_cap")

REVIEW_RUN_KEY = "l2_review_run"
REVIEW_CANCEL_BUTTON_KEY = "l2_review_cancel_button"
REVIEW_CLEAR_KEY = "l2_review_clear"
REVIEW_RUNNING_KEY = "l2_review_running"
REVIEW_CANCEL_KEY = "l2_review_cancel"
REVIEW_CURSOR_KEY = "l2_review_cursor"
REVIEW_PIECES_KEY = "l2_review_pieces"
REVIEW_KEY_KEY = "l2_review_key"
REVIEW_RESULT_KEY = "l2_review_result"
REVIEW_COMPLETIONS_KEY = "l2_review_completions"
REVIEW_KEYS = (
    REVIEW_RUNNING_KEY,
    REVIEW_CANCEL_KEY,
    REVIEW_CURSOR_KEY,
    REVIEW_PIECES_KEY,
    REVIEW_KEY_KEY,
    REVIEW_RESULT_KEY,
    REVIEW_COMPLETIONS_KEY,
)

REVIEW_DONE = "completed"
REVIEW_CANCELLED = "cancelled"
REVIEW_EMPTY = "empty"
REVIEW_INCOMPLETE = "incomplete"

SECTION_FIELDS: dict[str, tuple[str, ...]] = {
    "l2": ("l2_loops", "l2_blocked_links", "l2_bundles", "l2_findings"),
    "wan": (
        "wan_links",
        "wan_site_ids",
        "wan_total_monthly_cost_proxy",
        "wan_findings",
    ),
    "wireless": (
        "wireless_areas",
        "wireless_total_aps",
        "wireless_total_uplink_mbps",
        "wireless_findings",
    ),
    "qos": ("qos_caps", "qos_default_class", "qos_findings"),
}


@dataclass(frozen=True)
class ReviewBootstrap:
    """Pure UI state derived before any review slice is evaluated."""

    cursor: int
    stop_reason: str | None
    seed_reason: str | None


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _csv(value: object) -> tuple[str, ...]:
    return tuple(part.strip() for part in _text(value).split(",") if part.strip())


def _integer(value: object, default: int = 0) -> int:
    text = _text(value)
    return int(float(text)) if text else default


def _number(value: object, default: float = 0.0) -> float:
    text = _text(value)
    return float(text) if text else default


def _boolean(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "y"}


def _pairs(
    text: object,
    *,
    key_cast: Callable[[str], object] = str,
    value_cast: Callable[[str], object] = str,
    label: str = "Entry",
) -> dict[object, object]:
    pairs: dict[object, object] = {}
    for entry in _csv(text):
        if "=" not in entry:
            raise ValueError(f"{label} entries must use key=value form: {entry!r}")
        key_text, value_text = entry.split("=", 1)
        pairs[key_cast(key_text.strip())] = value_cast(value_text.strip())
    return pairs


def _frame(rows: list[dict[str, object]], columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(columns))


def _findings_frame(findings: Sequence[tuple[str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(findings, columns=["Severity", "Code", "Explanation"])


def _accent(token: str, text: str) -> None:
    """Render a section label using one theme-owned accent token."""
    st.markdown(
        f'<span style="color:{theme.color(token)};font-weight:600;">'
        f"{i18n.tx(text)}</span>",
        unsafe_allow_html=True,
    )


def _scope_note() -> None:
    st.markdown(
        f'<span style="color:{theme.color("info")};font-weight:600;">'
        f"{i18n.t('l2.scope')}</span>",
        unsafe_allow_html=True,
    )


def _review(twin: DigitalTwin) -> L2DesignReview:
    return cached_l2_design_review(
        twin_payload(twin),
        twin_cache_key(twin),
        L2_REVIEW_SECTIONS,
    )


def _apply(
    twin: DigitalTwin,
    *,
    field: str,
    editor_base: str,
    build: Callable[[], object],
    success: str,
) -> None:
    """Build, store, and announce one optional W1-W4 model."""
    try:
        candidate = build()
        updated = twin.model_copy(update={field: candidate})
        state.replace_twin(updated)
    except (NetArchitectError, ValidationError, ValueError) as error:
        bump_editor_key(editor_base)
        queue_notice("error", format_error(error), title="Model not saved")
    else:
        queue_notice("success", success)
    st.rerun()


def _clear(twin: DigitalTwin, *, field: str, message: str) -> None:
    state.replace_twin(twin.model_copy(update={field: None}))
    queue_notice("info", message)
    st.rerun()


def _l2_frame(twin: DigitalTwin) -> pd.DataFrame:
    design = twin.l2_design
    if design is not None:
        rows = [
            {
                "id": bundle.id,
                "name": bundle.name,
                "link_ids": ", ".join(bundle.link_ids),
                "rationale": bundle.rationale,
            }
            for bundle in design.etherchannel_bundles
        ]
    else:
        links = tuple(link.id for link in twin.topology.links[:2])
        rows = (
            [
                {
                    "id": "bundle-1",
                    "name": "Modeled parallel links",
                    "link_ids": ", ".join(links),
                    "rationale": "Modeled parallel-link bundle.",
                }
            ]
            if len(links) >= 2
            else []
        )
    return _frame(rows, L2_COLUMNS)


def _wan_frame(twin: DigitalTwin) -> pd.DataFrame:
    design = twin.wan_design
    if design is not None:
        site_ids = tuple(sorted(design.site_types))
        types = design.site_types
    else:
        site_ids = tuple(sorted({device.site for device in twin.topology.devices}))
        types = {}
    rows = []
    for site_id in site_ids:
        lowered = site_id.lower()
        inferred = (
            SiteType.hq
            if "hq" in lowered
            else SiteType.dc
            if "dc" in lowered
            else SiteType.cloud
            if "cloud" in lowered
            else SiteType.branch
        )
        site_type = types.get(site_id, inferred)
        hq = (
            site_id in design.hq_site_ids
            if design is not None
            else site_type in {SiteType.hq, SiteType.dc}
        )
        rows.append(
            {
                "site_id": site_id,
                "site_type": site_type.value,
                "hq": hq,
            }
        )
    return _frame(rows, WAN_COLUMNS)


def _wireless_frame(twin: DigitalTwin) -> pd.DataFrame:
    design = twin.wireless_design
    areas = design.areas if design is not None else ()
    if areas:
        rows = [dict(area.model_dump()) for area in areas]
    else:
        default = WirelessArea(id="area-1", name="Users", area_m2=400.0, clients=100)
        rows = [dict(default.model_dump())]
    return _frame(rows, WIRELESS_COLUMNS)


def _qos_frame(twin: DigitalTwin) -> pd.DataFrame:
    design = twin.qos_design
    if design is not None:
        rows = [
            {
                "link_id": cap.link_id,
                "traffic_class": cap.traffic_class.value,
                "share_cap": cap.share_cap,
            }
            for cap in design.class_share_caps
        ]
    else:
        link_id = ""
        for link in twin.topology.links:
            link_id = link.id
            break
        rows = (
            [
                {
                    "link_id": link_id,
                    "traffic_class": TrafficClass.best_effort.value,
                    "share_cap": 0.5,
                }
            ]
            if link_id
            else []
        )
    return _frame(rows, QOS_COLUMNS)


def _l2_design_from_frame(
    edited: pd.DataFrame,
    *,
    gateways: object,
    roots: object,
    threshold: object,
) -> L2Design:
    bundles = tuple(
        EtherChannelBundle(
            id=_text(row.get("id")),
            name=_text(row.get("name")),
            link_ids=_csv(row.get("link_ids")),
            rationale=_text(row.get("rationale")),
        )
        for row in edited.to_dict("records")
    )
    return L2Design(
        gateway_by_vlan=_pairs(
            gateways,
            key_cast=_integer,
            label="Gateway VLAN",
        ),  # type: ignore[arg-type]
        root_priorities=_pairs(
            roots,
            value_cast=_integer,
            label="Root priority",
        ),  # type: ignore[arg-type]
        vlan_spread_threshold=_integer(threshold, 4) or 4,
        etherchannel_bundles=bundles,
    )


def _wan_design_from_frame(edited: pd.DataFrame) -> WanDesign:
    site_types: dict[str, SiteType] = {}
    hq_site_ids: list[str] = []
    for row in edited.to_dict("records"):
        site_id = _text(row.get("site_id"))
        if not site_id:
            raise ValueError("WAN site ids must be non-empty.")
        site_types[site_id] = SiteType(_text(row.get("site_type")))
        if _boolean(row.get("hq")):
            hq_site_ids.append(site_id)
    return WanDesign(site_types=site_types, hq_site_ids=tuple(hq_site_ids))


def _wireless_design_from_frame(edited: pd.DataFrame) -> WirelessDesign:
    areas = tuple(
        WirelessArea(
            id=_text(row.get("id")),
            name=_text(row.get("name")),
            area_m2=_number(row.get("area_m2")),
            clients=_integer(row.get("clients")),
            client_density_per_100m2=_number(row.get("client_density_per_100m2"), 20.0),
            client_mbps=_number(row.get("client_mbps"), 10.0),
            ap_capacity_mbps=_number(row.get("ap_capacity_mbps"), 100.0),
            coverage_radius_m=_number(row.get("coverage_radius_m"), 20.0),
            utilization_target=_number(row.get("utilization_target"), 0.7),
            overlap_factor=_number(row.get("overlap_factor"), 0.8),
            uplink_switch_id=_text(row.get("uplink_switch_id")) or None,
        )
        for row in edited.to_dict("records")
    )
    return WirelessDesign(areas=areas)


def _qos_design_from_frame(edited: pd.DataFrame, default_class: object) -> QosDesign:
    caps = tuple(
        ClassShareCap(
            link_id=_text(row.get("link_id")),
            traffic_class=TrafficClass(_text(row.get("traffic_class"))),
            share_cap=_number(row.get("share_cap"), 0.5),
        )
        for row in edited.to_dict("records")
    )
    return QosDesign(
        default_class=TrafficClass(_text(default_class)),
        class_share_caps=caps,
    )


def render_l2_tab(twin: DigitalTwin) -> None:
    """Render the modeled Layer-2 bundle editor and loop summary."""
    _accent("l2_accent", "Layer-2 switching")
    review = _review(twin)
    section_header("Modeled Layer-2 design")
    if review.l2_loops:
        st.dataframe(
            pd.DataFrame(
                review.l2_loops,
                columns=["VLAN", "Root bridge", "Cycle rank", "Blocked links"],
            ),
            hide_index=True,
            width="stretch",
            alt="Modeled per-VLAN Layer-2 loop review",
        )
        st.caption(
            "Cycle rank is links minus switches plus components. Blocking is a "
            "deterministic minimum spanning forest choice, not a running STP "
            "instance."
        )
    else:
        st.caption("No Layer-2 loop review is available for this topology.")
    if review.l2_bundles:
        st.dataframe(
            pd.DataFrame(
                review.l2_bundles,
                columns=["Bundle", "Capacity (Mbps)", "Down", "Member links"],
            ),
            hide_index=True,
            width="stretch",
            alt="Modeled EtherChannel bundle capacities",
        )
    if review.l2_findings:
        with st.expander(f"Design findings ({len(review.l2_findings)})"):
            st.dataframe(
                _findings_frame(review.l2_findings),
                hide_index=True,
                width="stretch",
                alt="Layer-2 design findings",
            )
    if twin.l2_design is not None:
        design = twin.l2_design

        def build_request():
            return l2_design_request(design, analyze_l2_design(twin, design=design))

        why_button(L2_WHY_KEY, build_request)

    section_header("Edit Layer-2 design", divider=True)
    st.caption(
        "List VLAN gateways and root priorities as comma-separated key=value "
        "pairs. Bundles reference existing topology link ids only."
    )
    edited = st.data_editor(
        _l2_frame(twin),
        key=editor_key(L2_EDITOR_BASE),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        alt="Editable EtherChannel bundles",
    )
    gateway_text = st.text_input(
        "Gateway by VLAN (for example 10=r1,20=r2)",
        value=", ".join(
            f"{vlan_id}={device_id}"
            for vlan_id, device_id in sorted(
                twin.l2_design.gateway_by_vlan.items() if twin.l2_design else ()
            )
        ),
        key=L2_GATEWAYS_KEY,
    )
    root_text = st.text_input(
        "Root priority by switch (for example sw1=4096)",
        value=", ".join(
            f"{device_id}={priority}"
            for device_id, priority in sorted(
                twin.l2_design.root_priorities.items() if twin.l2_design else ()
            )
        ),
        key=L2_ROOTS_KEY,
    )
    threshold = st.number_input(
        "VLAN sprawl heuristic (switches, not a protocol limit)",
        min_value=1,
        value=twin.l2_design.vlan_spread_threshold if twin.l2_design else 4,
        key=L2_THRESHOLD_KEY,
    )
    apply_col, clear_col = st.columns(2)
    if apply_col.button("Apply Layer-2 design", key=L2_APPLY_KEY):
        _apply(
            twin,
            field="l2_design",
            editor_base=L2_EDITOR_BASE,
            build=lambda: _l2_design_from_frame(
                edited,
                gateways=gateway_text,
                roots=root_text,
                threshold=threshold,
            ),
            success="Layer-2 switching design saved to the twin.",
        )
    if clear_col.button("Clear Layer-2 design", key=L2_CLEAR_KEY):
        _clear(twin, field="l2_design", message="Layer-2 switching design cleared.")


def render_wan_tab(twin: DigitalTwin) -> None:
    """Render the modeled WAN site editor and cost/link summary."""
    _accent("wan_accent", "WAN and multi-site")
    review = _review(twin)
    section_header("Modeled WAN design")
    if review.wan_links:
        st.dataframe(
            pd.DataFrame(
                review.wan_links,
                columns=[
                    "Link",
                    "Source site",
                    "Target site",
                    "Type",
                    "Capacity (Mbps)",
                    "Monthly proxy",
                    "Latency (ms)",
                ],
            ),
            hide_index=True,
            width="stretch",
            alt="Modeled active inter-site WAN links",
        )
    st.caption(
        f"Modeled sites: {', '.join(review.wan_site_ids) or 'none'}. "
        f"Monthly cost proxy: {review.wan_total_monthly_cost_proxy:g}. "
        "Costs and latency are stated assumptions, not measurements."
    )
    if review.wan_findings:
        with st.expander(f"Design findings ({len(review.wan_findings)})"):
            st.dataframe(
                _findings_frame(review.wan_findings),
                hide_index=True,
                width="stretch",
                alt="WAN design findings",
            )
    if twin.wan_design is not None:
        design = twin.wan_design

        def build_request():
            return wan_design_request(
                design,
                analyze_wan_design(twin, design=design, include_expensive=False),
            )

        why_button(WAN_WHY_KEY, build_request)

    section_header("Edit WAN sites", divider=True)
    st.caption(
        "Set a modeled type per site and mark the HQ/DC targets branches are "
        "expected to reach. Types are design facts, not discovered roles."
    )
    edited = st.data_editor(
        _wan_frame(twin),
        key=editor_key(WAN_EDITOR_BASE),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        alt="Editable modeled WAN sites",
    )
    apply_col, clear_col = st.columns(2)
    if apply_col.button("Apply WAN design", key=WAN_APPLY_KEY):
        _apply(
            twin,
            field="wan_design",
            editor_base=WAN_EDITOR_BASE,
            build=lambda: _wan_design_from_frame(edited),
            success="WAN site design saved to the twin.",
        )
    if clear_col.button("Clear WAN design", key=WAN_CLEAR_KEY):
        _clear(twin, field="wan_design", message="WAN site design cleared.")


def render_wireless_tab(twin: DigitalTwin) -> None:
    """Render the abstract wireless area editor and AP estimate."""
    _accent("wireless_accent", "Abstract wireless")
    review = _review(twin)
    section_header("Modeled wireless estimate")
    if review.wireless_areas:
        st.dataframe(
            pd.DataFrame(
                review.wireless_areas,
                columns=[
                    "Area",
                    "Name",
                    "Clients",
                    "Capacity APs",
                    "Recommended APs",
                    "Binding",
                    "Uplink (Mbps)",
                ],
            ),
            hide_index=True,
            width="stretch",
            alt="Modeled wireless AP estimates",
        )
    st.caption(
        f"Recommended APs: {review.wireless_total_aps}. Total modeled uplink: "
        f"{review.wireless_total_uplink_mbps:g} Mbps. No RF propagation or "
        "site survey is modeled."
    )
    if review.wireless_findings:
        with st.expander(f"Design findings ({len(review.wireless_findings)})"):
            st.dataframe(
                _findings_frame(review.wireless_findings),
                hide_index=True,
                width="stretch",
                alt="Wireless design findings",
            )
    if twin.wireless_design is not None:
        design = twin.wireless_design

        def build_request():
            return wireless_design_request(design, analyze_wireless_design(design))

        why_button(WIRELESS_WHY_KEY, build_request)

    section_header("Edit wireless areas", divider=True)
    st.caption(
        "AP counts are ceilings from stated clients, area, AP capacity, and "
        "circular coverage assumptions. Clients are never enumerated."
    )
    edited = st.data_editor(
        _wireless_frame(twin),
        key=editor_key(WIRELESS_EDITOR_BASE),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        alt="Editable abstract wireless areas",
    )
    apply_col, clear_col = st.columns(2)
    if apply_col.button("Apply wireless design", key=WIRELESS_APPLY_KEY):
        _apply(
            twin,
            field="wireless_design",
            editor_base=WIRELESS_EDITOR_BASE,
            build=lambda: _wireless_design_from_frame(edited),
            success="Abstract wireless design saved to the twin.",
        )
    if clear_col.button("Clear wireless design", key=WIRELESS_CLEAR_KEY):
        _clear(twin, field="wireless_design", message="Abstract wireless design cleared.")


def render_qos_tab(twin: DigitalTwin) -> None:
    """Render the modeled QoS admission editor and bounded findings."""
    _accent("qos_accent", "QoS admission")
    review = _review(twin)
    section_header("Modeled QoS design")
    if review.qos_caps:
        st.dataframe(
            pd.DataFrame(
                review.qos_caps,
                columns=["Link", "Traffic class", "Share cap"],
            ),
            hide_index=True,
            width="stretch",
            alt="Modeled QoS class share caps",
        )
    else:
        st.caption("No class share caps are stored on the twin.")
    st.caption(
        f"Default class: {review.qos_default_class or 'none'}. This is an "
        "admission model only; no queue, drop, scheduler, or device hardware "
        "behavior is represented."
    )
    if review.qos_findings:
        with st.expander(f"Design findings ({len(review.qos_findings)})"):
            st.dataframe(
                _findings_frame(review.qos_findings),
                hide_index=True,
                width="stretch",
                alt="QoS design findings",
            )
    if twin.qos_design is not None:
        design = twin.qos_design
        network_state = evaluate(
            twin,
            SimulationAssumptions(
                routing_mode=RoutingMode.capacity_aware,
                enable_strict_priority_qos=True,
            ),
        )
        findings = qos_findings(twin, network_state, design=design)

        def build_request():
            return qos_design_request(
                design,
                build_qos_admission_plan(twin, design),
                findings,
            )

        why_button(QOS_WHY_KEY, build_request)

    section_header("Edit QoS admission", divider=True)
    st.caption(
        "Share caps are fractions of modeled link capacity (0..1). Traffic "
        "classes follow the documented strict-priority order."
    )
    default_class = st.selectbox(
        "Default traffic class",
        options=tuple(item.value for item in TrafficClass),
        index=(
            tuple(item.value for item in TrafficClass).index(
                twin.qos_design.default_class.value
            )
            if twin.qos_design is not None
            else 0
        ),
        key=QOS_DEFAULT_CLASS_KEY,
    )
    edited = st.data_editor(
        _qos_frame(twin),
        key=editor_key(QOS_EDITOR_BASE),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        alt="Editable modeled QoS class caps",
    )
    apply_col, clear_col = st.columns(2)
    if apply_col.button("Apply QoS design", key=QOS_APPLY_KEY):
        _apply(
            twin,
            field="qos_design",
            editor_base=QOS_EDITOR_BASE,
            build=lambda: _qos_design_from_frame(edited, default_class),
            success="QoS admission design saved to the twin.",
        )
    if clear_col.button("Clear QoS design", key=QOS_CLEAR_KEY):
        _clear(twin, field="qos_design", message="QoS admission design cleared.")


def _review_bootstrap(
    *,
    total: int,
    cursor: int,
    pieces: Sequence[L2DesignReview],
    cancelled: bool,
) -> ReviewBootstrap:
    """Normalize first-run, empty, cancelled, and completed review state.

    ``pieces`` is the authority for completed work. A stale cursor with no
    pieces is reset to zero, and ``stop_reason`` stays ``None`` until a piece
    exists so an empty first run never reads a missing result.
    """
    completed = len(pieces)
    stop_reason: str | None = None
    for piece in pieces:
        stop_reason = piece.status
    seed_reason: str | None = None
    if not pieces:
        if total == 0:
            seed_reason = REVIEW_EMPTY
        elif cancelled:
            seed_reason = REVIEW_CANCELLED
        elif cursor >= total:
            seed_reason = REVIEW_DONE
    if cancelled:
        stop_reason = REVIEW_CANCELLED
    cursor = completed
    if completed > total:
        cursor = total
    if not pieces:
        cursor = 0
    return ReviewBootstrap(
        cursor=cursor,
        stop_reason=stop_reason,
        seed_reason=seed_reason,
    )


def _merge_reviews(
    pieces: Sequence[L2DesignReview],
    *,
    key: str,
    status: str,
) -> L2DesignReview:
    """Merge bounded slices into one deterministic, reportable review."""
    result = L2DesignReview(
        twin_version=key,
        sections=L2_REVIEW_SECTIONS,
        status=status,
    )
    updates: dict[str, object] = {}
    for piece in pieces:
        for section in piece.sections:
            for field in SECTION_FIELDS.get(section, ()):
                updates[field] = getattr(piece, field)
    return replace(result, **updates)


def _review_frame(review: L2DesignReview) -> pd.DataFrame:
    rows = [
        {
            "Section": "Layer-2 switching",
            "Findings": len(review.l2_findings),
            "Summary": (
                f"{len(review.l2_loops)} VLAN review(s); "
                f"{len(review.l2_blocked_links)} blocked link(s); "
                f"{len(review.l2_bundles)} bundle(s)"
            ),
        },
        {
            "Section": "WAN and multi-site",
            "Findings": len(review.wan_findings),
            "Summary": (
                f"{len(review.wan_site_ids)} site(s); {len(review.wan_links)} "
                f"active link(s); proxy {review.wan_total_monthly_cost_proxy:g}"
            ),
        },
        {
            "Section": "Abstract wireless",
            "Findings": len(review.wireless_findings),
            "Summary": (
                f"{len(review.wireless_areas)} area(s); "
                f"{review.wireless_total_aps} recommended AP(s); "
                f"uplink {review.wireless_total_uplink_mbps:g} Mbps"
            ),
        },
        {
            "Section": "QoS admission",
            "Findings": len(review.qos_findings),
            "Summary": (
                f"default {review.qos_default_class or 'none'}; "
                f"{len(review.qos_caps)} modeled cap(s)"
            ),
        },
    ]
    return pd.DataFrame(rows, columns=["Section", "Findings", "Summary"])


def _clear_review() -> None:
    for key in REVIEW_KEYS:
        state.session_delete(key)


def _start_review() -> None:
    state.session_set(REVIEW_RUNNING_KEY, True)
    state.session_set(REVIEW_CANCEL_KEY, False)
    state.session_set(REVIEW_CURSOR_KEY, 0)
    state.session_set(REVIEW_PIECES_KEY, ())
    state.session_set(REVIEW_KEY_KEY, "")
    state.session_set(REVIEW_RESULT_KEY, None)


def _cancel_review() -> None:
    state.session_set(REVIEW_CANCEL_KEY, True)


def _stored_pieces() -> tuple[L2DesignReview, ...]:
    stored = state.session_get(REVIEW_PIECES_KEY, ())
    if isinstance(stored, (tuple, list)):
        return tuple(
            piece for piece in stored if isinstance(piece, L2DesignReview)
        )
    return ()


@st.fragment
def _run_review_fragment(twin: DigitalTwin) -> None:
    """Run four bounded slices in this fragment; no worker or thread is used."""
    key = l2_review_key(twin)
    stored_key = state.session_get(REVIEW_KEY_KEY, "")
    if stored_key and stored_key != key:
        _clear_review()
        state.session_set(REVIEW_KEY_KEY, key)
        state.session_set(REVIEW_CURSOR_KEY, 0)
        state.session_set(REVIEW_PIECES_KEY, ())
        state.session_set(REVIEW_RUNNING_KEY, False)
        st.warning(
            "The twin changed during the review; the cursor was reset.",
            title="Review reset",
        )
        return
    state.session_set(REVIEW_KEY_KEY, key)

    if state.session_get(REVIEW_RESULT_KEY) is not None:
        state.session_set(REVIEW_RUNNING_KEY, False)
        return

    cancelled = bool(state.session_get(REVIEW_CANCEL_KEY, False))
    pieces = _stored_pieces()
    bootstrap = _review_bootstrap(
        total=len(L2_REVIEW_SECTIONS),
        cursor=state.session_get(REVIEW_CURSOR_KEY, 0),
        pieces=pieces,
        cancelled=cancelled,
    )
    cursor = bootstrap.cursor
    status = bootstrap.stop_reason
    state.session_set(REVIEW_CURSOR_KEY, cursor)

    if bootstrap.seed_reason is not None:
        pieces = (
            L2DesignReview(
                twin_version=key,
                sections=(),
                status=bootstrap.seed_reason,
            ),
        )
        status = bootstrap.seed_reason
        state.session_set(REVIEW_PIECES_KEY, pieces)

    progress = st.progress(
        cursor / len(L2_REVIEW_SECTIONS),
        text=f"Reviewed {cursor} of {len(L2_REVIEW_SECTIONS)} sections...",
    )
    for section in L2_REVIEW_SECTIONS[cursor:]:
        if bool(state.session_get(REVIEW_CANCEL_KEY, False)):
            break
        piece = cached_l2_design_review(
            twin_payload(twin),
            twin_cache_key(twin),
            (section,),
        )
        pieces += (piece,)
        cursor += 1
        status = piece.status
        state.session_set(REVIEW_PIECES_KEY, pieces)
        state.session_set(REVIEW_CURSOR_KEY, cursor)
        progress.progress(
            cursor / len(L2_REVIEW_SECTIONS),
            text=f"Reviewed {cursor} of {len(L2_REVIEW_SECTIONS)} sections...",
        )

    cancelled = bool(state.session_get(REVIEW_CANCEL_KEY, False))
    if status in {REVIEW_CANCELLED, REVIEW_EMPTY}:
        final_status = status
    elif cursor >= len(L2_REVIEW_SECTIONS):
        final_status = REVIEW_DONE
    elif cancelled:
        final_status = REVIEW_CANCELLED
    else:
        final_status = REVIEW_INCOMPLETE
    result = _merge_reviews(pieces, key=key, status=final_status)
    completions = int(state.session_get(REVIEW_COMPLETIONS_KEY, 0) or 0)
    state.session_set(REVIEW_COMPLETIONS_KEY, completions + 1)
    state.session_set(REVIEW_RESULT_KEY, result)
    state.session_set(REVIEW_RUNNING_KEY, False)
    state.session_set(REVIEW_CANCEL_KEY, False)
    state.session_set(REVIEW_PIECES_KEY, ())
    state.session_set(REVIEW_CURSOR_KEY, 0)
    progress.progress(
        1.0 if final_status == REVIEW_DONE else cursor / len(L2_REVIEW_SECTIONS),
        text=f"Finished with status {final_status}.",
    )
    st.rerun(scope="app")


def _render_review(twin: DigitalTwin) -> None:
    _accent("findings_accent", "Bounded design review")
    section_header("Review progress")
    st.caption(
        "Four fixed, synchronous sections are reviewed from the current twin. "
        "Cancel stops before the next section; Clear drops every stored result."
    )
    running = bool(state.session_get(REVIEW_RUNNING_KEY, False))
    result = state.session_get(REVIEW_RESULT_KEY)
    if not isinstance(result, L2DesignReview):
        result = None
    if result is not None and result.twin_version != l2_review_key(twin):
        result = None

    run_col, cancel_col, clear_col = st.columns(3)
    run_col.button(
        i18n.t("l2.review.run"),
        key=REVIEW_RUN_KEY,
        on_click=_start_review,
        type="primary",
        disabled=running,
    )
    cancel_col.button(
        i18n.t("l2.review.cancel"),
        key=REVIEW_CANCEL_BUTTON_KEY,
        on_click=_cancel_review,
        disabled=not running,
    )
    clear_col.button(
        i18n.t("l2.review.clear"),
        key=REVIEW_CLEAR_KEY,
        on_click=_clear_review,
    )

    if running:
        st.info(i18n.t("l2.review.running"))
        _run_review_fragment(twin)

    if result is None:
        st.info(i18n.t("l2.review.empty"))
        return
    if result.status == REVIEW_CANCELLED:
        st.warning(i18n.t("l2.review.running") + " " + result.status)
    elif result.status == REVIEW_EMPTY:
        st.info(i18n.t("l2.review.empty"))
    else:
        st.success(i18n.t("l2.review.done"))
    st.dataframe(
        _review_frame(result),
        hide_index=True,
        width="stretch",
        alt="Bounded L2 design review summary",
    )


def render() -> None:
    """Render the L2 Design page."""
    page_header(PAGE_TITLE, i18n.t("page.l2_design.description"))
    render_notices()
    st.info(MODEL_NOTE)
    _scope_note()

    twin = state.get_twin()
    if twin is None:
        empty_state(
            "No digital twin with a topology is loaded.",
            title="No design loaded",
            hint="Load or edit a twin on the Topology or Digital Twin page first.",
        )
        return

    l2_tab, wan_tab, wireless_tab, qos_tab, findings_tab = st.tabs(
        [
            i18n.t("l2.tab.l2"),
            i18n.t("l2.tab.wan"),
            i18n.t("l2.tab.wireless"),
            i18n.t("l2.tab.qos"),
            i18n.t("l2.tab.findings"),
        ]
    )
    with l2_tab:
        render_l2_tab(twin)
    with wan_tab:
        render_wan_tab(twin)
    with wireless_tab:
        render_wireless_tab(twin)
    with qos_tab:
        render_qos_tab(twin)
    with findings_tab:
        _render_review(twin)
        section_header("Design health")
        st.caption(
            "The shared health panel includes the W1-W4 design checks when "
            "their models are stored on the twin."
        )
        render_design_health(twin)


__all__ = [
    "MODEL_NOTE",
    "PAGE_TITLE",
    "REVIEW_CANCEL_KEY",
    "REVIEW_CURSOR_KEY",
    "REVIEW_PIECES_KEY",
    "REVIEW_RESULT_KEY",
    "render",
    "render_l2_tab",
    "render_qos_tab",
    "render_wan_tab",
    "render_wireless_tab",
]
