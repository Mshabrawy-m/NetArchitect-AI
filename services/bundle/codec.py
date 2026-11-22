"""Hostile-input-safe ZIP and JSON helpers for project bundles (B1).

Every member name is checked against a fixed allowlist before it is opened, so
path traversal, absolute paths, backslashes, symlinks, and extra files are
rejected. Sizes, member counts, and decompression ratios are bounded before any
payload is read into memory. JSON is decoded with the guarded parser and a
SHA-256 checksum from the manifest is verified for every member.
"""

from __future__ import annotations

import hashlib
import io
import stat
from collections.abc import Mapping
from typing import Any
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from config.limits import MAX_BUNDLE_BYTES, MAX_BUNDLE_MEMBERS, MAX_INPUT_BYTES
from core.exceptions import InputError
from core.inputs import parse_json_text

from .errors import (
    BundleChecksumError,
    BundleFormatError,
    BundleLimitError,
    BundlePathError,
)
from .models import (
    DECISIONS_MEMBER,
    FLOWS_MEMBER,
    MANIFEST_MEMBER,
    SECTION_DIRECTORIES,
    SETTINGS_MEMBER,
    TWIN_MEMBER,
)

_EXACT_MEMBERS: frozenset[str] = frozenset(
    {
        MANIFEST_MEMBER,
        TWIN_MEMBER,
        DECISIONS_MEMBER,
        FLOWS_MEMBER,
        SETTINGS_MEMBER,
    }
)
_MAX_DECOMPRESSION_RATIO = 200
_RATIO_CHECK_MIN_BYTES = 100_000

# A fixed ZIP timestamp and mode make a bundle byte-identical for the same data.
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ZIP_MODE = 0o600 << 16


def is_safe_member(name: str) -> bool:
    """Return whether ``name`` is one of the fixed bundle member paths."""
    if not name or "\x00" in name or "\\" in name:
        return False
    if name.startswith(("/", "./")):
        return False
    if name.endswith("/"):
        return False
    if any(part in {"", ".", ".."} for part in name.split("/")):
        return False
    if name in _EXACT_MEMBERS:
        return True
    for directory in SECTION_DIRECTORIES:
        if name.startswith(directory):
            tail = name[len(directory) :]
            if not tail.endswith(".json") or len(tail) > 12:
                return False
            stem = tail[:-5]
            return bool(stem) and stem.isdigit() and len(stem) <= 6
    return False


def _check_info(info: ZipInfo) -> None:
    if info.is_dir():
        raise BundlePathError("Bundle archives may not contain directory entries.")
    if info.flag_bits & 0x1:
        raise BundleFormatError("Encrypted bundle members are not supported.")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode) or stat.S_ISDIR(mode) or stat.S_ISCHR(mode):
        raise BundlePathError("Bundle archives may not contain special members.")
    if info.file_size > MAX_INPUT_BYTES:
        raise BundleLimitError(
            f"A bundle member is {info.file_size} bytes, above the "
            f"{MAX_INPUT_BYTES}-byte per-member limit."
        )
    if info.compress_size < 0 or info.file_size < 0:
        raise BundleFormatError("Bundle member has an invalid size header.")
    if (
        info.file_size > _RATIO_CHECK_MIN_BYTES
        and info.compress_size > 0
        and info.file_size // info.compress_size > _MAX_DECOMPRESSION_RATIO
    ):
        raise BundleLimitError("A bundle member has an implausible compression ratio.")


def read_archive(payload: bytes) -> dict[str, bytes]:
    """Validate and read all ZIP members into a bounded in-memory mapping."""
    if not isinstance(payload, (bytes, bytearray)):
        raise BundleFormatError("Bundle payload must be bytes.")
    data = bytes(payload)
    if not data or len(data) > MAX_BUNDLE_BYTES:
        raise BundleLimitError(
            f"Bundle is {len(data)} bytes; the limit is {MAX_BUNDLE_BYTES} bytes."
        )
    members: dict[str, bytes] = {}
    total = 0
    try:
        with ZipFile(io.BytesIO(data), "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_BUNDLE_MEMBERS:
                raise BundleLimitError(
                    f"Bundle has {len(infos)} members; the limit is "
                    f"{MAX_BUNDLE_MEMBERS}."
                )
            for info in infos:
                if not is_safe_member(info.filename):
                    raise BundlePathError("Bundle contains an unsafe member path.")
                _check_info(info)
                if info.filename in members:
                    raise BundleFormatError("Bundle contains duplicate member names.")
                total += info.file_size
                if total > MAX_BUNDLE_BYTES:
                    raise BundleLimitError("Bundle uncompressed size exceeds the limit.")
                members[info.filename] = archive.read(info)
    except BundleFormatError:
        raise
    except (OSError, ValueError, RuntimeError, EOFError, BadZipFile) as error:
        raise BundleFormatError("Bundle is not a readable ZIP archive.") from error
    if MANIFEST_MEMBER not in members:
        raise BundleFormatError("Bundle is missing manifest.json.")
    return members


def decode_json(payload: bytes, *, label: str) -> Any:
    """Decode one guarded JSON member."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BundleFormatError(f"{label} is not valid UTF-8.") from error
    try:
        return parse_json_text(text, label=label)
    except InputError as error:
        raise BundleFormatError(f"{label} failed guarded parsing: {error}") from error


def verify_checksums(
    members: Mapping[str, bytes], declared: Mapping[str, str]
) -> None:
    """Verify declared SHA-256 checksums and reject unexpected members.

    Older v1 manifests have no checksum map; those are accepted by path and size
    guards alone. A present map must describe exactly the non-manifest members.
    """
    if not declared:
        return
    expected = set(declared) | {MANIFEST_MEMBER}
    actual = set(members)
    if actual != expected:
        raise BundleChecksumError("Bundle member list does not match its manifest.")
    for name, digest in declared.items():
        payload = members.get(name)
        if payload is None:
            raise BundleChecksumError("A declared bundle member is missing.")
        if not isinstance(digest, str) or len(digest) != 64:
            raise BundleChecksumError("A declared checksum is malformed.")
        actual_digest = hashlib.sha256(payload).hexdigest()
        if actual_digest != digest:
            raise BundleChecksumError("A bundle member failed its checksum check.")


def digest(payload: bytes) -> str:
    """Return the SHA-256 hex digest of one member payload."""
    return hashlib.sha256(payload).hexdigest()


def build_archive(members: Mapping[str, bytes]) -> bytes:
    """Build a deterministic in-memory ZIP from a mapping of members."""
    names = sorted(members)
    if len(names) > MAX_BUNDLE_MEMBERS:
        raise BundleLimitError("Bundle has too many members.")
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name in names:
            if not is_safe_member(name):
                raise BundlePathError("Refusing to write an unsafe bundle member path.")
            payload = members[name]
            if len(payload) > MAX_INPUT_BYTES:
                raise BundleLimitError("A bundle member exceeds the per-member limit.")
            info = ZipInfo(name, date_time=_ZIP_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = _ZIP_MODE
            archive.writestr(info, payload)
    result = buffer.getvalue()
    if len(result) > MAX_BUNDLE_BYTES:
        raise BundleLimitError("Bundle exceeds the serialized size limit.")
    return result


__all__ = [
    "build_archive",
    "decode_json",
    "digest",
    "is_safe_member",
    "read_archive",
    "verify_checksums",
]
