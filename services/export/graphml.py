"""Deterministic GraphML export for a digital twin.

GraphML is a modeling interchange format: the result describes the twin's
design intent, not device-applied configuration or live equipment state.
ElementTree performs all escaping, so hostile identifiers cannot inject XML.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from config.limits import MAX_EDGES, MAX_NODES
from digital_twin import DigitalTwin

from .common import enforce_size

GRAPHML_NAMESPACE = "http://graphml.graphdrawing.org/xmlns"
_XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>'

# (key id, attribute name, attribute type, element)
_KEY_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("d_id", "id", "string", "node"),
    ("d_name", "name", "string", "node"),
    ("d_type", "type", "string", "node"),
    ("d_site", "site", "string", "node"),
    ("d_role", "role", "string", "node"),
    ("e_id", "id", "string", "edge"),
    ("e_name", "name", "string", "edge"),
    ("e_capacity_mbps", "capacity_mbps", "double", "edge"),
    ("e_cost", "cost", "double", "edge"),
    ("e_directed", "directed", "boolean", "edge"),
    ("e_endpoints", "endpoints", "string", "edge"),
)


def _q(tag: str) -> str:
    return f"{{{GRAPHML_NAMESPACE}}}{tag}"


def _number(value: float) -> str:
    return str(value)


def _serialize(root: ET.Element) -> bytes:
    """Serialize with the fixed declaration used by every interchange file."""
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    _head, marker, body = payload.partition(b"?>")
    if not marker:
        return payload
    return _XML_DECLARATION + body


def _add_data(parent: ET.Element, key: str, value: str) -> None:
    data = ET.SubElement(parent, _q("data"), {"key": key})
    data.text = value


def to_graphml(twin: DigitalTwin) -> bytes:
    """Return deterministic GraphML bytes for ``twin``'s modeled topology."""
    devices = sorted(twin.topology.devices, key=lambda item: item.id)[:MAX_NODES]
    included = {device.id for device in devices}
    links = [
        link
        for link in sorted(twin.topology.links, key=lambda item: item.id)[:MAX_EDGES]
        if all(endpoint in included for endpoint in link.endpoints)
    ]

    root = ET.Element(_q("graphml"))
    for key_id, attr_name, attr_type, for_element in _KEY_SPECS:
        ET.SubElement(
            root,
            _q("key"),
            {
                "id": key_id,
                "for": for_element,
                "attr.name": attr_name,
                "attr.type": attr_type,
            },
        )

    graph = ET.SubElement(
        root,
        _q("graph"),
        {"id": twin.topology.name, "edgedefault": "undirected"},
    )

    for device in devices:
        node = ET.SubElement(graph, _q("node"), {"id": device.id})
        # Device ids dual as display names: the domain model has no name field.
        _add_data(node, "d_id", device.id)
        _add_data(node, "d_name", device.id)
        _add_data(node, "d_type", device.type.value)
        _add_data(node, "d_site", device.site)
        _add_data(node, "d_role", device.role.value)

    for link in links:
        first, second = link.endpoints
        edge = ET.SubElement(
            graph,
            _q("edge"),
            {
                "id": link.id,
                "source": first,
                "target": second,
                "directed": "true" if link.directed else "false",
            },
        )
        _add_data(edge, "e_id", link.id)
        _add_data(edge, "e_name", link.id)
        _add_data(edge, "e_capacity_mbps", _number(link.capacity_mbps))
        _add_data(edge, "e_cost", _number(link.cost))
        _add_data(edge, "e_directed", "true" if link.directed else "false")
        _add_data(edge, "e_endpoints", f"{first}|{second}")

    return enforce_size(_serialize(root), kind="GraphML")


__all__ = ["GRAPHML_NAMESPACE", "to_graphml"]
