"""Single-point-of-failure entries and machine-readable findings."""

from __future__ import annotations

from core.schemas.validation import Severity
from network.analysis import analyze_topology, spof_findings, spof_report


def test_line_spof_report_lists_devices_then_links(line_graph) -> None:
    report = spof_report(line_graph)

    assert report.baseline_component_count == 1
    assert [(entry.kind, entry.entity_id) for entry in report.entries] == [
        ("device", "b"),
        ("device", "c"),
        ("link", "ab"),
        ("link", "bc"),
        ("link", "cd"),
    ]
    link_entry = report.entries[2]
    assert link_entry.endpoints == ["a", "b"]
    assert link_entry.components_after_removal == 2
    assert link_entry.isolated_device_ids == ["a"]


def test_line_findings_are_critical_with_stable_codes(line_graph) -> None:
    findings = spof_findings(spof_report(line_graph))

    assert [finding.code for finding in findings] == [
        "spof_device",
        "spof_device",
        "spof_link",
        "spof_link",
        "spof_link",
    ]
    assert all(finding.severity == Severity.critical for finding in findings)
    assert all(finding.remediation for finding in findings)
    assert "from 1 to 2" in findings[0].explanation
    assert findings[0].affected_entities == ["b", "a"]
    assert findings[2].affected_entities == ["ab", "a", "b"]


def test_ring_has_no_spof_entries_or_findings(ring_graph) -> None:
    report = spof_report(ring_graph)

    assert report.baseline_component_count == 1
    assert report.entries == []
    assert spof_findings(report) == []


def test_star_hub_and_every_spoke_link_are_spofs(star_graph) -> None:
    report = spof_report(star_graph)

    kinds = [(entry.kind, entry.entity_id) for entry in report.entries]

    assert ("device", "h") in kinds
    assert [entry for entry in kinds if entry[0] == "link"] == [
        ("link", "hs1"),
        ("link", "hs2"),
        ("link", "hs3"),
    ]
    assert all(entry[0] != "device" or entry[1] == "h" for entry in kinds)


def test_parallel_link_pair_is_not_a_single_link_spof() -> None:
    from .helpers import build_topology, make_link

    topology = build_topology(
        "Parallel pair",
        ["a", "b", "c"],
        [
            make_link("ab-1", "a", "b"),
            make_link("ab-2", "a", "b"),
            make_link("bc", "b", "c"),
        ],
    )

    report = spof_report(topology)

    assert [entry.entity_id for entry in report.entries] == ["b", "bc"]


def test_analysis_findings_add_connectivity_warnings(disconnected_graph) -> None:
    report = analyze_topology(disconnected_graph)
    codes = [finding.code for finding in report.findings]

    assert codes.count("spof_link") == 2
    assert "topology_disconnected" in codes
    assert "isolated_device" in codes
    disconnected = next(
        finding
        for finding in report.findings
        if finding.code == "topology_disconnected"
    )
    assert disconnected.severity == Severity.warning
    isolated = next(
        finding for finding in report.findings if finding.code == "isolated_device"
    )
    assert isolated.affected_entities == ["e"]
