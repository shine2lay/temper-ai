"""Tests for temper_ai/auth/api_key_auth.py — API key authentication."""

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request

from temper_ai.auth.api_key_auth import (
    API_KEY_TOKEN_PREFIX,
    AuthContext,
    _extract_bearer_token,
    authenticate_ws_token,
    generate_api_key,
    hash_api_key,
    require_auth,
    require_role,
)

# ── Fixtures ─────────────────────────────────────────────────────────


def _make_request(headers: dict, path: str = "/api/workflows") -> Request:
    """Build a minimal Starlette Request with the given headers and path."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": Headers(headers=headers).raw,
    }
    return Request(scope)


def _make_valid_lookup_result(
    *,
    is_active: bool = True,
    expires_at: datetime | None = None,
    role: str = "owner",
) -> dict:
    return {
        "api_key_id": "key-id-123",
        "user_id": "user-id-456",
        "tenant_id": "tenant-id-789",
        "is_active": is_active,
        "expires_at": expires_at,
        "role": role,
    }


# ── generate_api_key ─────────────────────────────────────────────────


def test_generate_api_key_starts_with_prefix():
    full_key, _, _ = generate_api_key()
    assert full_key.startswith("tk_")


def test_generate_api_key_prefix_display_length():
    full_key, key_prefix, _ = generate_api_key()
    # prefix stored = "tk_" (3 chars) + 8 display chars = 11
    assert len(key_prefix) == len(API_KEY_TOKEN_PREFIX) + 8
    assert full_key.startswith(key_prefix)


def test_generate_api_key_hash_length():
    """Key hash must be a 64-char hex digest (SHA-256 or HMAC-SHA256)."""
    _, _, key_hash = generate_api_key()
    assert len(key_hash) == 64  # SHA-256 hex digest length


def test_generate_api_key_uniqueness():
    k1, _, _ = generate_api_key()
    k2, _, _ = generate_api_key()
    assert k1 != k2


# ── hash_api_key ─────────────────────────────────────────────────────


def test_hash_api_key_deterministic():
    raw = "tk_somesecretvalue"
    assert hash_api_key(raw) == hash_api_key(raw)


def test_hash_api_key_sha256_output_dev_mode():
    """Without TEMPER_API_KEY_PEPPER set, falls back to plain SHA-256."""
    import os

    raw = "tk_abc123"
    # In test environment, pepper is not set so plain SHA-256 is used
    if not os.environ.get("TEMPER_API_KEY_PEPPER"):
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert hash_api_key(raw) == expected
    else:
        # With pepper, output differs from plain SHA-256 but is still 64 chars
        assert len(hash_api_key(raw)) == 64


def test_hash_api_key_different_inputs_differ():
    assert hash_api_key("tk_aaa") != hash_api_key("tk_bbb")


# ── _extract_bearer_token ─────────────────────────────────────────────


def test_extract_bearer_token_valid():
    token = "tk_abc123456789"
    req = _make_request({"Authorization": f"Bearer {token}"})
    assert _extract_bearer_token(req) == token


def test_extract_bearer_token_missing():
    req = _make_request({})
    assert _extract_bearer_token(req) is None


def test_extract_bearer_token_wrong_scheme():
    req = _make_request({"Authorization": "Basic dXNlcjpwYXNz"})
    assert _extract_bearer_token(req) is None


def test_extract_bearer_token_empty_authorization():
    req = _make_request({"Authorization": ""})
    assert _extract_bearer_token(req) is None


# ── require_auth — bypass paths ───────────────────────────────────────


@pytest.mark.asyncio
async def test_require_auth_no_bypass_for_health():
    """Health path is a public route — it should not declare Depends(require_auth).
    If called directly without a token, require_auth raises 401 (no bypass path logic).
    """
    from fastapi import HTTPException

    req = _make_request({}, path="/api/health")
    with pytest.raises(HTTPException) as exc_info:
        await require_auth(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_auth_no_bypass_for_signup():
    """Signup is a public route — it should not declare Depends(require_auth).
    If called directly without a token, require_auth raises 401 (no bypass path logic).
    """
    from fastapi import HTTPException

    req = _make_request({}, path="/api/auth/signup")
    with pytest.raises(HTTPException) as exc_info:
        await require_auth(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_auth_rejects_websocket_upgrade():
    """WebSocket upgrades without a Bearer token get 401 — no anonymous bypass."""
    req = _make_request({"upgrade": "websocket"}, path="/ws")
    with pytest.raises(HTTPException) as exc_info:
        await require_auth(req)
    assert exc_info.value.status_code == 401


# ── require_auth — failures ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_auth_missing_header():
    req = _make_request({})
    with pytest.raises(HTTPException) as exc_info:
        await require_auth(req)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_auth_invalid_prefix():
    req = _make_request({"Authorization": "Bearer badprefix_xyz"})
    with pytest.raises(HTTPException) as exc_info:
        await require_auth(req)
    assert exc_info.value.status_code == 401
    assert "tk_" in exc_info.value.detail


@pytest.mark.asyncio
@patch("temper_ai.auth.api_key_auth._lookup_api_key", new_callable=AsyncMock)
async def test_require_auth_invalid_key(mock_lookup):
    mock_lookup.return_value = None
    token = "tk_validformatbutunknown"
    req = _make_request({"Authorization": f"Bearer {token}"})
    with pytest.raises(HTTPException) as exc_info:
        await require_auth(req)
    assert exc_info.value.status_code == 401
    assert "Invalid API key" in exc_info.value.detail


@pytest.mark.asyncio
@patch("temper_ai.auth.api_key_auth._lookup_api_key", new_callable=AsyncMock)
async def test_require_auth_revoked_key(mock_lookup):
    mock_lookup.return_value = _make_valid_lookup_result(is_active=False)
    token = "tk_revokedkey123"
    req = _make_request({"Authorization": f"Bearer {token}"})
    with pytest.raises(HTTPException) as exc_info:
        await require_auth(req)
    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower()


@pytest.mark.asyncio
@patch("temper_ai.auth.api_key_auth._lookup_api_key", new_callable=AsyncMock)
async def test_require_auth_expired_key(mock_lookup):
    past = datetime.now(UTC) - timedelta(hours=1)
    mock_lookup.return_value = _make_valid_lookup_result(expires_at=past)
    token = "tk_expiredkey123"
    req = _make_request({"Authorization": f"Bearer {token}"})
    with pytest.raises(HTTPException) as exc_info:
        await require_auth(req)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


# ── require_auth — success ────────────────────────────────────────────


@pytest.mark.asyncio
@patch("temper_ai.auth.api_key_auth._lookup_api_key", new_callable=AsyncMock)
async def test_require_auth_success(mock_lookup):
    mock_lookup.return_value = _make_valid_lookup_result()
    token = "tk_validkey123456"
    req = _make_request({"Authorization": f"Bearer {token}"})
    ctx = await require_auth(req)
    assert isinstance(ctx, AuthContext)
    assert ctx.user_id == "user-id-456"
    assert ctx.tenant_id == "tenant-id-789"
    assert ctx.role == "owner"
    assert ctx.api_key_id == "key-id-123"


@pytest.mark.asyncio
@patch("temper_ai.auth.api_key_auth._lookup_api_key", new_callable=AsyncMock)
async def test_require_auth_not_expired_key(mock_lookup):
    future = datetime.now(UTC) + timedelta(hours=1)
    mock_lookup.return_value = _make_valid_lookup_result(expires_at=future)
    token = "tk_validfuturekey"
    req = _make_request({"Authorization": f"Bearer {token}"})
    ctx = await require_auth(req)
    assert ctx.user_id == "user-id-456"


# ── require_role ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("temper_ai.auth.api_key_auth._lookup_api_key", new_callable=AsyncMock)
async def test_require_role_allowed(mock_lookup):
    mock_lookup.return_value = _make_valid_lookup_result(role="owner")
    check = require_role("owner", "editor")
    token = "tk_ownerkey12345"
    _make_request({"Authorization": f"Bearer {token}"})
    ctx = await check(
        ctx=AuthContext(user_id="u1", tenant_id="t1", role="owner", api_key_id="k1")
    )
    assert ctx.role == "owner"


@pytest.mark.asyncio
async def test_require_role_denied():
    check = require_role("owner", "editor")
    viewer_ctx = AuthContext(
        user_id="u1", tenant_id="t1", role="viewer", api_key_id="k1"
    )
    with pytest.raises(HTTPException) as exc_info:
        await check(ctx=viewer_ctx)
    assert exc_info.value.status_code == 403
    assert "Insufficient permissions" in exc_info.value.detail


# ── authenticate_ws_token ─────────────────────────────────────────────


@pytest.mark.asyncio
@patch("temper_ai.auth.api_key_auth._lookup_api_key", new_callable=AsyncMock)
async def test_authenticate_ws_token_valid(mock_lookup):
    mock_lookup.return_value = _make_valid_lookup_result()
    ctx = await authenticate_ws_token("tk_validwstoken12")
    assert isinstance(ctx, AuthContext)
    assert ctx.user_id == "user-id-456"


@pytest.mark.asyncio
@patch("temper_ai.auth.api_key_auth._lookup_api_key", new_callable=AsyncMock)
async def test_authenticate_ws_token_invalid(mock_lookup):
    mock_lookup.return_value = None
    result = await authenticate_ws_token("tk_unknowntoken12")
    assert result is None


@pytest.mark.asyncio
async def test_authenticate_ws_token_bad_prefix():
    result = await authenticate_ws_token("badprefix_xyz")
    assert result is None


@pytest.mark.asyncio
async def test_authenticate_ws_token_empty():
    result = await authenticate_ws_token("")
    assert result is None


@pytest.mark.asyncio
@patch("temper_ai.auth.api_key_auth._lookup_api_key", new_callable=AsyncMock)
async def test_authenticate_ws_token_revoked(mock_lookup):
    mock_lookup.return_value = _make_valid_lookup_result(is_active=False)
    result = await authenticate_ws_token("tk_revokedtoken12")
    assert result is None


@pytest.mark.asyncio
@patch("temper_ai.auth.api_key_auth._lookup_api_key", new_callable=AsyncMock)
async def test_authenticate_ws_token_expired(mock_lookup):
    past = datetime.now(UTC) - timedelta(hours=2)
    mock_lookup.return_value = _make_valid_lookup_result(expires_at=past)
    result = await authenticate_ws_token("tk_expiredwstoken")
    assert result is None
