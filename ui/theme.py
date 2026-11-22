"""Single source of design tokens for NetArchitect AI.

All UI modules import colors and spacing from here. ``.streamlit/config.toml``
mirrors the light and dark palettes because Streamlit reads theme colors before
Python starts; keep the two files in sync when changing a brand color.
"""

from __future__ import annotations

from types import MappingProxyType

import streamlit as st

FONT_FAMILY = "Source Sans 3"

SPACING = MappingProxyType(
    {
        "xs": 4,
        "sm": 8,
        "md": 12,
        "lg": 16,
        "xl": 24,
        "2xl": 32,
    }
)

# Light palette. Text colors are chosen for >= 4.5:1 contrast on their surface.
LIGHT = MappingProxyType(
    {
        "background": "#ffffff",
        "surface": "#f4f6f8",
        "surface_alt": "#e9edf2",
        "border": "#d4dce5",
        "text": "#1b2b3a",
        "muted": "#526273",
        "primary": "#1f5f8b",
        "primary_text": "#ffffff",
        "link": "#1f5f8b",
        "ok": "#166b47",
        "ok_surface": "#e8f3ea",
        "warn": "#8a5a00",
        "warn_surface": "#fff4d6",
        "critical": "#a12d2d",
        "critical_surface": "#fae7e7",
        "info": "#1f5f8b",
        "info_surface": "#e8f0f6",
        "l2_accent": "#2f6690",
        "wan_accent": "#7a5a20",
        "wireless_accent": "#7a5195",
        "qos_accent": "#1f6f8b",
        "findings_accent": "#a12d2d",
        "chart_text": "#33414f",
        "chart_grid": "#d4dce5",
        "link_undirected": "#7d8c9b",
        "link_directed": "#a15c2f",
        "highlight": "#1f6f8b",
        "baseline": "#8a5a00",
        "role_core": "#1f3a5f",
        "role_distribution": "#2f6690",
        "role_aggregation": "#3d7ea6",
        "role_access": "#7fa8c9",
        "role_border": "#6b4c3b",
        "role_edge": "#4f7cac",
        "role_wan": "#8a6d3b",
        "role_dmz": "#a37b36",
        "zone_1": "#2f6690",
        "zone_2": "#7a5195",
        "zone_3": "#2f7d68",
        "zone_4": "#a15c2f",
        "zone_5": "#4f7cac",
        "zone_6": "#8a6d3b",
        "util_none": "#9aa7b4",
        "util_low": "#7fa8c9",
        "util_medium": "#d98c00",
        "util_high": "#e05a00",
        "util_overload": "#a12d2d",
        "state_normal": "#e8f3ea",
        "state_warning": "#fff4d6",
        "state_critical": "#402528",
        "state_overloaded": "#fae7e7",
        "state_absent": "#e9edf2",
        "bundle_surface": "#e8f0f6",
        "bundle_border": "#b8c9d8",
        "bundle_accent": "#1f5f8b",
    }
)

# Dark palette. It uses the same semantic keys so components need no branches.
DARK = MappingProxyType(
    {
        "background": "#111a24",
        "surface": "#1b2734",
        "surface_alt": "#253444",
        "border": "#3b4b5c",
        "text": "#e8edf2",
        "muted": "#afc0cf",
        "primary": "#8cc8f0",
        "primary_text": "#101923",
        "link": "#8cc8f0",
        "ok": "#6bd9a2",
        "ok_surface": "#18382c",
        "warn": "#f3c46b",
        "warn_surface": "#3b3020",
        "critical": "#ff9a9a",
        "critical_surface": "#402528",
        "info": "#8cc8f0",
        "info_surface": "#1b3346",
        "l2_accent": "#8cc8f0",
        "wan_accent": "#e0c07a",
        "wireless_accent": "#c2a4dc",
        "qos_accent": "#7bd2b4",
        "findings_accent": "#ff9a9a",
        "chart_text": "#d8e2ec",
        "chart_grid": "#3b4b5c",
        "link_undirected": "#9aacbb",
        "link_directed": "#f0b27a",
        "highlight": "#8cc8f0",
        "baseline": "#f3c46b",
        "role_core": "#8cc8f0",
        "role_distribution": "#6faed6",
        "role_aggregation": "#79c4d8",
        "role_access": "#a8d2ea",
        "role_border": "#d9aa8e",
        "role_edge": "#9ec6e8",
        "role_wan": "#e0c07a",
        "role_dmz": "#edcf8e",
        "zone_1": "#8cc8f0",
        "zone_2": "#c2a4dc",
        "zone_3": "#7bd2b4",
        "zone_4": "#f0b27a",
        "zone_5": "#a8d2ea",
        "zone_6": "#e0c07a",
        "util_none": "#9aacbb",
        "util_low": "#a8d2ea",
        "util_medium": "#f3c46b",
        "util_high": "#f0a46b",
        "util_overload": "#ff9a9a",
        "state_normal": "#18382c",
        "state_warning": "#3b3020",
        "state_critical": "#3b3020",
        "state_overloaded": "#402528",
        "state_absent": "#253444",
        "bundle_surface": "#1b3346",
        "bundle_border": "#456783",
        "bundle_accent": "#8cc8f0",
    }
)

