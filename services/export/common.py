"""Shared bounds and deterministic archive helpers for report exports."""

from __future__ import annotations

import io
from collections.abc import Sequence
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from config.limits import MAX_REPORT_BYTES
from core.exceptions import ReportLimitError

# A fixed ZIP member timestamp keeps the produced archive byte-identical for
# the same input, regardless of when the export is requested.
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ZIP_MEMBER_MODE = 0o600 << 16


def enforce_size(data: bytes, *, kind: str) -> bytes:
    """Raise :class:`ReportLimitError` when ``data`` exceeds the export bound."""
    if len(data) > MAX_REPORT_BYTES:
        raise ReportLimitError(
            f"The {kind} export is {len(data)} bytes, above the "
            f"{MAX_REPORT_BYTES}-byte limit. Select fewer sections or tables."
        )
    return data


def stable_zip(files: Sequence[tuple[str, bytes]], *, kind: str = "archive") -> bytes:
    """Build an in-memory ZIP with fixed member timestamps and permissions."""
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, payload in files:
            info = ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = ZIP_MEMBER_MODE
            archive.writestr(info, payload)
    return enforce_size(buffer.getvalue(), kind=kind)


__all__ = ["ZIP_MEMBER_MODE", "ZIP_TIMESTAMP", "enforce_size", "stable_zip"]
