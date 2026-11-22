"""Design-system invariants for the V2 UI package."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui import theme

ROOT = Path(__file__).resolve().parents[3]
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def test_raw_hex_colors_are_only_in_theme_module() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "ui").rglob("*.py")
        if path.name != "theme.py" and HEX.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_token_palette_meets_text_contrast() -> None:
    assert theme.minimum_text_contrast() >= 4.5
    assert set(theme.LIGHT) == set(theme.DARK)


L2_THEME_TOKENS = (
    "l2_accent",
    "wan_accent",
    "wireless_accent",
    "qos_accent",
    "findings_accent",
)


def test_l2_theme_tokens_exist_in_both_palettes_and_meet_contrast() -> None:
    for token in L2_THEME_TOKENS:
        assert token in theme.LIGHT
        assert token in theme.DARK
        assert (token, "surface") in theme.TEXT_CONTRAST_PAIRS
        assert theme.contrast_ratio(theme.LIGHT[token], theme.LIGHT["surface"]) >= 4.5
        assert theme.contrast_ratio(theme.DARK[token], theme.DARK["surface"]) >= 4.5


def test_config_declares_light_and_dark_with_one_typeface() -> None:
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())
    assert config["theme"]["base"] == "light"
    assert config["theme"]["font"] == theme.FONT_FAMILY
    assert config["theme"]["headingFont"] == theme.FONT_FAMILY
    assert "primaryColor" in config["theme"]["light"]
    assert "primaryColor" in config["theme"]["dark"]


def test_shared_components_render() -> None:
    source = """
from ui.components import (
    callout,
    empty_state,
    key_value_list,
    metric_tile,
    section_header,
    status_badge,
)

metric_tile("Devices", 4, help="From the current twin")
status_badge("done")
section_header("Properties", description="Current design state")
callout("Modeled values only.", kind="model_estimate")
callout("Review the finding.", kind="warn")
empty_state("No data yet.", title="Empty")
key_value_list([("Name", "site-1"), ("Subnet", "10.0.0.0/24")])
"""
    at = AppTest.from_string(source).run()
    assert not at.exception
    assert len(at.metric) == 1
    assert any("Done" in item.value for item in at.markdown)
    assert any(item.value == "Properties" for item in at.subheader)
    assert len(at.dataframe) == 1
