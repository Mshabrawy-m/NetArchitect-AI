"""Cold-start import and bounded-cache regression tests."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_child(code: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_cold_app_import_defers_heavy_modules() -> None:
    result = _run_child(
        """
import json
import sys
import app
names = [
    "reportlab",
    "services.reporting",
    "services.export",
    "ui.pages.agent_control_center",
    "ui.pages.ai_designer",
    "ui.pages.reports",
    "ui.pages.security_analysis",
]
print(json.dumps({name: name in sys.modules for name in names}))
"""
    )
    assert result == {name: False for name in result}


def test_export_package_loads_pdf_only_on_first_use() -> None:
    result = _run_child(
        """
import json
import sys
import services.export as exports
names = ["reportlab", "services.export.pdf"]
before = {name: name in sys.modules for name in names}
helper = exports.to_pdf
after = {name: name in sys.modules for name in names}
print(json.dumps({"before": before, "after": after, "callable": callable(helper)}))
"""
    )
    assert result["before"] == {"reportlab": False, "services.export.pdf": False}
    assert result["after"] == {"reportlab": True, "services.export.pdf": True}
    assert result["callable"] is True


def test_lazy_exports_keep_function_names_after_submodule_load() -> None:
    result = _run_child(
        """
import json
from services.export import (
    config_templates,
    csv_tables,
    to_config_bundle,
    to_csv_bundle,
)
print(json.dumps({
    "config_templates": callable(config_templates),
    "csv_tables": callable(csv_tables),
    "to_config_bundle": callable(to_config_bundle),
    "to_csv_bundle": callable(to_csv_bundle),
}))
"""
    )
    assert result == {
        "config_templates": True,
        "csv_tables": True,
        "to_config_bundle": True,
        "to_csv_bundle": True,
    }


def test_all_cache_data_decorators_are_bounded() -> None:
    tree = ast.parse((ROOT / "ui" / "cache.py").read_text(encoding="utf-8"))
    cache_entries = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id == "CACHE_ENTRIES"
    }
    assert cache_entries == {"CACHE_ENTRIES"}

    decorators = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "cache_data"
    ]
    assert len(decorators) == 8
    for decorator in decorators:
        keywords = {
            keyword.arg: keyword.value
            for keyword in decorator.keywords
            if keyword.arg is not None
        }
        assert isinstance(keywords.get("max_entries"), ast.Name)
        assert keywords["max_entries"].id == "CACHE_ENTRIES"
        assert isinstance(keywords.get("show_spinner"), ast.Constant)
        assert keywords["show_spinner"].value is False
