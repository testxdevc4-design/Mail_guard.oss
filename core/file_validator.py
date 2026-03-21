"""
File upload validation for MailGuard OSS.

Provides defence-in-depth for image uploads:

1. **Size check** — rejects files exceeding ``MAX_FILE_SIZE`` (10 MB).
2. **MIME allowlist** — only the four safe image MIME types are accepted.
3. **Magic-bytes validation** — compares the file's leading bytes to known
   file signatures so that a malicious actor cannot bypass the check by
   simply declaring a safe MIME type for a dangerous file.

No executable or document formats are permitted.

Usage
-----
::

    from core.file_validator import validate_file

    mime = validate_file(raw_bytes, declared_mime="image/png")
    # Returns the validated MIME type or raises ValueError
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB in bytes

# ---------------------------------------------------------------------------
# MIME type → magic byte signatures mapping
#
# Each entry maps a normalised MIME type string to a list of byte-string
# prefixes that are considered valid for that type.  A file is accepted if
# its leading bytes start with *any* of the listed signatures.
# ---------------------------------------------------------------------------

_MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    # WebP files always begin with "RIFF" followed by 4 size bytes then "WEBP"
    "image/webp": [b"RIFF"],
}

# Public frozenset for import by other modules
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(_MAGIC_BYTES.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_file(
    content: bytes,
    declared_mime: str,
    *,
    max_size: int = MAX_FILE_SIZE,
) -> str:
    """Validate an uploaded file.

    Performs three sequential checks:

    1. **Size** — ``len(content) <= max_size``.
    2. **MIME allowlist** — ``declared_mime`` (after stripping parameters such
       as ``;charset=utf-8``) must be in ``ALLOWED_MIME_TYPES``.
    3. **Magic bytes** — the file's actual leading bytes must match the known
       signature for the declared MIME type.

    Parameters
    ----------
    content:
        Raw bytes of the uploaded file.
    declared_mime:
        MIME type as reported by the HTTP client (e.g.
        ``"image/png"`` or ``"image/png; charset=utf-8"``).
    max_size:
        Maximum allowed file size in bytes (default ``MAX_FILE_SIZE``).

    Returns
    -------
    str
        The validated, normalised MIME type (parameters stripped, lower-cased).

    Raises
    ------
    TypeError
        If *content* is not :class:`bytes` or *declared_mime* is not
        :class:`str`.
    ValueError
        If any security check fails.  The error message describes which check
        failed.
    """
    if not isinstance(content, bytes):
        raise TypeError(f"content must be bytes, got {type(content).__name__!r}")
    if not isinstance(declared_mime, str):
        raise TypeError(
            f"declared_mime must be a str, got {type(declared_mime).__name__!r}"
        )

    # 1. Size check
    if len(content) == 0:
        raise ValueError("File must not be empty")
    if len(content) > max_size:
        raise ValueError(
            f"File size {len(content):,} bytes exceeds maximum of "
            f"{max_size:,} bytes ({max_size // (1024 * 1024)} MB)"
        )

    # 2. MIME allowlist — strip optional parameters (e.g. "; charset=utf-8")
    normalised_mime = declared_mime.split(";")[0].strip().lower()
    if normalised_mime not in ALLOWED_MIME_TYPES:
        raise ValueError(
            f"MIME type {normalised_mime!r} is not allowed; "
            f"permitted types: {sorted(ALLOWED_MIME_TYPES)}"
        )

    # 3. Magic-bytes validation
    if not _check_magic_bytes(content, normalised_mime):
        raise ValueError(
            f"File content does not match declared MIME type {normalised_mime!r}; "
            "the file may be corrupt or misidentified"
        )

    return normalised_mime


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_magic_bytes(content: bytes, mime_type: str) -> bool:
    """Return ``True`` if *content* starts with a known signature for *mime_type*."""
    signatures = _MAGIC_BYTES.get(mime_type, [])
    return any(content[: len(sig)] == sig for sig in signatures)
