"""Interchange export tests for digital-twin topology data.

Every export is built in memory. The hostile-name fixture deliberately mixes
XML/Mermaid delimiters, spreadsheet formula prefixes, control characters, RTL
text, and a very long identifier.
"""

from __future__ import annotations

import csv
import io
import re
from xml.etree import ElementTree as ET

import pytest

from core.exceptions import ReportLimitError
from core.schemas.network import Topology
from digital_twin import DigitalTwin
from services.export.drawio import to_drawio
from services.export.graphml import GRAPHML_NAMESPACE, to_graphml
from services.export.inventory import INVENTORY_COLUMNS, to_inventory_csv
from services.export.mermaid import to_mermaid
from tests.unit.digital_twin.helpers import make_twin

_HOSTILE = '=<>&"\' +@\n\t\u202e\u0627\u0644\u0634\u0628\u0643\u0629\u202c' + "A" * 2000
_HOSTILE_LINK = f"@{_HOSTILE}"
_NS = f"{{{GRAPHML_NAMESPACE}}}"
_EXPORTS = (to_graphml, to_mermaid, to_inventory_csv, to_drawio)


def _hostile_twin() -> DigitalTwin:
    """Build a valid twin with adversarial device and link identifiers."""
    twin = make_twin()
    topology = twin.topology.model_copy(deep=True)
    original_id = next(iter(topology.devices)).id
    next(iter(topology.devices)).id = _HOSTILE
    for link in topology.links:
        link.endpoints = tuple(
            _HOSTILE if endpoint == original_id else endpoint
            for endpoint in link.endpoints
        )
    next(iter(topology.links)).id = _HOSTILE_LINK
    return make_twin(topology=Topology.model_validate(topology.model_dump()))


def _empty_twin() -> DigitalTwin:
    return make_twin(
        topology=Topology(name="Empty", devices=[], links=[]),
        addressing=None,
        vlan_plan=None,
        dhcp_scopes=(),
    )


@pytest.mark.parametrize("export", _EXPORTS)
def test_exports_are_byte_identical_for_the_same_twin(export) -> None:
    first = export(make_twin())
    second = export(make_twin())
    third = export(make_twin())
    assert first == second == third
    assert isinstance(first, (bytes, str))


@pytest.mark.parametrize("export", _EXPORTS)
def test_hostile_twin_exports_are_also_deterministic(export) -> None:
    assert export(_hostile_twin()) == export(_hostile_twin())


def test_hostile_names_escape_into_parseable_xml() -> None:
    hostile = _hostile_twin()
    graphml = to_graphml(hostile)
    drawio = to_drawio(hostile)

    assert graphml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert drawio.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')

    graph_root = ET.fromstring(graphml)
    draw_root = ET.fromstring(drawio)
    nodes = list(graph_root.iter(f"{_NS}node"))
    edges = list(graph_root.iter(f"{_NS}edge"))
    assert any(node.get("id") == _HOSTILE for node in nodes)
    assert any(edge.get("id") == _HOSTILE_LINK for edge in edges)

    cells = list(draw_root.iter("mxCell"))
    assert any(cell.get("value") and _HOSTILE in cell.get("value") for cell in cells)
    assert any(
        cell.get("value") and _HOSTILE_LINK in cell.get("value") for cell in cells
    )


def test_mermaid_labels_cannot_break_the_diagram_syntax() -> None:
    lines = to_mermaid(_hostile_twin()).splitlines()

    assert lines[0].startswith("%%") and "design intent" in lines[0]
    assert lines[1] == "flowchart LR"
    # Two headers, three device nodes, two link edges: the hostile newline
    # must not have split a label into additional lines.
    assert len(lines) == 7

    labels = re.findall(r'\["([^"\]]*)"\]', "\n".join(lines))
    assert len(labels) == 3
    unsafe = set('"`[](){}<>|\n\r\t')
    for label in labels:
        assert not unsafe.intersection(label)


def test_inventory_csv_neutralizes_formula_cells_and_tags_sections() -> None:
    payload = to_inventory_csv(_hostile_twin())
    assert b"\r\n" in payload

    rows = list(csv.reader(io.StringIO(payload.decode("utf-8"), newline="")))
    assert tuple(rows[0]) == INVENTORY_COLUMNS
    assert all(row for row in rows[1:])
    assert {row[0] for row in rows[1:]} == {
        "devices",
        "links",
        "subnets",
        "vlans",
        "dhcp",
    }

    cells = [cell for row in rows for cell in row]
    assert any(cell.startswith("'") and _HOSTILE in cell for cell in cells)
    assert any(cell.startswith("'") and _HOSTILE_LINK in cell for cell in cells)


def test_empty_topology_exports_are_valid_and_minimal() -> None:
    empty = _empty_twin()

    graph_root = ET.fromstring(to_graphml(empty))
    assert not list(graph_root.iter(f"{_NS}node"))
    assert not list(graph_root.iter(f"{_NS}edge"))

    mermaid_lines = to_mermaid(empty).splitlines()
    assert mermaid_lines[0].startswith("%%")
    assert mermaid_lines[1:] == ["flowchart LR"]

    rows = list(csv.reader(io.StringIO(to_inventory_csv(empty).decode("utf-8"))))
    assert tuple(rows[0]) == INVENTORY_COLUMNS
    assert len(rows) == 6

    draw_cells = list(ET.fromstring(to_drawio(empty)).iter("mxCell"))
    assert {cell.get("id") for cell in draw_cells} == {"0", "1"}


def test_inventory_enforces_its_own_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("services.export.inventory.MAX_REPORT_BYTES", 10)
    with pytest.raises(ReportLimitError):
        to_inventory_csv(make_twin())


def test_xml_exports_enforce_the_shared_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("services.export.common.MAX_REPORT_BYTES", 10)
    with pytest.raises(ReportLimitError):
        to_graphml(make_twin())
    with pytest.raises(ReportLimitError):
        to_drawio(make_twin())
