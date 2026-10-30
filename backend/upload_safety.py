"""Small, dependency-free upload boundary shared by local API routes.

The prototype stores evidence locally, so callers must not be allowed to turn a
base64 field into an unbounded allocation or a malformed media-type value.
This module deliberately validates transport safety only; it does not claim
malware scanning or independent document authenticity.
"""
from __future__ import annotations

import base64
import binascii
import os
import re


class UploadSafetyError(ValueError):
    """A client-upload value is unsafe or outside the documented local limits."""


_MEDIA_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*(?:;[A-Za-z0-9!#$&^_.+-]+=[A-Za-z0-9!#$&^_.+-]+)*$")


def max_upload_bytes() -> int:
    raw = os.environ.get("PRAMAAN_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("PRAMAAN_MAX_UPLOAD_BYTES must be a positive integer") from exc
    if value < 1:
        raise RuntimeError("PRAMAAN_MAX_UPLOAD_BYTES must be a positive integer")
    return value


def decode_base64(value: str, *, label: str, limit: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise UploadSafetyError(f"{label} must be base64 text")
    size_limit = max_upload_bytes() if limit is None else limit
    # A base64 payload needs at least four encoded characters for every three
    # decoded bytes. Reject oversized input before allocating decoded content.
    if len(value) > ((size_limit + 2) // 3) * 4:
        raise UploadSafetyError(f"{label} exceeds the configured upload limit")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UploadSafetyError(f"{label} must be valid base64") from exc
    if len(decoded) > size_limit:
        raise UploadSafetyError(f"{label} exceeds the configured upload limit")
    return decoded


def content_type(value: str) -> str:
    if not isinstance(value, str) or not _MEDIA_TYPE.fullmatch(value):
        raise UploadSafetyError("content type must be a valid media type")
    return value.lower()
