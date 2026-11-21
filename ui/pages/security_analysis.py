"""Security Analysis page with Zones, Policy, Flow check, Findings, and Templates.

The page is a presentation layer over the deterministic, offline security
engine. It reads the current digital twin, lets the user edit a bounded modeled
security design, and renders only modeled design-time results. It never scans,
probes, contacts a device, looks up a vulnerability, or changes live equipment.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.exceptions import NetArchitectError
from security import (
    RULE_CATALOG,
    SECURITY_DISCLAIMER,
    FirewallRule,
    FlowRequest,
    PolicyAction,
    Protocol,
    SecurityModel,
    Service,
    Zone,
    ZoneType,
    accept_proposed_rules,
    get_security_model,
    set_security_model,
)
from services.copilot import finding_request
from simulation import twin_fingerprint
from ui import state
from ui.cache import cached_security_analysis, security_flows_payload, twin_payload
from ui.components import (
    empty_state,
    format_error,
    model_estimate_note,
    page_header,
    render_findings,
)
from ui.components.copilot import why_button
from ui.components.editors import bump_editor_key, editor_key
from ui.components.notices import queue_notice, render_notices

MODEL_NOTE = SECURITY_DISCLAIMER

ZONE_EDITOR_BASE = "security_zone_editor"
SERVICE_EDITOR_BASE = "security_service_editor"
RULE_EDITOR_BASE = "security_rule_editor"
ZONE_APPLY_KEY = "security_apply_zones"
POLICY_APPLY_KEY = "security_apply_policy"
ASSUMPTIONS_KEY = "security_assumptions"
DEFAULT_ACTION_KEY = "security_default_action"

FLOW_ID_KEY = "security_flow_id"
FLOW_SOURCE_KEY = "security_flow_source"
FLOW_DESTINATION_KEY = "security_flow_destination"
FLOW_PROTOCOL_KEY = "security_flow_protocol"
FLOW_PORT_KEY = "security_flow_port"
FLOW_ADD_KEY = "security_add_flow"
FLOW_REMOVE_KEY = "security_flow_remove_index"
FLOW_REMOVE_BUTTON_KEY = "security_remove_flow"
FLOW_CLEAR_BUTTON_KEY = "security_clear_flows"

COPILOT_WHY_FINDING_KEY = "copilot_why_finding_select"
PROPOSAL_SELECT_KEY = "security_selected_proposals"
APPLY_PROPOSALS_KEY = "security_apply_proposals"
TEMPLATE_DOWNLOAD_KEY = "security_template_download"
ANALYSIS_DOWNLOAD_KEY = "security_analysis_download"

ZONE_COLUMNS = (
    "id",
    "name",
    "type",
    "criticality",
    "member_vlan_ids",
    "member_device_ids",
    "expected_hosts",
)
SERVICE_COLUMNS = ("name", "protocol", "port_start", "port_end")
RULE_COLUMNS = (
    "id",
    "order",
    "src_zone",
    "dst_zone",
    "services",
    "any_service",
    "action",
    "enabled",
    "note",
)
FLOW_COLUMNS = (
    "id",
    "source_device_id",
    "destination_device_id",
    "protocol",
    "port",
)
ANY_TOKENS = frozenset({"any", "*"})
TRUE_TOKENS = frozenset({"true", "1", "yes"})
FALSE_TOKENS = frozenset({"false", "0", "no", ""})


def _blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return pd.isna(value)
    if isinstance(value, str):
        return not value.strip()
    return False


def _text(value: object) -> str:
    if _blank(value):
        return ""
    return str(value).strip()


def _integer(value: object, label: str) -> int:
    text = _text(value)
    if not text:
        raise ValueError(f"{label} is required.")
    try:
        number = float(text)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a whole number.") from error
    if number != int(number):
        raise ValueError(f"{label} must be a whole number.")
    return int(number)


def _optional_integer(value: object, label: str) -> int | None:
    if _blank(value):
        return None
    return _integer(value, label)


def _bool(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in TRUE_TOKENS:
        return True
    if text in FALSE_TOKENS:
        return False
    raise ValueError(f"{label} must be true or false.")


def _tokens(value: object, label: str) -> tuple[str, ...]:
    text = _text(value)
    if not text:
        return ()
    result = tuple(part.strip() for part in text.split(",") if part.strip())
    if not result:
        raise ValueError(f"{label} must contain at least one value.")
    return result


def _vlan_ids(value: object) -> tuple[int, ...]:
    return tuple(_integer(token, "VLAN id") for token in _tokens(value, "VLAN ids"))


def _immutable_id_edited(
    base: str,
    column: str,
    original_ids: tuple[str, ...] | list[str],
) -> bool:
    editor_state = state.session_get(editor_key(base))
    if not isinstance(editor_state, Mapping):
        return False
    changes = editor_state.get("edited_rows", {})
    if not isinstance(changes, Mapping):
        return False
    for row, delta in changes.items():
        if not isinstance(delta, Mapping) or column not in delta:
            continue
        try:
            index = int(row)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(original_ids) and delta[column] != original_ids[index]:
            return True
    return False


def _zone_rows(model: SecurityModel) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": zone.id,
                "name": zone.name,
                "type": zone.type.value,
                "criticality": zone.criticality,
                "member_vlan_ids": ",".join(str(item) for item in zone.member_vlan_ids),
                "member_device_ids": ",".join(zone.member_device_ids),
                "expected_hosts": zone.expected_hosts
                if zone.expected_hosts is not None
                else "",
            }
            for zone in model.zones
        ],
        columns=list(ZONE_COLUMNS),
    )


def _service_rows(model: SecurityModel) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": service.name,
                "protocol": service.protocol.value,
                "port_start": service.port_start,
                "port_end": service.port_end,
            }
            for service in model.services
        ],
        columns=list(SERVICE_COLUMNS),
    )


def _rule_rows(model: SecurityModel) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": rule.id,
                "order": rule.order,
                "src_zone": rule.src_zone,
                "dst_zone": rule.dst_zone,
                "services": "any" if rule.any_service else ",".join(rule.services),
                "any_service": rule.any_service,
                "action": rule.action.value,
                "enabled": rule.enabled,
                "note": rule.note,
            }
            for rule in model.rules
        ],
        columns=list(RULE_COLUMNS),
    )


def _zones_from_frame(edited: pd.DataFrame) -> tuple[Zone, ...]:
    zones: list[Zone] = []
    for _, row in edited.iterrows():
        zones.append(
            Zone(
                id=_text(row["id"]),
                name=_text(row["name"]),
                type=ZoneType(_text(row["type"])),
                criticality=_integer(row["criticality"], "Criticality"),
                member_vlan_ids=_vlan_ids(row["member_vlan_ids"]),
                member_device_ids=_tokens(row["member_device_ids"], "Member devices"),
                expected_hosts=_optional_integer(row["expected_hosts"], "Expected hosts"),
            )
        )
    return tuple(zones)


def _services_from_frame(edited: pd.DataFrame) -> tuple[Service, ...]:
    services: list[Service] = []
    for _, row in edited.iterrows():
        services.append(
            Service(
                name=_text(row["name"]),
                protocol=Protocol(_text(row["protocol"])),
                port_start=_integer(row["port_start"], "Port start"),
                port_end=_integer(row["port_end"], "Port end"),
            )
        )
    return tuple(services)


def _rules_from_frame(edited: pd.DataFrame) -> tuple[FirewallRule, ...]:
    rules: list[FirewallRule] = []
    for _, row in edited.iterrows():
        service_text = _text(row["services"])
        any_from_text = service_text.lower() in ANY_TOKENS
        services = () if any_from_text else _tokens(service_text, "Services")
        any_service = _bool(row["any_service"], "Any service") or any_from_text
        rules.append(
            FirewallRule(
                id=_text(row["id"]),
                order=_integer(row["order"], "Rule order"),
                src_zone=_text(row["src_zone"]),
                dst_zone=_text(row["dst_zone"]),
                services=services,
                any_service=any_service,
                action=PolicyAction(_text(row["action"])),
                enabled=_bool(row["enabled"], "Enabled"),
                note=_text(row["note"]),
            )
        )
    return tuple(rules)


def _assumptions_from_text(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def _validate_references(model: SecurityModel) -> None:
    zone_ids = {zone.id for zone in model.zones}
    service_names = {service.name for service in model.services}
    for rule in model.rules:
        for label, zone_id in (("source", rule.src_zone), ("destination", rule.dst_zone)):
            if zone_id not in zone_ids:
                raise ValueError(
                    f"Rule {rule.id!r} names unknown {label} zone {zone_id!r}."
                )
        missing = [name for name in rule.services if name not in service_names]
        if missing:
            raise ValueError(
                f"Rule {rule.id!r} names unknown service(s): {', '.join(missing)}."
            )


def _apply_zone_edits(twin, edited: pd.DataFrame, assumptions_text: str) -> int:
    current = get_security_model(twin)
    original_ids = tuple(zone.id for zone in current.zones)
    if _immutable_id_edited(ZONE_EDITOR_BASE, "id", original_ids):
        raise ValueError("Zone ids are immutable. Delete the row and add a new zone.")
    candidate = current.model_copy(
        update={
            "zones": _zones_from_frame(edited),
            "assumptions": _assumptions_from_text(assumptions_text),
        }
    )
    state.replace_twin(set_security_model(twin, candidate))
    return len(candidate.zones)


def _apply_policy_edits(
    twin,
    edited_services: pd.DataFrame,
    edited_rules: pd.DataFrame,
    default_action: PolicyAction,
) -> tuple[int, int]:
    current = get_security_model(twin)
    service_ids = tuple(service.name for service in current.services)
    rule_ids = tuple(rule.id for rule in current.rules)
    if _immutable_id_edited(SERVICE_EDITOR_BASE, "name", service_ids):
        raise ValueError(
            "Service names are immutable. Delete the row and add a new service."
        )
    if _immutable_id_edited(RULE_EDITOR_BASE, "id", rule_ids):
        raise ValueError("Rule ids are immutable. Delete the row and add a new rule.")
    candidate = current.model_copy(
        update={
            "services": _services_from_frame(edited_services),
            "rules": _rules_from_frame(edited_rules),
            "default_action": default_action,
        }
    )
    _validate_references(candidate)
    state.replace_twin(set_security_model(twin, candidate))
    return len(candidate.services), len(candidate.rules)


def _analysis(twin, model: SecurityModel):
    return cached_security_analysis(
        twin_payload(twin),
        model.model_dump_json(),
        security_flows_payload(state.peek_security_flows()),
    )


def _render_zones_tab(twin, model: SecurityModel) -> None:
    st.subheader("Modeled zones")
    source = "stored security model" if twin.security is not None else "derived default"
    st.caption(
        f"Source: {source}. Zone criticality is a user-set 1-5 modeling "
        "assumption, not a measurement or a CVSS score."
    )
    st.caption(
        "List VLAN ids and device ids as comma-separated values. Every zone "
        "needs at least one member. Zone ids are immutable."
    )

    with st.form("security_zones_form"):
        edited = st.data_editor(
            _zone_rows(model),
            key=editor_key(ZONE_EDITOR_BASE),
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "id": st.column_config.TextColumn("Zone id", required=True),
                "name": st.column_config.TextColumn("Name", required=True),
                "type": st.column_config.SelectboxColumn(
                    "Type",
                    options=[item.value for item in ZoneType],
                    required=True,
                ),
                "criticality": st.column_config.NumberColumn(
                    "Criticality", min_value=1, max_value=5, step=1
                ),
                "member_vlan_ids": st.column_config.TextColumn("VLAN ids"),
                "member_device_ids": st.column_config.TextColumn("Device ids"),
                "expected_hosts": st.column_config.NumberColumn(
                    "Expected hosts", min_value=0, step=1
                ),
            },
        )
        assumptions = st.text_area(
            "Modeling assumptions (one per line)",
            value="\n".join(model.assumptions),
            key=ASSUMPTIONS_KEY,
            height=120,
        )
        applied = st.form_submit_button(
            "Apply zone changes", key=ZONE_APPLY_KEY, type="primary"
        )

    if not applied:
        return
    try:
        count = _apply_zone_edits(twin, edited, assumptions)
    except (NetArchitectError, ValidationError, ValueError) as error:
        bump_editor_key(ZONE_EDITOR_BASE)
        queue_notice("error", f"Zone edits rejected: {format_error(error)}")
        st.rerun()
    else:
        st.success(f"Stored {count} modeled zone(s).")
        st.rerun()


def _render_policy_tab(twin, model: SecurityModel) -> None:
    st.subheader("Modeled policy")
    st.caption(
        "Rules are evaluated in ascending order with first-match semantics. "
        "Disabled rules are skipped, and the explicit default applies when no "
        "rule matches. Use 'any' in the services column for any service."
    )
    default_index = 0 if model.default_action is PolicyAction.deny else 1
    default_action = st.selectbox(
        "Default action",
        [item.value for item in PolicyAction],
        index=default_index,
        key=DEFAULT_ACTION_KEY,
    )

    with st.form("security_policy_form"):
        st.markdown("**Named services**")
        edited_services = st.data_editor(
            _service_rows(model),
            key=editor_key(SERVICE_EDITOR_BASE),
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "name": st.column_config.TextColumn("Name", required=True),
                "protocol": st.column_config.SelectboxColumn(
                    "Protocol",
                    options=[item.value for item in Protocol],
                    required=True,
                ),
                "port_start": st.column_config.NumberColumn(
                    "Port start", min_value=0, max_value=65_535, step=1
                ),
                "port_end": st.column_config.NumberColumn(
                    "Port end", min_value=0, max_value=65_535, step=1
                ),
            },
        )
        st.markdown("**Ordered firewall rules**")
        edited_rules = st.data_editor(
            _rule_rows(model),
            key=editor_key(RULE_EDITOR_BASE),
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "id": st.column_config.TextColumn("Rule id", required=True),
                "order": st.column_config.NumberColumn(
                    "Order", min_value=0, step=1
                ),
                "src_zone": st.column_config.TextColumn("Source zone", required=True),
                "dst_zone": st.column_config.TextColumn(
                    "Destination zone", required=True
                ),
                "services": st.column_config.TextColumn("Services or any"),
                "any_service": st.column_config.CheckboxColumn("Any service"),
                "action": st.column_config.SelectboxColumn(
                    "Action",
                    options=[item.value for item in PolicyAction],
                    required=True,
                ),
                "enabled": st.column_config.CheckboxColumn("Enabled"),
                "note": st.column_config.TextColumn("Note"),
            },
        )
        applied = st.form_submit_button(
            "Apply policy changes", key=POLICY_APPLY_KEY, type="primary"
        )

    if not applied:
        return
    try:
        service_count, rule_count = _apply_policy_edits(
            twin,
            edited_services,
            edited_rules,
            PolicyAction(default_action),
        )
    except (NetArchitectError, ValidationError, ValueError) as error:
        bump_editor_key(SERVICE_EDITOR_BASE)
        bump_editor_key(RULE_EDITOR_BASE)
        queue_notice("error", f"Policy edits rejected: {format_error(error)}")
        st.rerun()
    else:
        st.success(
            f"Stored {service_count} service(s) and {rule_count} rule(s)."
        )
        st.rerun()


def _render_flow_tab(twin, analysis) -> None:
    st.subheader("Flow checks")
    device_ids = tuple(device.id for device in twin.topology.devices)
    if not device_ids:
        empty_state("The modeled topology has no devices to check.")
        return
    st.caption(
        "A flow check combines the modeled route with first-match policy. It "
        "does not send traffic. ICMP and any-protocol checks always use port 0."
    )

    with st.form("security_flow_form"):
        columns = st.columns(4)
        with columns[0]:
            flow_id = st.text_input("Check id", key=FLOW_ID_KEY)
        with columns[1]:
            source = st.selectbox("Source device", device_ids, key=FLOW_SOURCE_KEY)
        with columns[2]:
            destination = st.selectbox(
                "Destination device", device_ids, key=FLOW_DESTINATION_KEY
            )
        with columns[3]:
            protocol = st.selectbox(
                "Protocol",
                [item.value for item in Protocol],
                key=FLOW_PROTOCOL_KEY,
            )
        port = st.number_input(
            "Port (ignored for ICMP and any)",
            min_value=0,
            max_value=65_535,
            value=80,
            key=FLOW_PORT_KEY,
        )
        added = st.form_submit_button(
            "Add flow check", key=FLOW_ADD_KEY, type="primary"
        )

    if added:
        modeled_port = 0 if protocol in {"icmp", "any"} else int(port)
        try:
            request = FlowRequest(
                id=_text(flow_id),
                source_device_id=source,
                destination_device_id=destination,
                protocol=Protocol(protocol),
                port=modeled_port,
            )
            state.add_security_flow(request)
        except (ValidationError, ValueError, TypeError) as error:
            st.error(f"Flow check rejected: {format_error(error)}")
        else:
            st.success(f"Added flow check {request.id!r}.")
            st.rerun()

    flows = state.peek_security_flows()
    st.subheader("Current flow checks")
    if not flows:
        empty_state("No flow checks have been added in this session.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "id": item.id,
                        "source_device_id": item.source_device_id,
                        "destination_device_id": item.destination_device_id,
                        "protocol": item.protocol.value,
                        "port": item.port,
                    }
                    for item in flows
                ],
                columns=list(FLOW_COLUMNS),
            ),
            hide_index=True,
            width="stretch",
        )
        selected = st.selectbox(
            "Flow check to remove",
            options=range(len(flows)),
            format_func=lambda index: flows[index].id,
            key=FLOW_REMOVE_KEY,
        )
        action_columns = st.columns(2)
        if action_columns[0].button(
            "Remove selected flow", key=FLOW_REMOVE_BUTTON_KEY
        ):
            try:
                removed = state.remove_security_flow(int(selected))
            except (IndexError, ValueError, TypeError) as error:
                st.error(format_error(error))
            else:
                st.success(f"Removed flow check {removed.id!r}.")
                st.rerun()
        if action_columns[1].button("Clear all flows", key=FLOW_CLEAR_BUTTON_KEY):
            state.clear_security_flows()
            st.success("Cleared every flow check.")
            st.rerun()

    st.subheader("Modeled results")
    if not analysis.flow_checks:
        empty_state("Add a flow check to see its modeled route and policy outcome.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "id": check.request.id,
                    "source_zone": check.source_zone or "(unassigned)",
                    "destination_zone": check.destination_zone or "(unassigned)",
                    "verdict": check.verdict.value,
                    "route_reachable": check.route_reachable,
                    "policy_permitted": check.policy_permitted,
                    "device_path": " -> ".join(check.device_path),
                    "reason": check.reason,
                }
                for check in analysis.flow_checks
            ],
            columns=[
                "id",
                "source_zone",
                "destination_zone",
                "verdict",
                "route_reachable",
                "policy_permitted",
                "device_path",
                "reason",
            ],
        ),
        hide_index=True,
        width="stretch",
    )


def _render_findings_tab(twin, analysis) -> None:
    st.subheader("Modeled risk")
    metrics = st.columns(4)
    metrics[0].metric("Risk score", str(analysis.risk.score))
    metrics[1].metric("Risk level", analysis.risk.level.value)
    metrics[2].metric("Posture", analysis.summary.posture.value)
    metrics[3].metric("Findings", str(len(analysis.findings)))
    st.caption(analysis.risk.formula)
    st.caption(SECURITY_DISCLAIMER)
    if analysis.risk.terms:
        st.dataframe(
            pd.DataFrame(
                [
                    {"term": term.label, "value": term.value, "basis": term.basis}
                    for term in analysis.risk.terms
                ],
                columns=["term", "value", "basis"],
            ),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Design and policy findings")
    render_findings(
        tuple(item.to_validation_finding() for item in analysis.findings),
        "No design-weakness or policy finding was produced for this model.",
    )

    if analysis.findings:
        st.subheader("Explain a finding")
        st.caption(
            "The deterministic explanation uses the full finding, its evidence, "
            "and its computed remediation. Optional AI prose is audited and never "
            "states a severity or verdict."
        )
        # Codes can repeat, so include a stable index in the visible label. Keep
        # the full SecurityFinding (not the reduced Finding) for the builder.
        choices = [
            (f"{item.code} ({index + 1})", item)
            for index, item in enumerate(analysis.findings)
        ]
        selected = st.selectbox(
            "Finding to explain",
            [label for label, _ in choices],
            key=COPILOT_WHY_FINDING_KEY,
        )
        finding = next(item for label, item in choices if label == selected)
        why_button("copilot_why_finding", lambda: finding_request(finding))

    st.subheader("Fixed catalog")
    st.caption(
        "The catalog is a modeling aid, not an audit standard. Its ids and base "
        "severities are fixed in code and cannot be changed by UI state."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "id": rule.id,
                    "title": rule.title,
                    "trigger": rule.trigger,
                    "base_severity": rule.base_severity.value,
                    "remediation": rule.remediation,
                }
                for rule in RULE_CATALOG
            ],
            columns=["id", "title", "trigger", "base_severity", "remediation"],
        ),
        hide_index=True,
        width="stretch",
    )

    st.subheader("Proposed rules")
    st.caption(
        "Proposals are inert modeling output. Only rules selected here are "
        "added to a new twin, and no device configuration is produced."
    )
    if not analysis.proposals.rules:
        st.info("No proposed rules were produced for the current findings.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "id": proposal.id,
                    "source_zone": proposal.src_zone,
                    "destination_zone": proposal.dst_zone,
                    "action": proposal.action.value,
                    "based_on_finding": proposal.based_on_finding,
                    "reason": proposal.reason,
                }
                for proposal in analysis.proposals.rules
            ],
            columns=[
                "id",
                "source_zone",
                "destination_zone",
                "action",
                "based_on_finding",
                "reason",
            ],
        ),
        hide_index=True,
        width="stretch",
    )
    selected = st.multiselect(
        "Proposals to apply",
        [rule.id for rule in analysis.proposals.rules],
        key=PROPOSAL_SELECT_KEY,
    )
    if not st.button("Apply selected proposals", key=APPLY_PROPOSALS_KEY):
        return
    if not selected:
        st.warning("Select at least one proposal before applying changes.")
        return
    try:
        updated, applied = accept_proposed_rules(
            twin, analysis.proposals, tuple(selected)
        )
    except (NetArchitectError, ValidationError, ValueError) as error:
        st.error(f"Proposals not applied: {format_error(error)}")
        return
    source_fingerprint = twin_fingerprint(twin)
    state.replace_twin(updated)
    state.record_decision(
        kind="security_proposal_accepted",
        subject_id=", ".join(applied)[:200],
        title=f"Accepted {len(applied)} modeled security proposal(s)",
        page="Security Analysis",
        source_fingerprint=source_fingerprint,
        result_fingerprint=twin_fingerprint(updated),
    )
    st.success(f"Applied {len(applied)} proposed rule(s) to a new twin.")
    st.rerun()


def _render_templates_tab(analysis) -> None:
    st.subheader("Vendor-neutral templates")
    st.caption(
        "Templates are key/value intent records. They contain no vendor syntax, "
        "no device commands, and no instruction to apply a configuration."
    )
    st.code(analysis.template.text(), language="text")
    st.download_button(
        "Download modeled policy intent",
        data=analysis.template.text().encode("utf-8"),
        file_name="security-policy-intent.txt",
        mime="text/plain",
        key=TEMPLATE_DOWNLOAD_KEY,
    )
    st.download_button(
        "Download full assessment as JSON",
        data=(analysis.model_dump_json(indent=2) + "\n").encode("utf-8"),
        file_name="security-analysis.json",
        mime="application/json",
        key=ANALYSIS_DOWNLOAD_KEY,
    )
    st.caption(SECURITY_DISCLAIMER)


def render() -> None:
    """Render the five-tab design-time Security Analysis workflow."""
    page_header(
        "Security Analysis",
        "Model trust zones, policy, and flow checks against the current digital "
        "twin. This page does not scan, probe, contact a device, or look up a "
        "vulnerability.",
    )
    render_notices()
    model_estimate_note(MODEL_NOTE, title="Model scope")

    twin = state.get_twin()
    if twin is None or not twin.topology.devices:
        empty_state(
            "No digital twin with a topology is loaded. Open the Topology "
            "Editor to create, generate, or import one, then return here.",
            title="Digital twin required",
            hint="Security results are modeled only from a stored twin revision.",
        )
        return

    model = get_security_model(twin)
    analysis = _analysis(twin, model)
    zones_tab, policy_tab, flow_tab, findings_tab, templates_tab = st.tabs(
        ["Zones", "Policy", "Flow check", "Findings", "Templates"]
    )
    with zones_tab:
        _render_zones_tab(twin, model)
    with policy_tab:
        _render_policy_tab(twin, model)
    with flow_tab:
        _render_flow_tab(twin, analysis)
    with findings_tab:
        _render_findings_tab(twin, analysis)
    with templates_tab:
        _render_templates_tab(analysis)
