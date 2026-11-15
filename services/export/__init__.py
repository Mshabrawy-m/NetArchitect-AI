"""Report exporters (Phase 11b).

Every exporter is a pure function of a validated
:class:`~services.reporting.models.ReportDocument` (or, for configuration
templates, a validated digital twin). Exports are returned as in-memory bytes:
nothing is written to disk and no device is contacted.
"""

from .config_templates import (
    TEMPLATE_HEADER,
    ConfigTemplate,
    config_templates,
    to_config_bundle,
)
from .csv_export import (
    CSV_ENCODING_NOTE,
    CSV_TABLE_IDS,
    CsvTable,
    csv_tables,
    to_csv_bundle,
)
from .json_export import from_json, to_json
from .markdown import to_markdown
from .pdf import NON_LATIN_NOTICE, pdf_page_count, pdf_warnings, to_pdf

__all__ = [
    "CSV_ENCODING_NOTE",
    "CSV_TABLE_IDS",
    "NON_LATIN_NOTICE",
    "TEMPLATE_HEADER",
    "ConfigTemplate",
    "CsvTable",
    "config_templates",
    "csv_tables",
    "from_json",
    "pdf_page_count",
    "pdf_warnings",
    "to_config_bundle",
    "to_csv_bundle",
    "to_json",
    "to_markdown",
    "to_pdf",
]
