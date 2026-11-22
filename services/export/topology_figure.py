"""Deterministic, print-safe vector topology figure for PDF export.

The figure is a ReportLab ``Drawing`` (and therefore a ``Flowable``) built only
from vector primitives. It uses the same role tiers and left-to-right layering
as the interactive topology view without importing Streamlit or the UI layer.
No files are written and no clock is consulted.
"""

from __future__ import annotations

from io import BytesIO
from math import cos, hypot, sin
from typing import TYPE_CHECKING

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Flowable, SimpleDocTemplate

from config.limits import MAX_EDGES, MAX_NODES

from .arabic import logical_to_visual, shape_arabic
from .pdf import ensure_arabic_font

if TYPE_CHECKING:  # pragma: no cover - typing only
    from digital_twin import DigitalTwin

_PALETTE: dict[str, str] = {
    "background": "#FFFFFF",
    "panel": "#F4F6F8",
    "border": "#B8BFC7",
    "text": "#1F2A37",
    "muted": "#5B6773",
    "node": "#DCE8F5",
    "node_border": "#1F3B57",
    "link": "#6B7785",
    "directed": "#1F6F4A",
}

# Mirrors ui.topology_view.ROLE_TIERS without importing the UI package.
_ROLE_TIERS: dict[str, int] = {
    "wan": 0,
    "border": 0,
    "dmz": 1,
    "core": 1,
    "distribution": 2,
    "aggregation": 2,
    "access": 3,
    "edge": 3,
}
_ENDPOINT_TYPES = frozenset({"server", "host"})

_MAX_DEVICE_LABELS = 12
_MAX_LINK_LABELS = 16
_LEGEND_HEIGHT = 46.0
_MARGIN_X = 10.0
_MARGIN_Y = 10.0
_NODE_HEIGHT = 18.0
_FONT_SIZE = 6.5

_ARABIC_LANGUAGES = frozenset({"ar", "ara", "arb", "arabic", "العربية"})


def _is_arabic(language: str) -> bool:
    return str(language).strip().lower() in _ARABIC_LANGUAGES


def _label(text: object, *, arabic: bool) -> str:
    """Return a bounded, render-safe label in display order."""
    value = str(text).replace("\r", " ").replace("\n", " ")[:24]
    if arabic:
        return logical_to_visual(shape_arabic(value))
    return value


def _device_tier(device: object) -> int:
    role = str(getattr(getattr(device, "role", None), "value", ""))
    tier = _ROLE_TIERS.get(role, 2)
    device_type = str(getattr(getattr(device, "type", None), "value", ""))
    if tier >= 3 and device_type in _ENDPOINT_TYPES:
        return 4
    return tier


def _colour(value: str, palette: dict[str, str]):
    return colors.HexColor(palette.get(value, _PALETTE[value]))


