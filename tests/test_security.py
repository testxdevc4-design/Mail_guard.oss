"""
tests/test_security.py — Security module tests for MailGuard OSS.

Covers:
  1.  Sanitizer — sanitize_text, validate_message_length, validate_url,
                  validate_coordinates, validate_element_type
  2.  Key hash  — generate_key, hash_key, verify_key
  3.  Identity  — generate_user_id, generate_signature, verify_signature
  4.  File validator — validate_file (size, MIME allowlist, magic bytes)
  5.  Rate limiter new tiers — check_key_verification, check_element_creation,
                               check_reply_creation
  6.  CSRF middleware — accepts / rejects based on X-Requested-With header
  7.  Security headers — Content-Security-Policy header present
"""
from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Env vars must be set before importing any app module
# ---------------------------------------------------------------------------
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "testkey")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("JWT_SECRET", "b" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test:token")
os.environ.setdefault("TELEGRAM_ADMIN_UID", "1")
os.environ.setdefault("ENV", "development")

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from apps.api.middleware.csrf import CSRFProtectionMiddleware  # noqa: E402
from apps.api.middleware.security_headers import SecurityHeadersMiddleware  # noqa: E402
from core.file_validator import (  # noqa: E402
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE,
    validate_file,
)
from core.identity import (  # noqa: E402
    generate_signature,
    generate_user_id,
    verify_signature,
)
from core.key_hash import generate_key, hash_key, verify_key  # noqa: E402
from core.rate_limiter import (  # noqa: E402
    check_element_creation,
    check_key_verification,
    check_reply_creation,
)
from core.sanitizer import (  # noqa: E402
    ALLOWED_ELEMENT_TYPES,
    ALLOWED_URL_SCHEMES,
    MAX_TEXT_LENGTH,
    sanitize_text,
    validate_coordinates,
    validate_element_type,
    validate_message_length,
    validate_url,
)


# ===========================================================================
# 1. INPUT SANITIZATION (core/sanitizer.py)
# ===========================================================================

class TestSanitizeText:
    def test_plain_text_unchanged_content(self) -> None:
        """Safe text (no HTML chars) is returned intact after escaping."""
        result = sanitize_text("Hello, world!")
        assert "Hello" in result
        assert "world" in result

    def test_strips_script_tags(self) -> None:
        """<script> tags must be HTML-escaped, not passed through."""
        result = sanitize_text("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "alert" in result  # text content preserved, tags escaped

    def test_escapes_angle_brackets(self) -> None:
        result = sanitize_text("<b>bold</b>")
        assert "<b>" not in result
        assert "&lt;b&gt;" in result

    def test_escapes_ampersand(self) -> None:
        result = sanitize_text("Tom & Jerry")
        assert "&amp;" in result

    def test_escapes_double_quotes(self) -> None:
        result = sanitize_text('"quoted"')
        assert "&quot;" in result

    def test_escapes_single_quotes(self) -> None:
        result = sanitize_text("it's fine")
        # html.escape with quote=True escapes single quotes as &#x27;
        assert "'" not in result

    def test_truncates_to_max_length(self) -> None:
        long_text = "a" * (MAX_TEXT_LENGTH + 100)
        result = sanitize_text(long_text)
        # After escaping 'a' characters they remain 'a', so len should be MAX
        assert len(result) <= MAX_TEXT_LENGTH

    def test_custom_max_length(self) -> None:
        result = sanitize_text("Hello, world!", max_length=5)
        assert result == "Hello"

    def test_empty_string(self) -> None:
        assert sanitize_text("") == ""

    def test_type_error_on_non_string(self) -> None:
        with pytest.raises(TypeError):
            sanitize_text(123)  # type: ignore[arg-type]

    def test_javascript_url_in_text_is_escaped(self) -> None:
        result = sanitize_text("javascript:alert(1)")
        # 'javascript:' becomes safe plain text after HTML-escaping
        assert "<" not in result
        assert ">" not in result

    def test_iframe_tag_escaped(self) -> None:
        result = sanitize_text('<iframe src="evil.com"></iframe>')
        assert "<iframe" not in result

    def test_inline_event_handler_escaped(self) -> None:
        result = sanitize_text('<img onerror="alert(1)">')
        assert "onerror" in result  # attribute text present but tag escaped
        assert "<img" not in result


class TestValidateMessageLength:
    def test_within_limit_passes(self) -> None:
        text = "a" * MAX_TEXT_LENGTH
        assert validate_message_length(text) == text

    def test_exceeds_limit_raises(self) -> None:
        text = "a" * (MAX_TEXT_LENGTH + 1)
        with pytest.raises(ValueError, match="exceeds maximum"):
            validate_message_length(text)

    def test_custom_limit(self) -> None:
        with pytest.raises(ValueError):
            validate_message_length("hello world", max_length=5)

    def test_type_error_on_non_string(self) -> None:
        with pytest.raises(TypeError):
            validate_message_length(42)  # type: ignore[arg-type]


class TestValidateUrl:
    def test_http_url_accepted(self) -> None:
        url = "http://example.com/path"
        assert validate_url(url) == url

    def test_https_url_accepted(self) -> None:
        url = "https://secure.example.com/resource?q=1"
        assert validate_url(url) == url

    def test_javascript_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            validate_url("javascript:alert(1)")

    def test_data_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            validate_url("data:text/html,<h1>XSS</h1>")

    def test_ftp_scheme_rejected(self) -> None:
        with pytest.raises(ValueError, match="scheme"):
            validate_url("ftp://files.example.com/file.txt")

    def test_url_without_host_rejected(self) -> None:
        with pytest.raises(ValueError, match="host"):
            validate_url("https://")

    def test_url_exceeding_max_length_rejected(self) -> None:
        long_url = "https://example.com/" + "a" * 3000
        with pytest.raises(ValueError, match="length"):
            validate_url(long_url)

    def test_strips_leading_whitespace(self) -> None:
        result = validate_url("  https://example.com  ")
        assert result == "https://example.com"

    def test_type_error_on_non_string(self) -> None:
        with pytest.raises(TypeError):
            validate_url(42)  # type: ignore[arg-type]

    def test_allowed_url_schemes_constant(self) -> None:
        assert "http" in ALLOWED_URL_SCHEMES
        assert "https" in ALLOWED_URL_SCHEMES
        assert "javascript" not in ALLOWED_URL_SCHEMES


class TestValidateCoordinates:
    def test_integer_coords_accepted(self) -> None:
        x, y = validate_coordinates(100, 200)
        assert x == 100
        assert y == 200

    def test_string_integer_coords_accepted(self) -> None:
        x, y = validate_coordinates("42", "99")
        assert x == 42
        assert y == 99

    def test_zero_coords(self) -> None:
        x, y = validate_coordinates(0, 0)
        assert x == 0 and y == 0

    def test_negative_coords_accepted(self) -> None:
        x, y = validate_coordinates(-100, -200)
        assert x == -100 and y == -200

    def test_whole_float_accepted(self) -> None:
        x, y = validate_coordinates(3.0, 4.0)
        assert x == 3 and y == 4

    def test_fractional_float_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_coordinates(3.5, 4)

    def test_non_numeric_x_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_coordinates("abc", 0)

    def test_none_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_coordinates(None, 0)

    def test_bool_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_coordinates(True, 0)  # bool is a subclass of int but misleading


class TestValidateElementType:
    def test_all_allowed_types_accepted(self) -> None:
        for et in ALLOWED_ELEMENT_TYPES:
            assert validate_element_type(et) == et

    def test_text_type(self) -> None:
        assert validate_element_type("text") == "text"

    def test_drawing_type(self) -> None:
        assert validate_element_type("drawing") == "drawing"

    def test_image_type(self) -> None:
        assert validate_element_type("image") == "image"

    def test_link_type(self) -> None:
        assert validate_element_type("link") == "link"

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid element type"):
            validate_element_type("script")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_element_type("")

    def test_uppercase_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_element_type("TEXT")

    def test_type_error_on_non_string(self) -> None:
        with pytest.raises(TypeError):
            validate_element_type(42)  # type: ignore[arg-type]


# ===========================================================================
# 2. KEY HASHING (core/key_hash.py)
# ===========================================================================

class TestKeyHash:
    def test_hash_key_returns_64_char_hex(self) -> None:
        digest = hash_key("my-secret-key")
        assert isinstance(digest, str)
        assert len(digest) == 64
        int(digest, 16)  # raises ValueError if not valid hex

    def test_hash_key_is_deterministic(self) -> None:
        key = "same-key"
        assert hash_key(key) == hash_key(key)

    def test_different_keys_produce_different_hashes(self) -> None:
        assert hash_key("key-A") != hash_key("key-B")

    def test_hash_key_type_error_on_non_string(self) -> None:
        with pytest.raises(TypeError):
            hash_key(12345)  # type: ignore[arg-type]

    def test_verify_key_correct_key_returns_true(self) -> None:
        raw = "my-ownership-key"
        stored = hash_key(raw)
        assert verify_key(raw, stored) is True

    def test_verify_key_wrong_key_returns_false(self) -> None:
        raw = "my-ownership-key"
        stored = hash_key(raw)
        assert verify_key("wrong-key", stored) is False

    def test_verify_key_tampered_hash_returns_false(self) -> None:
        raw = "my-ownership-key"
        stored = hash_key(raw)
        tampered = stored[:-1] + ("0" if stored[-1] != "0" else "1")
        assert verify_key(raw, tampered) is False

    def test_verify_key_non_string_inputs_return_false(self) -> None:
        assert verify_key(None, "abc") is False  # type: ignore[arg-type]
        assert verify_key("key", None) is False  # type: ignore[arg-type]

    def test_generate_key_returns_non_empty_string(self) -> None:
        key = generate_key()
        assert isinstance(key, str)
        assert len(key) > 0

    def test_generate_key_produces_unique_values(self) -> None:
        keys = {generate_key() for _ in range(20)}
        assert len(keys) == 20

    def test_generate_key_custom_length(self) -> None:
        key = generate_key(nbytes=16)
        assert isinstance(key, str)
        # URL-safe base64 of 16 bytes ≈ 22 characters
        assert len(key) >= 16

    def test_raw_key_not_equal_to_hash(self) -> None:
        """Stored hash must never equal the raw key."""
        raw = generate_key()
        assert raw != hash_key(raw)


# ===========================================================================
# 3. IDENTITY SIGNATURES (core/identity.py)
# ===========================================================================

class TestIdentity:
    def test_generate_user_id_returns_non_empty_string(self) -> None:
        uid = generate_user_id()
        assert isinstance(uid, str)
        assert len(uid) > 0

    def test_generate_user_id_is_unique(self) -> None:
        uids = {generate_user_id() for _ in range(20)}
        assert len(uids) == 20

    def test_generate_signature_returns_64_char_hex(self) -> None:
        sig = generate_signature("user123")
        assert isinstance(sig, str)
        assert len(sig) == 64
        int(sig, 16)  # raises if not valid hex

    def test_generate_signature_is_deterministic(self) -> None:
        uid = "stable-user-id"
        assert generate_signature(uid) == generate_signature(uid)

    def test_different_user_ids_produce_different_sigs(self) -> None:
        assert generate_signature("user-A") != generate_signature("user-B")

    def test_generate_signature_type_error_on_non_string(self) -> None:
        with pytest.raises(TypeError):
            generate_signature(42)  # type: ignore[arg-type]

    def test_verify_signature_correct_sig_returns_true(self) -> None:
        uid = generate_user_id()
        sig = generate_signature(uid)
        assert verify_signature(uid, sig) is True

    def test_verify_signature_wrong_sig_returns_false(self) -> None:
        uid = generate_user_id()
        _ = generate_signature(uid)
        assert verify_signature(uid, "wrong-sig") is False

    def test_verify_signature_wrong_uid_returns_false(self) -> None:
        uid = generate_user_id()
        sig = generate_signature(uid)
        assert verify_signature("different-uid", sig) is False

    def test_verify_signature_non_string_inputs_return_false(self) -> None:
        assert verify_signature(None, "sig") is False  # type: ignore[arg-type]
        assert verify_signature("uid", None) is False  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        uid = generate_user_id()
        sig = generate_signature(uid)
        assert verify_signature(uid, sig) is True


# ===========================================================================
# 4. FILE UPLOAD VALIDATION (core/file_validator.py)
# ===========================================================================

# Minimal valid magic-byte prefixes for each allowed type
_JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 10
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
_GIF87_BYTES = b"GIF87a" + b"\x00" * 10
_GIF89_BYTES = b"GIF89a" + b"\x00" * 10
_WEBP_BYTES = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 10


class TestFileValidator:
    def test_valid_jpeg_accepted(self) -> None:
        mime = validate_file(_JPEG_BYTES, "image/jpeg")
        assert mime == "image/jpeg"

    def test_valid_png_accepted(self) -> None:
        mime = validate_file(_PNG_BYTES, "image/png")
        assert mime == "image/png"

    def test_valid_gif87_accepted(self) -> None:
        mime = validate_file(_GIF87_BYTES, "image/gif")
        assert mime == "image/gif"

    def test_valid_gif89_accepted(self) -> None:
        mime = validate_file(_GIF89_BYTES, "image/gif")
        assert mime == "image/gif"

    def test_valid_webp_accepted(self) -> None:
        mime = validate_file(_WEBP_BYTES, "image/webp")
        assert mime == "image/webp"

    def test_empty_file_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_file(b"", "image/jpeg")

    def test_file_exceeding_max_size_rejected(self) -> None:
        oversized = b"\xff\xd8\xff" + b"\x00" * (MAX_FILE_SIZE + 1)
        with pytest.raises(ValueError, match="exceeds"):
            validate_file(oversized, "image/jpeg")

    def test_custom_max_size_respected(self) -> None:
        data = _JPEG_BYTES
        with pytest.raises(ValueError, match="exceeds"):
            validate_file(data, "image/jpeg", max_size=5)

    def test_disallowed_mime_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            validate_file(_JPEG_BYTES, "application/pdf")

    def test_executable_mime_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            validate_file(b"\x4d\x5a" + b"\x00" * 10, "application/octet-stream")

    def test_text_html_mime_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            validate_file(b"<html>", "text/html")

    def test_mime_type_parameter_stripped(self) -> None:
        """MIME types with parameters like '; charset=utf-8' must still work."""
        mime = validate_file(_JPEG_BYTES, "image/jpeg; charset=utf-8")
        assert mime == "image/jpeg"

    def test_magic_bytes_mismatch_rejected(self) -> None:
        """Declare PNG but provide JPEG bytes → rejected."""
        with pytest.raises(ValueError, match="does not match"):
            validate_file(_JPEG_BYTES, "image/png")

    def test_magic_bytes_mismatch_gif_declared_as_png(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            validate_file(_GIF89_BYTES, "image/png")

    def test_allowed_mime_types_constant_contains_expected(self) -> None:
        for expected in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            assert expected in ALLOWED_MIME_TYPES

    def test_type_error_on_non_bytes_content(self) -> None:
        with pytest.raises(TypeError):
            validate_file("not bytes", "image/jpeg")  # type: ignore[arg-type]

    def test_type_error_on_non_string_mime(self) -> None:
        with pytest.raises(TypeError):
            validate_file(_JPEG_BYTES, 42)  # type: ignore[arg-type]


# ===========================================================================
# 5. RATE LIMITER — new board/element tiers
# ===========================================================================

class _FakePipeline:
    """Minimal Redis pipeline mock for sorted-set operations."""

    def __init__(self, store: "_FakeRedis") -> None:
        self._store = store
        self._cmds: list[tuple] = []

    def zremrangebyscore(self, key: str, min_score: object, max_score: float) -> "_FakePipeline":
        self._cmds.append(("zremrangebyscore", key, min_score, max_score))
        return self

    def zadd(self, key: str, mapping: dict) -> "_FakePipeline":
        self._cmds.append(("zadd", key, mapping))
        return self

    def zcard(self, key: str) -> "_FakePipeline":
        self._cmds.append(("zcard", key))
        return self

    def expire(self, key: str, seconds: int) -> "_FakePipeline":
        self._cmds.append(("expire", key, seconds))
        return self

    def execute(self) -> list:
        results: list = []
        for cmd in self._cmds:
            op = cmd[0]
            if op == "zremrangebyscore":
                _, key, min_s, max_s = cmd
                zset = self._store._zsets.setdefault(key, {})
                lo = float("-inf") if min_s == "-inf" else float(min_s)
                hi = float(max_s)
                removed = [m for m, s in list(zset.items()) if lo <= s <= hi]
                for m in removed:
                    del zset[m]
                results.append(len(removed))
            elif op == "zadd":
                _, key, mapping = cmd
                zset = self._store._zsets.setdefault(key, {})
                for member, score in mapping.items():
                    zset[member] = score
                results.append(len(mapping))
            elif op == "zcard":
                _, key = cmd
                results.append(len(self._store._zsets.get(key, {})))
            elif op == "expire":
                results.append(1)
        return results

    def __enter__(self) -> "_FakePipeline":
        return self

    def __exit__(self, *_: object) -> None:
        pass


class _FakeRedis:
    def __init__(self) -> None:
        self._zsets: dict[str, dict[str, float]] = {}

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self)


@pytest.fixture()
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


class TestKeyVerificationRateLimit:
    def test_allows_up_to_limit(self, fake_redis: _FakeRedis) -> None:
        for _ in range(5):
            assert check_key_verification(fake_redis, "elem-1") is True

    def test_blocks_at_limit_plus_one(self, fake_redis: _FakeRedis) -> None:
        for _ in range(5):
            check_key_verification(fake_redis, "elem-2")
        assert check_key_verification(fake_redis, "elem-2") is False

    def test_different_elements_are_isolated(self, fake_redis: _FakeRedis) -> None:
        for _ in range(6):
            check_key_verification(fake_redis, "elem-A")
        # elem-B is a separate window
        assert check_key_verification(fake_redis, "elem-B") is True


class TestElementCreationRateLimit:
    def test_allows_up_to_limit(self, fake_redis: _FakeRedis) -> None:
        for _ in range(20):
            assert check_element_creation(fake_redis, "user-X") is True

    def test_blocks_at_limit_plus_one(self, fake_redis: _FakeRedis) -> None:
        for _ in range(20):
            check_element_creation(fake_redis, "user-Y")
        assert check_element_creation(fake_redis, "user-Y") is False

    def test_different_users_isolated(self, fake_redis: _FakeRedis) -> None:
        for _ in range(21):
            check_element_creation(fake_redis, "user-Z1")
        assert check_element_creation(fake_redis, "user-Z2") is True


class TestReplyCreationRateLimit:
    def test_allows_up_to_limit(self, fake_redis: _FakeRedis) -> None:
        for _ in range(10):
            assert check_reply_creation(fake_redis, "user-R1") is True

    def test_blocks_at_limit_plus_one(self, fake_redis: _FakeRedis) -> None:
        for _ in range(10):
            check_reply_creation(fake_redis, "user-R2")
        assert check_reply_creation(fake_redis, "user-R2") is False

    def test_different_users_isolated(self, fake_redis: _FakeRedis) -> None:
        for _ in range(11):
            check_reply_creation(fake_redis, "user-R3")
        assert check_reply_creation(fake_redis, "user-R4") is True


# ===========================================================================
# 6. CSRF MIDDLEWARE (apps/api/middleware/csrf.py)
# ===========================================================================

def _make_csrf_app() -> FastAPI:
    csrf_app = FastAPI()
    csrf_app.add_middleware(CSRFProtectionMiddleware)

    @csrf_app.get("/read")
    async def read_route():
        return {"ok": True}

    @csrf_app.post("/write")
    async def write_route():
        return {"ok": True}

    @csrf_app.post("/auth-write")
    async def auth_write_route():
        return {"ok": True}

    return csrf_app


@pytest.mark.asyncio
async def test_csrf_get_request_always_allowed() -> None:
    """GET requests are always allowed regardless of X-Requested-With."""
    app = _make_csrf_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/read")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_csrf_post_without_header_rejected() -> None:
    """POST without X-Requested-With and without Authorization → 403."""
    app = _make_csrf_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/write")
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "csrf_validation_failed"


@pytest.mark.asyncio
async def test_csrf_post_with_correct_header_allowed() -> None:
    """POST with X-Requested-With: XMLHttpRequest → allowed."""
    app = _make_csrf_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/write", headers={"X-Requested-With": "XMLHttpRequest"})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_csrf_post_with_wrong_header_value_rejected() -> None:
    """POST with incorrect X-Requested-With value → 403."""
    app = _make_csrf_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/write", headers={"X-Requested-With": "fetch"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_csrf_post_with_authorization_header_exempt() -> None:
    """POST with Authorization header is exempt from X-Requested-With check."""
    app = _make_csrf_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            "/auth-write",
            headers={"Authorization": "Bearer some-token"},
        )
        # Route returns 200 (CSRF check is skipped for Bearer-auth requests)
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_csrf_error_body_is_json() -> None:
    """CSRF rejection must return a valid JSON error body."""
    app = _make_csrf_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/write")
        assert r.headers.get("content-type", "").startswith("application/json")
        body = r.json()
        assert "detail" in body


# ===========================================================================
# 7. SECURITY HEADERS — Content-Security-Policy
# ===========================================================================

def _make_sec_headers_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ok")
    async def ok_route():
        return {"ok": True}

    @app.get("/error")
    async def error_route():
        return JSONResponse(status_code=500, content={"error": "internal"})

    return app


@pytest.mark.asyncio
async def test_content_security_policy_header_present() -> None:
    """Every response must include a Content-Security-Policy header."""
    app = _make_sec_headers_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/ok")
        assert r.status_code == 200
        csp = r.headers.get("content-security-policy", "")
        assert csp != "", "CSP header must not be empty"
        assert "default-src" in csp
        assert "object-src 'none'" in csp


@pytest.mark.asyncio
async def test_csp_blocks_inline_scripts() -> None:
    """CSP must not allow 'unsafe-inline' in script-src."""
    app = _make_sec_headers_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/ok")
        csp = r.headers.get("content-security-policy", "")
        assert "unsafe-inline" not in csp


@pytest.mark.asyncio
async def test_csp_on_error_response() -> None:
    """CSP header must also be present on error (5xx) responses."""
    app = _make_sec_headers_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/error")
        assert r.status_code == 500
        assert "content-security-policy" in r.headers


@pytest.mark.asyncio
async def test_all_existing_security_headers_still_present() -> None:
    """Adding CSP must not remove the other four security headers."""
    app = _make_sec_headers_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/ok")
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "SAMEORIGIN"
        assert "strict-transport-security" in r.headers
        assert "x-xss-protection" in r.headers
