from secure import Secure
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import uuid
import time

_secure = Secure()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects secure HTTP headers and a unique X-Request-ID on every response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        t = time.monotonic()
        response: Response = await call_next(request)
        _secure.framework.fastapi(response)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time"] = f"{(time.monotonic() - t) * 1000:.1f}ms"
        return response
