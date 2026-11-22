"""Deterministic draw.io (mxGraph) export for a digital twin.

The XML describes modeled design intent with a fixed left-to-right role layout.
ElementTree handles escaping and all identifiers are mapped to safe cell ids,
so hostile names cannot corrupt the document or its source/target references.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from config.limits import MAX_EDGES, MAX_NODES
from core.schemas.network import Device
from digital_twin import DigitalTwin

from .common import enforce_size

_XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>'
_TIER_WIDTH = 240
_NODE_HEIGHT = 120
_NODE_WIDTH = 160
_NODE_BOX_HEIGHT = 60

# Mirrors the stable role tiers used by the topology view, without importing
# the UI layer (and therefore without importing Streamlit into an exporter).
_TIER_ROLES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (0, ("wan", "border")),
    (1, ("dmz", "core")),
    (2, ("distribution", "aggregation")),
    (3, ("access", "edge")),
)
_ENDPOINT_TYPES = frozenset({"server", "host"})
_NON_ID_CHAR = re.compile(r"[^A-Za-z0-9_]")


def _number(value: float) -> str:
    return str(value)


def _device_tier(device: Device) -> int:
    role = device.role.value
    tier = next(
        (tier for tier, roles in _TIER_ROLES if role in roles),
        2,
    )
    if tier >= 3 and device.type.value in _ENDPOINT_TYPES:
        return 4
    return tier


def _safe_id(raw: str, prefix: str) -> str:
    cleaned = _NON_ID_CHAR.sub("_", raw)
    if not cleaned:
        return prefix
    if cleaned[:1].isdigit():
        return f"{prefix}_{cleaned}"
    return cleaned


def _unique_id(base: str, used: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _serialize(root: ET.Element) -> bytes:
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    _head, marker, body = payload.partition(b"?>")
    if not marker:
        return payload
    return _XML_DECLARATION + body


def to_drawio(twin: DigitalTwin) -> bytes:
    """Return deterministic draw.io XML bytes for ``twin``'s modeled topology."""
    devices = sorted(twin.topology.devices, key=lambda item: item.id)[:MAX_NODES]
    links = sorted(twin.topology.links, key=lambda item: item.id)[:MAX_EDGES]

    grouped: dict[int, list[str]] = {}
    for device in sorted(devices, key=lambda item: (_device_tier(item), item.site, item.id)):
        grouped.setdefault(_device_tier(device), []).append(device.id)

    positions: dict[str, tuple[int, int]] = {}
    for tier in sorted(grouped):
        for index, device_id in enumerate(grouped[tier]):
            positions[device_id] = (tier * _TIER_WIDTH, index * _NODE_HEIGHT)

    devices_by_id = {device.id: device for device in devices}
    used: set[str] = {"0", "1"}
    node_cells: dict[str, str] = {}

    root = ET.Element("mxfile", {"host": "NetArchitect AI"})
    diagram = ET.SubElement(root, "diagram", {"id": "twin-topology", "name": "Topology"})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1400",
            "dy": "800",
            "grid": "0",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "0",
            "pageScale": "1",
            "pageWidth": "850",
            "pageHeight": "1100",
            "math": "0",
            "shadow": "0",
        },
    )
    graph_root = ET.SubElement(model, "root")
    ET.SubElement(graph_root, "mxCell", {"id": "0"})
    ET.SubElement(graph_root, "mxCell", {"id": "1", "parent": "0"})

    for device_id in sorted(devices_by_id, key=lambda item: (positions[item], item)):
        device = devices_by_id[device_id]
        cell_id = _unique_id(_safe_id(device_id, "n"), used)
        node_cells[device_id] = cell_id
        x_position, y_position = positions[device_id]
        vertex = ET.SubElement(
            graph_root,
            "mxCell",
            {
                "id": cell_id,
                "value": f"{device_id} ({device.role.value}/{device.type.value})",
                "style": (
                    "rounded=1;whiteSpace=wrap;html=1;"
                    "fillColor=#f5f5f5;strokeColor=#666666;"
                ),
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            vertex,
            "mxGeometry",
            {
                "x": str(x_position),
                "y": str(y_position),
                "width": str(_NODE_WIDTH),
                "height": str(_NODE_BOX_HEIGHT),
                "as": "geometry",
            },
        )

    for link in links:
        first, second = link.endpoints
        if first not in node_cells or second not in node_cells:
            continue
        cell_id = _unique_id(_safe_id(link.id, "e"), used)
        label = (
            f"{link.id} | {_number(link.capacity_mbps)} Mbps | "
            f"cost={_number(link.cost)}"
        )
        style = "edgeStyle=orthogonalEdgeStyle;html=1;rounded=1;"
        style += "endArrow=block;" if link.directed else "endArrow=none;"
        edge = ET.SubElement(
            graph_root,
            "mxCell",
            {
                "id": cell_id,
                "value": label,
                "style": style,
                "edge": "1",
                "parent": "1",
                "source": node_cells[first],
                "target": node_cells[second],
            },
        )
        ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})

    return enforce_size(_serialize(root), kind="draw.io")


__all__ = ["to_drawio"]