PALETTES = MappingProxyType({"light": LIGHT, "dark": DARK})

ROLE_TOKEN_NAMES = MappingProxyType(
    {
        "core": "role_core",
        "distribution": "role_distribution",
        "aggregation": "role_aggregation",
        "access": "role_access",
        "border": "role_border",
        "edge": "role_edge",
        "wan": "role_wan",
        "dmz": "role_dmz",
    }
)

STATUS_TOKEN_NAMES = MappingProxyType(
    {
        "done": "ok",
        "complete": "ok",
        "ok": "ok",
        "incomplete": "muted",
        "stale": "warn",
        "warning": "warn",
        "warn": "warn",
        "critical": "critical",
        "error": "critical",
        "info": "info",
        "pass": "ok",
        "fail": "critical",
        "not-modeled": "info",
    }
)


def active_palette() -> MappingProxyType:
    """Return the palette for the browser's active appearance."""
    theme_type = st.context.theme.get("type") if st.context.theme else None
    return DARK if theme_type == "dark" else LIGHT


def color(token: str, *, palette: MappingProxyType | None = None) -> str:
    """Return one design token color; unknown tokens are a programming error."""
    source = palette if palette is not None else active_palette()
    try:
        return source[token]
    except KeyError as error:
        raise KeyError(f"Unknown color token: {token!r}") from error


def role_color(role: str, *, palette: MappingProxyType | None = None) -> str:
    """Return the color token for a device role."""
    token = ROLE_TOKEN_NAMES.get(role, "role_access")
    return color(token, palette=palette)


def status_color(status: str, *, palette: MappingProxyType | None = None) -> str:
    """Return the semantic color token for a workflow or health status."""
    token = STATUS_TOKEN_NAMES.get(status.lower(), "info")
    return color(token, palette=palette)


def _channel(value: str) -> float:
    normalized = int(value, 16) / 255.0
    if normalized <= 0.04045:
        return normalized / 12.92
    return ((normalized + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    """Return WCAG relative luminance for a ``#RRGGBB`` token."""
    value = hex_color.removeprefix("#")
    if len(value) != 6:
        raise ValueError(f"Expected a #RRGGBB color, got {hex_color!r}")
    red, green, blue = (_channel(value[index : index + 2]) for index in (0, 2, 4))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the WCAG contrast ratio between two token colors."""
    first, second = luminance(foreground), luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


TEXT_CONTRAST_PAIRS = (
    ("text", "background"),
    ("muted", "background"),
    ("text", "surface"),
    ("muted", "surface"),
    ("ok", "ok_surface"),
    ("warn", "warn_surface"),
    ("critical", "critical_surface"),
    ("info", "info_surface"),
    ("bundle_accent", "bundle_surface"),
    ("text", "bundle_surface"),
    ("l2_accent", "surface"),
    ("wan_accent", "surface"),
    ("wireless_accent", "surface"),
    ("qos_accent", "surface"),
    ("findings_accent", "surface"),
    ("primary_text", "primary"),
)


def minimum_text_contrast() -> float:
    """Return the lowest text contrast ratio across both palettes."""
    ratios = [
        contrast_ratio(palette[foreground], palette[background])
        for palette in (LIGHT, DARK)
        for foreground, background in TEXT_CONTRAST_PAIRS
    ]
    return min(ratios)


__all__ = [
    "DARK",
    "FONT_FAMILY",
    "LIGHT",
    "PALETTES",
    "ROLE_TOKEN_NAMES",
    "SPACING",
    "STATUS_TOKEN_NAMES",
    "TEXT_CONTRAST_PAIRS",
    "active_palette",
    "color",
    "contrast_ratio",
    "luminance",
    "minimum_text_contrast",
    "role_color",
    "status_color",
]
