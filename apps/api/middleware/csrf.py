"""
CSRF protection middleware for MailGuard OSS.

Enforces the presence of the ``X-Requested-With: XMLHttpRequest`` custom
header on mutating HTTP requests (POST, PUT, PATCH, DELETE).

Why this helps
--------------
Browsers block cross-origin requests from setting custom headers unless the
server explicitly permits them via CORS ``Access-Control-Allow-Headers``.
Therefore, a legitimate same-origin AJAX request can include
``X-Requested-With: XMLHttpRequest`` while a cross-site forged form
submission or image-tag attack cannot.

Exemptions
----------
Requests that already carry an ``Authorization`` header are **exempt** from
this check.  Bearer-token authentication provides an equivalent level of
CSRF protection because:

- Cross-origin scripts cannot read ``localStorage`` or cookies from another
  origin.
- The ``Authorization`` header itself is a custom header — the same
  cross-origin restriction applies — so a CSRF attacker cannot set it.

This exemption preserves backwards compatibility with existing API clients
that authenticate via Bearer token.

Usage
-----
Register the middleware in the FastAPI application factory::

    from apps.api.middleware.csrf import CSRFProtectionMiddleware
    app.add_middleware(CSRFProtectionMiddleware)

For routes that use Bearer-token authentication the middleware is a no-op.
For browser-facing endpoints (no Authorization header) the custom header is
required on every state-changing request.
"""
from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# HTTP methods that do not change server state — exempt from CSRF check
_SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

_CSRF_HEADER: str = "X-Requested-With"
_CSRF_VALUE: str = "XMLHttpRequest"


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """Validates ``X-Requested-With: XMLHttpRequest`` on mutating requests.

    Returns ``HTTP 403`` with a JSON error body when the check fails.
    Requests with an ``Authorization`` header are exempt (Bearer-token auth
    already prevents CSRF).
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method not in _SAFE_METHODS:
            # Requests with Bearer auth are already CSRF-protected
            if "authorization" not in request.headers:
                header_value = request.headers.get(_CSRF_HEADER, "")
                if header_value != _CSRF_VALUE:
                    return Response(
                        content=(
                            '{"error":"csrf_validation_failed",'
                            '"detail":"X-Requested-With: XMLHttpRequest header is required"}'
                        ),
                        status_code=403,
                        headers={"Content-Type": "application/json"},
                    )
        return await call_next(request)
