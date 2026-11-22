"""Report exporters (Phase 11b).

Every exporter is a pure function of a validated
:class:`~services.reporting.models.ReportDocument` (or, for configuration
templates, a validated digital twin). Exports are returned as in-memory bytes:
nothing is written to disk and no device is contacted.

Implementation modules are loaded on first use so report building and ReportLab
stay out of cold start.
"""

from __future__ import annotations

import sys
from typing import Any

__all__ = [
    "CSV_ENCODING_NOTE",
    "CSV_TABLE_IDS",
    "NON_LATIN_NOTICE",
    "TEMPLATE_HEADER",
    "ConfigTemplate",
    "CsvTable",
    "config_templates",
    "contains_arabic",
    "csv_tables",
    "from_json",
    "logical_to_visual",
    "pdf_page_count",
    "pdf_warnings",
    "to_config_bundle",
    "to_csv_bundle",
    "to_drawio",
    "to_graphml",
    "to_inventory_csv",
    "to_json",
    "to_markdown",
    "to_mermaid",
    "to_pdf",
    "topology_figure",
    "topology_figure_pdf",
    "topology_flowable",
]

_LAZY_EXPORTS = {
    "CSV_ENCODING_NOTE": ".csv_export",
    "CSV_TABLE_IDS": ".csv_export",
    "NON_LATIN_NOTICE": ".pdf",
    "TEMPLATE_HEADER": ".config_templates",
    "ConfigTemplate": ".config_templates",
    "CsvTable": ".csv_export",
    "config_templates": ".config_templates",
    "csv_tables": ".csv_export",
    "from_json": ".json_export",
    "contains_arabic": ".arabic",
    "logical_to_visual": ".arabic",
    "pdf_page_count": ".pdf",
    "pdf_warnings": ".pdf",
    "to_config_bundle": ".config_templates",
    "to_csv_bundle": ".csv_export",
    "to_drawio": ".drawio",
    "to_graphml": ".graphml",
    "to_inventory_csv": ".inventory",
    "to_json": ".json_export",
    "to_markdown": ".markdown",
    "to_mermaid": ".mermaid",
    "to_pdf": ".pdf",
    "topology_figure": ".topology_figure",
    "topology_figure_pdf": ".topology_figure",
    "topology_flowable": ".topology_figure",
}

# Import machinery binds a loaded submodule as an attribute of its package.
# These two public functions share a name with their implementation module, so
# restore the function binding after any lazy import.
_SHADOWED_BY_SUBMODULES = {
    "config_templates": ".config_templates",
    "csv_tables": ".csv_export",
}


def _restore_shadowed_functions() -> None:
    for name, module_name in _SHADOWED_BY_SUBMODULES.items():
        module = sys.modules.get(f"{__name__}{module_name}")
        if module is not None:
            globals()[name] = getattr(module, name)


def __getattr__(name: str) -> Any:
    """Load an export implementation only when a caller uses it."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from importlib import import_module

    module = import_module(module_name, __name__)
    _restore_shadowed_functions()
    value = getattr(module, name)
    globals()[name] = value
    return value
