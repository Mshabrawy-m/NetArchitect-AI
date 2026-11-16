"""Content-keyed caches for pure, expensive computations.

Every cached function is pure: its result depends only on the arguments it
receives. Streamlit's ``cache_data`` hashes those arguments, so a cache entry is
reused on reruns while the underlying twin and selected sources stay identical
and is bypassed as soon as any of them changes.

The caches are keyed by the canonical twin JSON *and* the twin fingerprint.
The fingerprint alone is already unique per twin revision; passing the JSON as
well lets the cached function rebuild the model without touching session state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import streamlit as st

from digital_twin import DigitalTwin, to_json
from optimization import OptimizationRun
from services.export import (
    pdf_warnings,
    to_config_bundle,
    to_csv_bundle,
    to_markdown,
    to_pdf,
)
from services.export import (
    to_json as document_to_json,
)
from services.reporting import ReportDocument, ReportSources, build_report
from services.validation import DesignHealth, build_design_health
from simulation import ScenarioRun, twin_fingerprint

CACHE_ENTRIES = 8


def twin_payload(twin: DigitalTwin) -> str:
    """Return the compact canonical JSON used as a cache payload."""
    return to_json(twin, indent=None)


def twin_cache_key(twin: DigitalTwin) -> str:
    """Return the stable content key for one twin revision."""
    return twin_fingerprint(twin)


def source_payload(source: ScenarioRun | OptimizationRun | None) -> str:
    """Return canonical JSON for an optional cacheable report source.

    ``WorkflowState`` is deliberately absent: it holds a live baseline accessor
    and is not serializable, so a workflow-backed report is built directly
    instead of entering a content-keyed cache.
    """
    if source is None:
        return ""
    return source.model_dump_json()


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def cached_design_health(
    twin_payload: str,
    include_expensive: bool,
    constraints: tuple[str, ...] = (),
) -> DesignHealth:
    """Build the design-health report once per twin revision and options."""
    return build_design_health(
        DigitalTwin.model_validate_json(twin_payload),
        include_expensive=include_expensive,
        constraints=constraints,
    )


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def cached_report(
    twin_payload: str,
    scenario_payload: str,
    optimization_payload: str,
    generated_at_iso: str,
    title: str = "",
) -> ReportDocument:
    """Build one report document once per twin revision and source selection."""
    return build_report(
        ReportSources(
            twin=DigitalTwin.model_validate_json(twin_payload),
            scenario_run=(
                ScenarioRun.model_validate_json(scenario_payload)
                if scenario_payload
                else None
            ),
            optimization_run=(
                OptimizationRun.model_validate_json(optimization_payload)
                if optimization_payload
                else None
            ),
            generated_at=datetime.fromisoformat(generated_at_iso),
            title=title,
        )
    )


@dataclass(frozen=True)
class ExportBundle:
    """All in-memory report exports for one document and twin revision."""

    pdf: bytes
    markdown: bytes
    json: bytes
    csv: bytes
    config: bytes
    warnings: tuple[str, ...] = ()


@st.cache_data(show_spinner=False, max_entries=CACHE_ENTRIES)
def cached_exports(document_payload: str, twin_payload: str) -> ExportBundle:
    """Build every export once per filtered document and twin revision."""
    document = ReportDocument.model_validate_json(document_payload)
    return ExportBundle(
        pdf=to_pdf(document),
        markdown=to_markdown(document),
        json=document_to_json(document),
        csv=to_csv_bundle(document),
        config=to_config_bundle(DigitalTwin.model_validate_json(twin_payload)),
        warnings=pdf_warnings(document),
    )


__all__ = [
    "ExportBundle",
    "cached_design_health",
    "cached_exports",
    "cached_report",
    "source_payload",
    "twin_cache_key",
    "twin_payload",
]
