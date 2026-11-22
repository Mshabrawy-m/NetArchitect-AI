"""Forward-only migrations for the project-bundle manifest (B1).

Migrations run before typed validation so an older manifest can be normalised
into the current shape. They never recompute a fingerprint: provenance recorded
at capture time is preserved verbatim. A future version is always rejected
rather than best-effort parsed, because silently dropping unknown sections would
lose provenance.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from .errors import BundleMigrationError, BundleVersionError
from .models import (
    CURRENT_BUNDLE_VERSION,
    MIN_BUNDLE_VERSION,
    SECRET_SETTING_TOKENS,
)

_Migration = Callable[[dict[str, Any]], dict[str, Any]]


def _strip_secret_settings(manifest: dict[str, Any]) -> None:
    settings = manifest.get("settings")
    if not isinstance(settings, dict):
        manifest["settings"] = {}
        return
    manifest["settings"] = {
        str(key): str(value)
        for key, value in settings.items()
        if not any(token in str(key).upper() for token in SECRET_SETTING_TOKENS)
    }


def _migrate_v1_to_v2(manifest: dict[str, Any]) -> dict[str, Any]:
    """Normalise the first bundle shape to the current section layout."""
    sections = manifest.get("sections")
    if not isinstance(sections, dict):
        sections = {}
    sections = dict(sections)
    legacy_decisions = sections.pop("decision_log", None)
    if legacy_decisions is not None and "decisions" not in sections:
        sections["decisions"] = legacy_decisions
    sections.setdefault("twin", "twin.json")
    manifest["sections"] = sections

    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    provenance = dict(provenance)
    provenance.setdefault("twin_fingerprint", "")
    provenance.setdefault("source_fingerprints", {})
    manifest["provenance"] = provenance

    if not isinstance(manifest.get("members"), dict):
        manifest["members"] = {}
    if not isinstance(manifest.get("limits"), dict):
        manifest["limits"] = {}
    if not isinstance(manifest.get("source_app_version"), str):
        manifest["source_app_version"] = "unknown"
    _strip_secret_settings(manifest)
    return manifest


_MIGRATIONS: dict[int, _Migration] = {
    1: _migrate_v1_to_v2,
}


def migrate_manifest(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Return a migrated copy of ``manifest`` and the applied migration names."""
    version = manifest.get("bundle_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise BundleVersionError("Bundle manifest has no integer bundle_version.")
    if version < MIN_BUNDLE_VERSION:
        raise BundleVersionError(
            f"Bundle version {version} is older than the minimum supported "
            f"version {MIN_BUNDLE_VERSION}."
        )
    if version > CURRENT_BUNDLE_VERSION:
        raise BundleVersionError(
            f"Bundle version {version} is newer than this build supports "
            f"(max {CURRENT_BUNDLE_VERSION}); upgrade the application first."
        )

    working = copy.deepcopy(dict(manifest))
    applied: list[str] = []
    while working["bundle_version"] < CURRENT_BUNDLE_VERSION:
        step = working["bundle_version"]
        migration = _MIGRATIONS.get(step)
        if migration is None:
            raise BundleMigrationError(f"No migration registered for bundle v{step}.")
        working = migration(working)
        applied.append(f"v{step}_to_v{step + 1}")
        working["bundle_version"] = step + 1
    _strip_secret_settings(working)
    return working, tuple(applied)


__all__ = ["migrate_manifest"]
