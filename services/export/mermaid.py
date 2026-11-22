"""Deterministic Mermaid flowchart export for a digital twin.

The diagram is a rendering of modeled design intent only. Identifiers are
mapped to safe Mermaid tokens and all label text is escaped, so untrusted
device/link names cannot terminate a node or edge declaration.
"""

from __future__ import annotations

import re

from config.limits import MAX_EDGES, MAX_NODES
from digital_twin import DigitalTwin

DESIGN_INTENT_COMMENT = (
    "%% Values below are modeled design intent; none are applied to devices."
)
MAX_LABEL_CHARS = 160

_NON_ID_CHAR = re.compile(r"[^A-Za-z0-9_]")
# Mermaid entity codes keep the original meaning without raw syntax delimiters.
_LABEL_ESCAPES = str.maketrans(
    {
        "#": "#35;",
        '"': "#quot;",
        "[": "#91;",
        "]": "#93;",
        "(": "#40;",
        ")": "#41;",
        "{": "#123;",
        "}": "#125;",
        "<": "#lt;",
        ">": "#gt;",
        "|": "#124;",
        "\n": " ",
        "\r": " ",
        "\t": " ",
    }
)


def _number(value: float) -> str:
    return str(value)


def _safe_id(raw: str, prefix: str) -> str:
    """Map an arbitrary identifier to a safe, non-empty Mermaid token base."""
    cleaned = _NON_ID_CHAR.sub("_", raw)
    if not cleaned:
        return prefix
    if cleaned[:1].isdigit():
        return f"{prefix}_{cleaned}"
    return cleaned


def _unique_id(base: str, used: set[str]) -> str:
    """Return a stable unused token, adding a numeric suffix on collision."""
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _label(value: str) -> str:
    """Escape one label and keep it within a bounded character count."""
    text = value.translate(_LABEL_ESCAPES)
    if len(text) > MAX_LABEL_CHARS:
        return text[: MAX_LABEL_CHARS - 3] + "..."
    return text


def to_mermaid(twin: DigitalTwin) -> str:
    """Return a deterministic ``flowchart LR`` description of ``twin``."""
    devices = sorted(twin.topology.devices, key=lambda item: item.id)[:MAX_NODES]
    included = {device.id for device in devices}
    links = [
        link
        for link in sorted(twin.topology.links, key=lambda item: item.id)[:MAX_EDGES]
        if all(endpoint in included for endpoint in link.endpoints)
    ]

    used: set[str] = set()
    node_ids: dict[str, str] = {}
    lines = [DESIGN_INTENT_COMMENT, "flowchart LR"]

    for device in devices:
        node_id = _unique_id(_safe_id(device.id, "device"), used)
        node_ids[device.id] = node_id
        label = _label(f"{device.id} ({device.role.value}/{device.type.value})")
        lines.append(f'{node_id}["{label}"]')

    for link in links:
        first, second = link.endpoints
        if first not in node_ids or second not in node_ids:
            continue
        arrow = "-->" if link.directed else "---"
        label = _label(
            f"{link.id} {_number(link.capacity_mbps)} Mbps "
            f"cost={_number(link.cost)}"
        )
        lines.append(f'{node_ids[first]} {arrow}|"{label}"| {node_ids[second]}')

    return "\n".join(lines) + "\n"


__all__ = ["DESIGN_INTENT_COMMENT", "MAX_LABEL_CHARS", "to_mermaid"]
