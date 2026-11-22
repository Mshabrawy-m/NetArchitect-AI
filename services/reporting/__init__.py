"""Report building, provenance, and consistency checking (Phase 11a).

Import the public API from this package rather than from the individual
modules. The package is pure Python: it has no Streamlit, ReportLab, or network
dependency.
"""

from .builder import (
    REPORT_TITLE_PREFIX,
    ReportSources,
    build_report,
    filter_sections,
)
from .consistency import (
    ConsistencyCode,
    ConsistencyFinding,
    ConsistencyReport,
    ConsistencySeverity,
    check_consistency,
)
from .executive import EXECUTIVE_SECTION_ID, LANGUAGES, build_executive_summary
from .explain import REPORT_EXPLANATION_SYSTEM_PROMPT, generate_ai_explanation
from .formatting import format_number, numeric_tokens, parse_display
from .models import (
    DISCLOSURE_TEXT,
    MODELED_ESTIMATE_LABEL,
    REPORT_SCHEMA_VERSION,
    REQUIRED_LABELS,
    SAMPLE_DATA_LABEL,
    TEMPLATE_LABEL,
    AIExplanation,
    BlockKind,
    ContentBlock,
    KeyValueBlock,
    KeyValueItem,
    NoteBlock,
    ParagraphBlock,
    Provenance,
    ReportDocument,
    ReportSection,
    ReportTwin,
    SectionStatus,
    TableBlock,
    ValueRecord,
)
from .templates import LIMITATIONS

__all__ = [
    "DISCLOSURE_TEXT",
    "EXECUTIVE_SECTION_ID",
    "LANGUAGES",
    "LIMITATIONS",
    "MODELED_ESTIMATE_LABEL",
    "REPORT_EXPLANATION_SYSTEM_PROMPT",
    "REPORT_SCHEMA_VERSION",
    "REPORT_TITLE_PREFIX",
    "REQUIRED_LABELS",
    "SAMPLE_DATA_LABEL",
    "TEMPLATE_LABEL",
    "AIExplanation",
    "BlockKind",
    "ConsistencyCode",
    "ConsistencyFinding",
    "ConsistencyReport",
    "ConsistencySeverity",
    "ContentBlock",
    "KeyValueBlock",
    "KeyValueItem",
    "NoteBlock",
    "ParagraphBlock",
    "Provenance",
    "ReportDocument",
    "ReportSection",
    "ReportSources",
    "ReportTwin",
    "SectionStatus",
    "TableBlock",
    "ValueRecord",
    "build_executive_summary",
    "build_report",
    "check_consistency",
    "filter_sections",
    "format_number",
    "generate_ai_explanation",
    "numeric_tokens",
    "parse_display",
]
