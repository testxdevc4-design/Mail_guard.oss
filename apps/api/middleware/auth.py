"""
API key authentication dependency for MailGuard OSS.

Usage
-----
::

    from apps.api.middleware.auth import require_api_key
    from core.models import ApiKey
    from fastapi import Depends

    @router.post("/send-otp")
    async def send_otp(key_row: ApiKey = Depends(require_api_key)):
        ...

The dependency extracts the Bearer token from the ``Authorization`` header,
passes it to ``validate_api_key()``, and returns the resolved ``ApiKey`` row.

Error responses
---------------
* ``401 missing_authorization``  — ``Authorization`` header absent or malformed
* ``403 sandbox_key_in_production`` — ``mg_test_`` key used in production
* ``401 invalid_api_key``       — hash not found in the database
* ``401 revoked_api_key``       — key found but ``is_active=False``
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.api_keys import validate_api_key
from core.models import ApiKey

_bearer = HTTPBearer(auto_error=False)


async def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiKey:
    """FastAPI dependency that validates a Bearer API key.

    Returns the ``ApiKey`` database row on success.

    Raises ``HTTPException(401)`` if the ``Authorization`` header is missing
    or does not contain a valid ``Bearer`` token.

    Raises ``HTTPException(403)`` or ``HTTPException(401)`` via
    :func:`core.api_keys.validate_api_key` for key-level failures.
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "missing_authorization"},
        )

    return validate_api_key(credentials.credentials)
