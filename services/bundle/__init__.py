"""In-memory project bundles (B1).

A bundle is one deterministic ZIP produced and consumed entirely in memory. It
carries a digital twin, snapshots, engine runs with their source fingerprints,
a decision log, modeled security flow requests, and a non-secret settings
snapshot. Import is hostile-input-safe: fixed member allowlist, size and
decompression caps, guarded JSON parsing, typed errors, checksum verification,
and forward-only manifest migrations.

The app never writes a bundle to disk; ``--out`` in the CLI is the only file
write path in the project.
"""

from __future__ import annotations

from .errors import (
    BundleChecksumError,
    BundleError,
    BundleFormatError,
    BundleLimitError,
    BundleMigrationError,
    BundlePathError,
    BundleVersionError,
)
from .models import (
    CURRENT_BUNDLE_VERSION,
    MIN_BUNDLE_VERSION,
    BundleData,
    BundleManifest,
    BundleProvenance,
    BundleSections,
    BundleSourceFingerprints,
)
from .service import build_bundle, limits_snapshot, read_bundle, settings_snapshot

__all__ = [
    "CURRENT_BUNDLE_VERSION",
    "MIN_BUNDLE_VERSION",
    "BundleChecksumError",
    "BundleData",
    "BundleError",
    "BundleFormatError",
    "BundleLimitError",
    "BundleManifest",
    "BundleMigrationError",
    "BundlePathError",
    "BundleProvenance",
    "BundleSections",
    "BundleSourceFingerprints",
    "BundleVersionError",
    "build_bundle",
    "limits_snapshot",
    "read_bundle",
    "settings_snapshot",
]
