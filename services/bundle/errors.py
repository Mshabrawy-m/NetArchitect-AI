"""Typed errors for in-memory project bundles (B1).

Every failure raised while building or restoring a bundle is a subclass of
:class:`BundleError`, itself a :class:`~core.exceptions.NetArchitectError`. The
UI can therefore show one readable message per category without string
matching. Error messages never include the rejected payload.
"""

from __future__ import annotations

from core.exceptions import NetArchitectError


class BundleError(NetArchitectError):
    """Base class for project-bundle failures."""


class BundleFormatError(BundleError):
    """The archive or one of its members is not a valid bundle payload."""


class BundleLimitError(BundleError):
    """A bundle exceeds a size, count, or decompression bound."""


class BundlePathError(BundleError):
    """A ZIP member name is unsafe or outside the allowed layout."""


class BundleChecksumError(BundleError):
    """A ZIP member does not match the checksum in the manifest."""


class BundleVersionError(BundleError):
    """The bundle version is unknown, too old, or from the future."""


class BundleMigrationError(BundleError):
    """A version migration could not be applied safely."""


__all__ = [
    "BundleChecksumError",
    "BundleError",
    "BundleFormatError",
    "BundleLimitError",
    "BundleMigrationError",
    "BundlePathError",
    "BundleVersionError",
]
