"""Tests for temper_ai/interfaces/server/auth_routes.py — auth API endpoints."""

from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.auth.api_key_auth import AuthContext, require_auth
from temper_ai.interfaces.server.auth_routes import (
    _rate_limit_store,
    create_auth_router,
)


@pytest.fixture(autouse=True)
def clear_rate_limits():
    """Reset in-memory rate limit state between tests to prevent contamination."""
    _rate_limit_store.clear()
    yield
    _rate_limit_store.clear()


# ── App + Client setup ────────────────────────────────────────────────

MOCK_AUTH_CTX = AuthContext(
    user_id="user-001",
    tenant_id="tenant-001",
    role="owner",
    api_key_id="key-001",
)


def _make_app(auth_override=None) -> FastAPI:
    app = FastAPI()
    app.include_router(create_auth_router())
    if auth_override is not None:
        app.dependency_overrides[require_auth] = auth_override
    return app


def _mock_auth():
    async def _dep():
        return MOCK_AUTH_CTX

    return _dep


def _make_mock_session(session_mock):
    """Return a context-manager mock wrapping session_mock."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session_mock)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# ── signup ────────────────────────────────────────────────────────────


def test_signup_creates_user_and_key():
    """POST /api/auth/signup should return user_id, tenant_id, api_key."""
    session = MagicMock()
    session_ctx = _make_mock_session(session)

    user_mock = MagicMock()
    user_mock.id = "new-user-id"
    tenant_mock = MagicMock()
    tenant_mock.id = "new-tenant-id"
    api_key_mock = MagicMock()
    api_key_mock.id = "new-key-id"
    api_key_mock.key_prefix = "tk_abcdefgh"
    api_key_mock.label = "default"

    # _create_user raises if email exists; for new user exec().first() = None
    session.exec.return_value.first.return_value = None
    session.flush = MagicMock()
    session.commit = MagicMock()

    with (
        patch(
            "temper_ai.interfaces.server.auth_routes.get_session",
            return_value=session_ctx,
        ),
        patch(
            "temper_ai.interfaces.server.auth_routes._create_user",
            return_value=user_mock,
        ),
        patch(
            "temper_ai.interfaces.server.auth_routes._create_tenant",
            return_value=tenant_mock,
        ),
        patch("temper_ai.interfaces.server.auth_routes._create_membership"),
        patch(
            "temper_ai.interfaces.server.auth_routes._create_api_key",
            return_value=("tk_full_key_here", api_key_mock),
        ),
    ):
        app = _make_app()
        client = TestClient(app)
        resp = client.post(
            "/api/auth/signup", json={"email": "user@example.com", "name": "Alice"}
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "api_key" in body
    assert "user_id" in body
    assert "tenant_id" in body


def test_signup_slug_collision():
    """Second signup from same domain gets suffixed slug (e.g. acme-2)."""
    from temper_ai.interfaces.server.auth_routes import _create_tenant
    from temper_ai.storage.database.models_tenancy import Tenant

    # Simulate: first query finds existing tenant, second query finds none
    existing_tenant = MagicMock(spec=Tenant)
    existing_tenant.slug = "acme"

    call_count = 0

    def _exec_side_effect(*args, **kwargs):
        nonlocal call_count
        result = MagicMock()
        call_count += 1
        # First call: slug "acme" already taken; second call: "acme-2" is free
        if call_count == 1:
            result.first.return_value = existing_tenant
        else:
            result.first.return_value = None
        return result

    session = MagicMock()
    session.exec.side_effect = _exec_side_effect
    session.flush = MagicMock()

    tenant = _create_tenant(session, "acme")

    assert tenant.slug == "acme-2"
    assert tenant.name == "acme-2"
    assert session.add.called


def test_signup_duplicate_email():
    """POST /api/auth/signup with an existing email should return 400."""
    from fastapi import HTTPException
    from starlette.status import HTTP_400_BAD_REQUEST

    session = MagicMock()
    session_ctx = _make_mock_session(session)

    def _raise_duplicate(*args, **kwargs):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="A user with that email already exists.",
        )

    with (
        patch(
            "temper_ai.interfaces.server.auth_routes.get_session",
            return_value=session_ctx,
        ),
        patch(
            "temper_ai.interfaces.server.auth_routes._create_user",
            side_effect=_raise_duplicate,
        ),
    ):
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/auth/signup", json={"email": "dup@example.com"})

    assert resp.status_code == 400


# ── create_api_key ────────────────────────────────────────────────────


def test_create_api_key():
    """POST /api/auth/api-keys should return a new key with prefix."""
    session = MagicMock()
    session_ctx = _make_mock_session(session)
    session.commit = MagicMock()

    new_key = MagicMock()
    new_key.id = "key-new-001"
    new_key.key_prefix = "tk_newprefx"
    new_key.label = "ci"

    with (
        patch(
            "temper_ai.interfaces.server.auth_routes.get_session",
            return_value=session_ctx,
        ),
        patch(
            "temper_ai.interfaces.server.auth_routes._create_api_key",
            return_value=("tk_full_new_key_123", new_key),
        ),
    ):
        app = _make_app(auth_override=_mock_auth())
        client = TestClient(app)
        resp = client.post(
            "/api/auth/api-keys",
            json={"label": "ci"},
            headers={"Authorization": "Bearer tk_doesnotmatter"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["api_key"] == "tk_full_new_key_123"
    assert body["key_prefix"] == "tk_newprefx"


# ── list_api_keys ─────────────────────────────────────────────────────


def test_list_api_keys():
    """GET /api/auth/api-keys should return a list of key summaries."""
    from datetime import datetime

    session = MagicMock()
    session_ctx = _make_mock_session(session)

    key1 = MagicMock()
    key1.id = "k1"
    key1.label = "default"
    key1.key_prefix = "tk_abc"
    key1.is_active = True
    key1.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    key1.last_used_at = None
    key1.total_requests = 0

    session.exec.return_value.all.return_value = [key1]

    with patch(
        "temper_ai.interfaces.server.auth_routes.get_session", return_value=session_ctx
    ):
        app = _make_app(auth_override=_mock_auth())
        client = TestClient(app)
        resp = client.get(
            "/api/auth/api-keys",
            headers={"Authorization": "Bearer tk_doesnotmatter"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "keys" in body
    assert len(body["keys"]) == 1
    assert body["keys"][0]["id"] == "k1"
    assert body["keys"][0]["label"] == "default"


# ── revoke_api_key ────────────────────────────────────────────────────


def test_revoke_api_key():
    """DELETE /api/auth/api-keys/{id} should soft-delete the key."""
    session = MagicMock()
    session_ctx = _make_mock_session(session)

    api_key = MagicMock()
    api_key.id = "key-001"
    api_key.user_id = "user-001"
    api_key.is_active = True
    session.get.return_value = api_key
    session.commit = MagicMock()

    with patch(
        "temper_ai.interfaces.server.auth_routes.get_session", return_value=session_ctx
    ):
        app = _make_app(auth_override=_mock_auth())
        client = TestClient(app)
        resp = client.delete(
            "/api/auth/api-keys/key-001",
            headers={"Authorization": "Bearer tk_doesnotmatter"},
        )

    assert resp.status_code == 200
    assert resp.json()["revoked"] is True
    assert api_key.is_active is False


def test_revoke_api_key_not_found():
    """DELETE /api/auth/api-keys/{id} with unknown key should return 404."""
    session = MagicMock()
    session_ctx = _make_mock_session(session)
    session.get.return_value = None

    with patch(
        "temper_ai.interfaces.server.auth_routes.get_session", return_value=session_ctx
    ):
        app = _make_app(auth_override=_mock_auth())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.delete(
            "/api/auth/api-keys/nonexistent-key",
            headers={"Authorization": "Bearer tk_doesnotmatter"},
        )

    assert resp.status_code == 404


# ── me ────────────────────────────────────────────────────────────────


def test_get_me():
    """GET /api/auth/me should return user and tenant info."""
    session = MagicMock()
    session_ctx = _make_mock_session(session)

    user_mock = MagicMock()
    user_mock.id = "user-001"
    user_mock.email = "alice@example.com"
    user_mock.name = "Alice"

    tenant_mock = MagicMock()
    tenant_mock.id = "tenant-001"
    tenant_mock.name = "example"
    tenant_mock.slug = "example"
    tenant_mock.plan = "free"

    membership_mock = MagicMock()
    membership_mock.role = "owner"

    def _session_get(model, pk):
        from temper_ai.storage.database.models_tenancy import Tenant, UserDB

        if model is UserDB:
            return user_mock
        if model is Tenant:
            return tenant_mock
        return None

    session.get.side_effect = _session_get
    session.exec.return_value.first.return_value = membership_mock

    with patch(
        "temper_ai.interfaces.server.auth_routes.get_session", return_value=session_ctx
    ):
        app = _make_app(auth_override=_mock_auth())
        client = TestClient(app)
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer tk_doesnotmatter"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["tenant"]["slug"] == "example"
    assert body["role"] == "owner"


def test_get_me_user_not_found():
    """GET /api/auth/me returns 404 when user is missing from DB."""
    session = MagicMock()
    session_ctx = _make_mock_session(session)
    session.get.return_value = None

    with patch(
        "temper_ai.interfaces.server.auth_routes.get_session", return_value=session_ctx
    ):
        app = _make_app(auth_override=_mock_auth())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer tk_doesnotmatter"},
        )

    assert resp.status_code == 404


# ── unauthorized ──────────────────────────────────────────────────────


def test_unauthorized_without_key():
    """Requests to protected endpoints without auth header return 401."""
    with patch("temper_ai.auth.api_key_auth._lookup_api_key") as _mock:
        app = FastAPI()
        app.include_router(create_auth_router())
        # No dependency override — real require_auth runs
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/auth/api-keys")

    assert resp.status_code == 401