def _capacity_text(capacity_mbps: float) -> str:
    rounded = round(float(capacity_mbps), 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


def _arrow_head(
    x_tip: float,
    y_tip: float,
    x_from: float,
    y_from: float,
    stroke,
) -> list[Line]:
    delta_x = x_tip - x_from
    delta_y = y_tip - y_from
    length = hypot(delta_x, delta_y)
    if length == 0:
        return []
    unit_x = delta_x / length
    unit_y = delta_y / length
    size = 5.0
    spread = 0.55
    points = []
    for angle in (spread, -spread):
        x_base = x_tip - size * (
            unit_x * cos(angle) - unit_y * sin(angle)
        )
        y_base = y_tip - size * (
            unit_x * sin(angle) + unit_y * cos(angle)
        )
        points.append(Line(x_tip, y_tip, x_base, y_base, strokeColor=stroke, strokeWidth=0.9))
    return points


def topology_flowable(
    twin: DigitalTwin,
    *,
    width: float = 520.0,
    max_height: float = 260.0,
    language: str = "en",
    palette: dict[str, str] | None = None,
) -> Flowable:
    """Build a bounded vector topology drawing for one digital twin."""
    effective_palette = dict(_PALETTE)
    if palette:
        effective_palette.update(palette)
    arabic = _is_arabic(language)
    if arabic:
        ensure_arabic_font()
    font = "NotoNaskhArabic" if arabic else "Helvetica"
    drawing_width = float(width) if width > 0 else 520.0
    drawing_max_height = float(max_height) if max_height > 0 else 260.0

    devices = list(twin.topology.devices)[:MAX_NODES]
    device_ids = {device.id for device in devices}
    links = [
        link
        for link in list(twin.topology.links)[:MAX_EDGES]
        if all(endpoint in device_ids for endpoint in link.endpoints)
    ]

    groups: dict[int, list[object]] = {}
    for device in sorted(
        devices, key=lambda item: (_device_tier(item), item.site, item.id)
    ):
        groups.setdefault(_device_tier(device), []).append(device)
    tier_keys = sorted(groups)
    if tier_keys:
        rows = len(groups[tier_keys[0]])
        for tier in tier_keys[1:]:
            rows = max(rows, len(groups[tier]))
    else:
        rows = 1

    computed_height = 82.0 + 18.0 * rows + _LEGEND_HEIGHT
    height = min(computed_height, drawing_max_height)
    drawing = Drawing(drawing_width, height)
    drawing.add(
        Rect(
            0,
            0,
            drawing_width,
            height,
            fillColor=_colour("background", effective_palette),
            strokeColor=None,
        )
    )
    drawing.add(
        String(
            _MARGIN_X,
            height - 13,
            _label("Topology", arabic=arabic),
            fontName=font,
            fontSize=8,
            fillColor=_colour("text", effective_palette),
        )
    )

    if not devices:
        drawing.add(
            String(
                _MARGIN_X,
                height / 2,
                _label("Empty topology", arabic=arabic),
                fontName=font,
                fontSize=9,
                fillColor=_colour("muted", effective_palette),
            )
        )
        _add_legend(drawing, drawing_width, effective_palette, font, arabic)
        return drawing

    content_width = drawing_width - 2 * _MARGIN_X
    column_width = content_width / len(tier_keys)
    node_width = column_width - 12.0 if column_width > 24.0 else column_width * 0.7
    node_width = min(node_width, 74.0)
    top = height - _LEGEND_HEIGHT - _MARGIN_Y - 18.0
    bottom = _LEGEND_HEIGHT + _MARGIN_Y + 8.0
    usable_height = max(top - bottom, 10.0)

    positions: dict[str, tuple[float, float]] = {}
    for column, tier in enumerate(tier_keys):
        tier_devices = groups[tier]
        centre_x = _MARGIN_X + column_width * (column + 0.5)
        count = len(tier_devices)
        for index, device in enumerate(tier_devices):
            if count == 1:
                y_position = bottom + usable_height / 2
            else:
                y_position = top - usable_height * index / (count - 1)
            positions[device.id] = (centre_x, y_position)

    half_width = node_width / 2
    half_height = _NODE_HEIGHT / 2
    link_stroke = _colour("link", effective_palette)
    directed_stroke = _colour("directed", effective_palette)
    for link in links:
        x1, y1 = positions[link.endpoints[0]]
        x2, y2 = positions[link.endpoints[1]]
        delta_x = x2 - x1
        delta_y = y2 - y1
        if delta_x == 0 and delta_y == 0:
            continue
        scale_x = half_width / abs(delta_x) if delta_x else float("inf")
        scale_y = half_height / abs(delta_y) if delta_y else float("inf")
        scale = min(scale_x, scale_y)
        scale = min(scale, 1.0)
        start_x = x1 + delta_x * scale
        start_y = y1 + delta_y * scale
        end_x = x2 - delta_x * scale
        end_y = y2 - delta_y * scale
        stroke = directed_stroke if link.directed else link_stroke
        drawing.add(
            Line(
                start_x,
                start_y,
                end_x,
                end_y,
                strokeColor=stroke,
                strokeWidth=0.9,
            )
        )
        if link.directed:
            for segment in _arrow_head(end_x, end_y, start_x, start_y, stroke):
                drawing.add(segment)

    device_stride = 1
    if len(devices) > _MAX_DEVICE_LABELS:
        device_stride = (len(devices) + _MAX_DEVICE_LABELS - 1) // _MAX_DEVICE_LABELS
    shown_devices = 0
    for index, device in enumerate(devices):
        centre_x, y_position = positions[device.id]
        drawing.add(
            Rect(
                centre_x - half_width,
                y_position - half_height,
                node_width,
                _NODE_HEIGHT,
                rx=3,
                ry=3,
                fillColor=_colour("node", effective_palette),
                strokeColor=_colour("node_border", effective_palette),
                strokeWidth=0.7,
            )
        )
        if index % device_stride:
            continue
        drawing.add(
            String(
                centre_x,
                y_position - 2,
                _label(device.id, arabic=arabic),
                fontName=font,
                fontSize=_FONT_SIZE,
                textAnchor="middle",
                fillColor=_colour("text", effective_palette),
            )
        )
        shown_devices += 1

    link_stride = 1
    if len(links) > _MAX_LINK_LABELS:
        link_stride = (len(links) + _MAX_LINK_LABELS - 1) // _MAX_LINK_LABELS
    shown_links = 0
    for index, link in enumerate(links):
        if index % link_stride:
            continue
        x1, y1 = positions[link.endpoints[0]]
        x2, y2 = positions[link.endpoints[1]]
        caption = _label(
            f"{link.id} {_capacity_text(link.capacity_mbps)} Mbps", arabic=arabic
        )
        drawing.add(
            String(
                (x1 + x2) / 2,
                (y1 + y2) / 2 + 3,
                caption,
                fontName=font,
                fontSize=_FONT_SIZE - 0.5,
                textAnchor="middle",
                fillColor=_colour("muted", effective_palette),
            )
        )
        shown_links += 1

    thinned = (
        shown_devices < len(devices)
        or shown_links < len(links)
    )
    if thinned:
        drawing.add(
            String(
                _MARGIN_X,
                height - 24,
                f"Showing {shown_devices + shown_links} of "
                f"{len(devices) + len(links)} labels",
                fontName="Helvetica",
                fontSize=6,
                fillColor=_colour("muted", effective_palette),
            )
        )
    _add_legend(drawing, drawing_width, effective_palette, font, arabic)
    return drawing


def _add_legend(
    drawing: Drawing,
    width: float,
    palette: dict[str, str],
    font: str,
    arabic: bool,
) -> None:
    drawing.add(
        Rect(
            4,
            4,
            width - 8,
            _LEGEND_HEIGHT - 8,
            rx=3,
            ry=3,
            fillColor=_colour("panel", palette),
            strokeColor=_colour("border", palette),
            strokeWidth=0.5,
        )
    )
    drawing.add(
        String(
            10,
            _LEGEND_HEIGHT - 12,
            _label("Legend", arabic=arabic),
            fontName=font,
            fontSize=7,
            fillColor=_colour("text", palette),
        )
    )
    drawing.add(
        Rect(
            12,
            13,
            12,
            8,
            rx=2,
            ry=2,
            fillColor=_colour("node", palette),
            strokeColor=_colour("node_border", palette),
            strokeWidth=0.6,
        )
    )
    drawing.add(
        String(
            30,
            15,
            _label("Device", arabic=arabic),
            fontName=font,
            fontSize=6,
            fillColor=_colour("muted", palette),
        )
    )
    drawing.add(
        Line(
            92,
            17,
            118,
            17,
            strokeColor=_colour("link", palette),
            strokeWidth=0.9,
        )
    )
    drawing.add(
        String(
            124,
            15,
            _label("Undirected", arabic=arabic),
            fontName=font,
            fontSize=6,
            fillColor=_colour("muted", palette),
        )
    )
    directed = _colour("directed", palette)
    drawing.add(
        Line(212, 17, 238, 17, strokeColor=directed, strokeWidth=0.9)
    )
    for segment in _arrow_head(238, 17, 212, 17, directed):
        drawing.add(segment)
    drawing.add(
        String(
            244,
            15,
            _label("Directed", arabic=arabic),
            fontName=font,
            fontSize=6,
            fillColor=_colour("muted", palette),
        )
    )


def topology_figure_pdf(
    twin: DigitalTwin,
    *,
    width: float = 520.0,
    max_height: float = 260.0,
    language: str = "en",
    palette: dict[str, str] | None = None,
) -> bytes:
    """Return a deterministic one-page PDF containing the topology figure."""
    flowable = topology_flowable(
        twin,
        width=width,
        max_height=max_height,
        language=language,
        palette=palette,
    )
    margin = 8.0
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title="Topology",
        author="NetArchitect AI",
        subject="Network topology figure",
        creator="NetArchitect AI",
        pageCompression=0,
        invariant=1,
    )
    document.build([flowable])
    return buffer.getvalue()


def topology_figure(
    twin: DigitalTwin,
    *,
    width: float = 520.0,
    max_height: float = 260.0,
    language: str = "en",
    palette: dict[str, str] | None = None,
) -> bytes:
    """Alias of :func:`topology_figure_pdf` kept for the public export API."""
    return topology_figure_pdf(
        twin,
        width=width,
        max_height=max_height,
        language=language,
        palette=palette,
    )


__all__ = ["topology_figure", "topology_figure_pdf", "topology_flowable"]
