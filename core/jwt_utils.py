"""
JWT issuance and verification for MailGuard OSS.

Every token carries a unique ``jti`` (JWT ID) generated with
``secrets.token_hex(16)``.  This enables individual-token revocation without
invalidating all tokens.

Revocation uses Redis: a revoked ``jti`` is stored as the key
``jti_blacklist:{jti}`` with an expiry equal to the token's remaining lifetime,
so blacklist entries self-clean when the token would have expired anyway.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt

from core.config import settings

UTC = timezone.utc
ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Issue
# ---------------------------------------------------------------------------

def issue_jwt(
    subject: str,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Issue a signed HS256 JWT.

    The payload includes:

    - ``sub`` — the subject (e.g. email_hash)
    - ``jti`` — ``secrets.token_hex(16)``; unique per token, enables revocation
    - ``iat`` — issued-at timestamp (UTC)
    - ``exp`` — expiry timestamp (UTC, ``JWT_EXPIRY_MINUTES`` from now)

    Any additional claims passed via *extra_claims* are merged into the payload.
    """
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=settings.JWT_EXPIRY_MINUTES)
    payload: Dict[str, Any] = {
        "sub": subject,
        "jti": secrets.token_hex(16),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def verify_jwt(
    token: str,
    redis_client: Any = None,
) -> Dict[str, Any]:
    """Decode and verify *token*.

    Raises :class:`ValueError` on any failure:

    - Expired token
    - Invalid/tampered signature
    - Revoked ``jti`` (checked when *redis_client* is provided)

    Returns the decoded payload dict on success.
    """
    try:
        payload: Dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[ALGORITHM],
        )
    except JWTError as exc:
        raise ValueError(f"Invalid JWT: {exc}") from exc

    if redis_client is not None:
        jti = payload.get("jti")
        if jti:
            revoked = redis_client.get(f"jti_blacklist:{jti}")
            if revoked:
                raise ValueError("JWT has been revoked")

    return payload


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------

def revoke_jwt(token: str, redis_client: Any) -> None:
    """Add *token*'s ``jti`` to the Redis blacklist.

    The blacklist key expires when the token's natural lifetime ends, so no
    periodic cleanup is required.

    Decoding is performed without expiry verification so that already-expired
    tokens can still be explicitly revoked (belt-and-suspenders).
    """
    try:
        payload: Dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )
    except JWTError as exc:
        raise ValueError(f"Cannot revoke malformed JWT: {exc}") from exc

    jti = payload.get("jti")
    if not jti:
        return

    exp = payload.get("exp", 0)
    ttl = max(1, int(exp - datetime.now(UTC).timestamp()))
    redis_client.set(f"jti_blacklist:{jti}", "1", ex=ttl)
