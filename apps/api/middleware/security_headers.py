"""
Explicit security-header middleware for MailGuard OSS.

Adds the four mandatory security headers to every response — including
error responses — so that no route can accidentally serve a response
without them.

Headers added
-------------
``X-Content-Type-Options``     nosniff
``X-Frame-Options``            SAMEORIGIN
``Strict-Transport-Security``  max-age=63072000; includeSubDomains
``X-XSS-Protection``           0  (modern browsers: disable legacy XSS filter)

Usage
-----
This module provides a standalone middleware that explicitly sets the
four required security headers.  The main application uses the ``secure``
library via ``apps.api.middleware.security`` for a broader set of headers;
this module is available for direct use in tests and alternative setups.
"""
from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-XSS-Protection": "0",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects the four mandatory security headers on every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response: Response = await call_next(request)
        for header, value in _HEADERS.items():
            response.headers[header] = value
        return response
