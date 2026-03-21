"""
Input sanitization and validation utilities for MailGuard OSS.

Provides protection against:
- XSS (Cross-Site Scripting) via HTML escaping
- Malicious URLs ("javascript:" scheme, non-HTTP/HTTPS protocols)
- Invalid coordinates (non-integer values)
- Unknown element types (strict enum enforcement)
- Oversized messages (length limits)

Usage
-----
::

    from core.sanitizer import sanitize_text, validate_url, validate_coordinates

    safe = sanitize_text(user_input)
    url  = validate_url(user_submitted_url)
    x, y = validate_coordinates(raw_x, raw_y)
"""
from __future__ import annotations

import html
import re
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TEXT_LENGTH: int = 1_000
MAX_URL_LENGTH: int = 2_048

ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Strict enum of recognised element types (canvas / board elements)
ALLOWED_ELEMENT_TYPES: frozenset[str] = frozenset(
    {"text", "drawing", "image", "link"}
)

# Matches one or more whitespace-only characters
_WHITESPACE_ONLY_RE = re.compile(r"^\s*$")


# ---------------------------------------------------------------------------
# Text sanitization
# ---------------------------------------------------------------------------

def sanitize_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Sanitize *text* for safe storage and display.

    Performs:

    1. Type validation — raises :class:`TypeError` if *text* is not a ``str``.
    2. Length truncation — silently truncates to *max_length* characters.
    3. HTML-entity encoding — converts ``< > & " '`` to their HTML entities
       so that the output is safe to embed inside HTML without further
       escaping.

    This is the server-side counterpart of DOMPurify used on the client.
    Stored data is *always* re-escaped before rendering on the frontend too.

    Parameters
    ----------
    text:
        The raw user-supplied string.
    max_length:
        Maximum number of characters to retain (default ``MAX_TEXT_LENGTH``).

    Returns
    -------
    str
        The sanitized, HTML-escaped string (safe for DB storage and HTML
        embedding).

    Raises
    ------
    TypeError
        If *text* is not a :class:`str`.
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be a str, got {type(text).__name__!r}")
    return html.escape(text[:max_length], quote=True)


def validate_message_length(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Validate that *text* does not exceed *max_length* characters.

    Unlike :func:`sanitize_text`, this function raises an explicit error
    rather than truncating silently, making it suitable for API request
    validation where the caller should be informed about the length violation.

    Raises
    ------
    ValueError
        If *text* exceeds *max_length*.
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be a str, got {type(text).__name__!r}")
    if len(text) > max_length:
        raise ValueError(
            f"Message length {len(text)} exceeds maximum of {max_length} characters"
        )
    return text


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def validate_url(url: str) -> str:
    """Validate a user-supplied URL.

    Accepts only ``http`` and ``https`` URLs with a non-empty host.
    Explicitly rejects ``javascript:``, ``data:``, ``vbscript:``, and any
    other scheme that could lead to XSS or SSRF.

    Parameters
    ----------
    url:
        The raw URL string submitted by the user.

    Returns
    -------
    str
        The stripped, validated URL (scheme preserved as-is).

    Raises
    ------
    TypeError
        If *url* is not a :class:`str`.
    ValueError
        If *url* exceeds ``MAX_URL_LENGTH``, has a disallowed scheme, or
        lacks a valid host.
    """
    if not isinstance(url, str):
        raise TypeError(f"url must be a str, got {type(url).__name__!r}")
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise ValueError(
            f"URL length {len(url)} exceeds maximum of {MAX_URL_LENGTH} characters"
        )
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"URL scheme {scheme!r} is not allowed; "
            f"only {sorted(ALLOWED_URL_SCHEMES)} are permitted"
        )
    if not parsed.netloc:
        raise ValueError("URL must include a valid host (netloc)")
    return url


# ---------------------------------------------------------------------------
# Coordinate validation
# ---------------------------------------------------------------------------

def validate_coordinates(x: object, y: object) -> tuple[int, int]:
    """Validate canvas coordinates, requiring both to be integers.

    Accepts any value that can be losslessly converted to an integer
    (e.g. ``"42"``, ``42``, ``42.0``).  Rejects floats with a fractional
    part (e.g. ``42.5``).

    Parameters
    ----------
    x, y:
        Raw coordinate values from user input.

    Returns
    -------
    tuple[int, int]
        The validated ``(x, y)`` pair as Python integers.

    Raises
    ------
    ValueError
        If either coordinate cannot be converted to a whole integer.
    """
    xi = _to_int(x, "x")
    yi = _to_int(y, "y")
    return xi, yi


def _to_int(value: object, name: str) -> int:
    """Convert *value* to an integer, rejecting non-whole floats."""
    if isinstance(value, bool):
        raise ValueError(f"Coordinate {name!r} must be an integer, got bool")
    if isinstance(value, float):
        if value != int(value):
            raise ValueError(
                f"Coordinate {name!r} must be a whole number, got {value!r}"
            )
        return int(value)
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Coordinate {name!r} must be an integer, got {value!r}"
        ) from exc


# ---------------------------------------------------------------------------
# Element type validation
# ---------------------------------------------------------------------------

def validate_element_type(element_type: str) -> str:
    """Validate *element_type* against the strict allowed-types enum.

    Parameters
    ----------
    element_type:
        The raw element type string submitted by the user.

    Returns
    -------
    str
        The validated element type (identical to the input if valid).

    Raises
    ------
    TypeError
        If *element_type* is not a :class:`str`.
    ValueError
        If *element_type* is not in ``ALLOWED_ELEMENT_TYPES``.
    """
    if not isinstance(element_type, str):
        raise TypeError(
            f"element_type must be a str, got {type(element_type).__name__!r}"
        )
    if element_type not in ALLOWED_ELEMENT_TYPES:
        raise ValueError(
            f"Invalid element type {element_type!r}; "
            f"allowed values: {sorted(ALLOWED_ELEMENT_TYPES)}"
        )
    return element_type
