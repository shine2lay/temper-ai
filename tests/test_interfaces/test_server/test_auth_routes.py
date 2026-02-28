"""Tests for auth_routes helper functions and Pydantic models."""

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from temper_ai.interfaces.server.auth_routes import (
    API_KEY_RATE_LIMIT,
    RATE_LIMIT_WINDOW,
    SIGNUP_RATE_LIMIT,
    CreateApiKeyRequest,
    SignupRequest,
    _check_rate_limit,
    _create_api_key,
    _create_membership,
    _create_tenant,
    _create_user,
    _derive_tenant_slug,
    _handle_create_api_key_endpoint,
    _handle_list_api_keys,
    _handle_me,
    _handle_revoke_api_key,
    _handle_signup,
    _rate_limit_store,
    create_auth_router,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_rate_store(key: str) -> None:
    """Remove all entries for a key from the rate limit store."""
    _rate_limit_store.pop(key, None)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_signup_rate_limit_is_positive(self) -> None:
        assert SIGNUP_RATE_LIMIT > 0

    def test_api_key_rate_limit_is_positive(self) -> None:
        assert API_KEY_RATE_LIMIT > 0

    def test_rate_limit_window_is_positive(self) -> None:
        assert RATE_LIMIT_WINDOW > 0

    def test_api_key_limit_greater_than_signup(self) -> None:
        assert API_KEY_RATE_LIMIT >= SIGNUP_RATE_LIMIT


# ---------------------------------------------------------------------------
# SignupRequest model
# ---------------------------------------------------------------------------


class TestSignupRequest:
    def test_valid_email(self) -> None:
        req = SignupRequest(email="user@example.com")
        assert req.email == "user@example.com"

    def test_name_defaults_to_none(self) -> None:
        req = SignupRequest(email="user@example.com")
        assert req.name is None

    def test_name_can_be_set(self) -> None:
        req = SignupRequest(email="user@example.com", name="Alice")
        assert req.name == "Alice"

    def test_invalid_email_raises(self) -> None:
        with pytest.raises(ValidationError):
            SignupRequest(email="not-an-email")

    def test_empty_email_raises(self) -> None:
        with pytest.raises(ValidationError):
            SignupRequest(email="")

    def test_missing_email_raises(self) -> None:
        with pytest.raises(ValidationError):
            SignupRequest()  # type: ignore[call-arg]

    def test_email_is_validated_as_email_type(self) -> None:
        req = SignupRequest(email="alice@corp.io")
        # EmailStr lowercases / normalizes
        assert "@" in str(req.email)


# ---------------------------------------------------------------------------
# CreateApiKeyRequest model
# ---------------------------------------------------------------------------


class TestCreateApiKeyRequest:
    def test_default_label(self) -> None:
        req = CreateApiKeyRequest()
        assert req.label == "default"

    def test_custom_label(self) -> None:
        req = CreateApiKeyRequest(label="production")
        assert req.label == "production"

    def test_label_can_be_none(self) -> None:
        req = CreateApiKeyRequest(label=None)
        assert req.label is None

    def test_model_dump(self) -> None:
        req = CreateApiKeyRequest(label="ci")
        assert req.model_dump() == {"label": "ci"}


# ---------------------------------------------------------------------------
# _check_rate_limit
# ---------------------------------------------------------------------------


class TestCheckRateLimit:
    def setup_method(self) -> None:
        """Clear the shared rate limit store before each test."""
        _rate_limit_store.clear()

    def test_first_request_is_allowed(self) -> None:
        assert _check_rate_limit("test-key", 5) is True

    def test_requests_within_limit_are_allowed(self) -> None:
        for _ in range(5):
            assert _check_rate_limit("within-limit", 5) is True

    def test_request_at_limit_is_blocked(self) -> None:
        key = "at-limit"
        for _ in range(5):
            _check_rate_limit(key, 5)
        # 6th request should be blocked
        assert _check_rate_limit(key, 5) is False

    def test_different_keys_are_independent(self) -> None:
        for _ in range(5):
            _check_rate_limit("key-a", 5)
        # key-a is exhausted, key-b is fresh
        assert _check_rate_limit("key-b", 5) is True

    def test_limit_of_one_allows_first_blocks_second(self) -> None:
        key = "single"
        assert _check_rate_limit(key, 1) is True
        assert _check_rate_limit(key, 1) is False

    def test_old_timestamps_pruned(self) -> None:
        key = "prune-test"
        # Manually insert very old timestamps
        _rate_limit_store[key] = [
            time.monotonic() - RATE_LIMIT_WINDOW - 10
        ] * 5  # all expired
        # Should be allowed since old entries are pruned
        assert _check_rate_limit(key, 5) is True

    def test_new_timestamps_counted(self) -> None:
        key = "recent-test"
        # Fill with recent timestamps
        now = time.monotonic()
        _rate_limit_store[key] = [now - 1] * 5  # 5 recent entries
        # Next request should be blocked (limit=5)
        assert _check_rate_limit(key, 5) is False


# ---------------------------------------------------------------------------
# _derive_tenant_slug
# ---------------------------------------------------------------------------


class TestDeriveTenantSlug:
    def test_extracts_domain_from_email(self) -> None:
        slug = _derive_tenant_slug("alice@acmecorp.com")
        assert slug == "acmecorp"

    def test_handles_subdomain_email(self) -> None:
        slug = _derive_tenant_slug("user@mail.example.com")
        # Splits on first '.', takes domain part: 'mail'
        assert slug == "mail"

    def test_gmail_domain(self) -> None:
        slug = _derive_tenant_slug("user@gmail.com")
        assert slug == "gmail"

    def test_returns_personal_slug_for_malformed_email(self) -> None:
        slug = _derive_tenant_slug("no-at-sign")
        assert slug.startswith("personal-")

    def test_returns_personal_slug_when_domain_empty(self) -> None:
        # Edge case: email like "@domain" has empty local part but valid domain
        slug = _derive_tenant_slug("user@.com")
        # domain.split('.')[0] == '' which is falsy → personal slug
        assert slug.startswith("personal-")

    def test_personal_slug_has_uuid_suffix(self) -> None:
        slug = _derive_tenant_slug("malformed")
        # Should be "personal-<8 hex chars>"
        assert slug.startswith("personal-")
        suffix = slug[len("personal-") :]
        assert len(suffix) == 8

    def test_consistent_for_same_email(self) -> None:
        s1 = _derive_tenant_slug("alice@company.com")
        s2 = _derive_tenant_slug("alice@company.com")
        assert s1 == s2


# ---------------------------------------------------------------------------
# _create_user (mocked session)
# ---------------------------------------------------------------------------


class TestCreateUser:
    def _make_session(self, existing_user=None):
        session = MagicMock()
        session.exec.return_value.first.return_value = existing_user
        return session

    def test_creates_user_when_not_exists(self) -> None:
        session = self._make_session(existing_user=None)
        user = _create_user(session, "alice@example.com", "Alice")
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert user.email == "alice@example.com"
        assert user.name == "Alice"

    def test_raises_http_400_when_email_exists(self) -> None:
        existing = MagicMock()
        session = self._make_session(existing_user=existing)
        with pytest.raises(HTTPException) as exc_info:
            _create_user(session, "alice@example.com", "Alice")
        assert exc_info.value.status_code == 400
        assert "already exists" in exc_info.value.detail


# ---------------------------------------------------------------------------
# _create_tenant (mocked session)
# ---------------------------------------------------------------------------


class TestCreateTenant:
    def test_creates_tenant_on_first_try(self) -> None:
        session = MagicMock()
        session.exec.return_value.first.return_value = None  # No collision
        tenant = _create_tenant(session, "acme")
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert tenant.slug == "acme"

    def test_handles_slug_collision_by_incrementing(self) -> None:
        session = MagicMock()
        existing = MagicMock()
        # First slug collides, second is free
        session.exec.return_value.first.side_effect = [existing, None]
        tenant = _create_tenant(session, "acme")
        assert tenant.slug == "acme-2"


# ---------------------------------------------------------------------------
# _create_membership (mocked session)
# ---------------------------------------------------------------------------


class TestCreateMembership:
    def test_creates_membership(self) -> None:
        session = MagicMock()
        membership = _create_membership(session, "tenant-1", "user-1", "owner")
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert membership.tenant_id == "tenant-1"
        assert membership.user_id == "user-1"
        assert membership.role == "owner"


# ---------------------------------------------------------------------------
# _create_api_key (mocked session + mocked generate_api_key)
# ---------------------------------------------------------------------------


class TestCreateApiKey:
    def test_creates_api_key_record(self) -> None:
        session = MagicMock()
        with patch(
            "temper_ai.interfaces.server.auth_routes.generate_api_key",
            return_value=("full-key", "prefix", "hash"),
        ):
            full_key, api_key = _create_api_key(session, "user-1", "tenant-1", "ci")
        assert full_key == "full-key"
        assert api_key.user_id == "user-1"
        assert api_key.tenant_id == "tenant-1"
        assert api_key.label == "ci"
        assert api_key.key_prefix == "prefix"
        assert api_key.key_hash == "hash"
        session.add.assert_called_once()
        session.flush.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_list_api_keys (mocked session + AuthContext)
# ---------------------------------------------------------------------------


class TestHandleListApiKeys:
    def _make_ctx(self, user_id="u1", tenant_id="t1"):
        ctx = MagicMock()
        ctx.user_id = user_id
        ctx.tenant_id = tenant_id
        return ctx

    def _make_api_key(self, key_id="k1", label="default"):
        k = MagicMock()
        k.id = key_id
        k.label = label
        k.key_prefix = "sk_..."
        k.is_active = True
        import datetime

        k.created_at = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
        k.last_used_at = None
        k.total_requests = 0
        return k

    def test_returns_keys_list(self) -> None:
        ctx = self._make_ctx()
        mock_key = self._make_api_key()
        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = [mock_key]
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            result = _handle_list_api_keys(ctx)

        assert "keys" in result
        assert len(result["keys"]) == 1
        assert result["keys"][0]["id"] == "k1"

    def test_empty_keys_list(self) -> None:
        ctx = self._make_ctx()
        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = []
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            result = _handle_list_api_keys(ctx)

        assert result["keys"] == []

    def test_key_with_last_used_at(self) -> None:
        import datetime

        ctx = self._make_ctx()
        mock_key = self._make_api_key()
        mock_key.last_used_at = datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC)
        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = [mock_key]
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            result = _handle_list_api_keys(ctx)

        assert result["keys"][0]["last_used_at"] is not None


# ---------------------------------------------------------------------------
# _handle_revoke_api_key (mocked session + AuthContext)
# ---------------------------------------------------------------------------


class TestHandleRevokeApiKey:
    def _make_ctx(self, user_id="u1", tenant_id="t1"):
        ctx = MagicMock()
        ctx.user_id = user_id
        ctx.tenant_id = tenant_id
        return ctx

    def test_revokes_api_key(self) -> None:
        ctx = self._make_ctx()
        mock_key = MagicMock()
        mock_key.user_id = "u1"
        mock_key.tenant_id = "t1"
        mock_key.is_active = True

        mock_session = MagicMock()
        mock_session.get.return_value = mock_key
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            result = _handle_revoke_api_key("k1", ctx)

        assert result == {"revoked": True}
        assert mock_key.is_active is False

    def test_raises_404_when_key_not_found(self) -> None:
        ctx = self._make_ctx()
        mock_session = MagicMock()
        mock_session.get.return_value = None
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            with pytest.raises(HTTPException) as exc_info:
                _handle_revoke_api_key("missing-key", ctx)
        assert exc_info.value.status_code == 404

    def test_raises_404_when_wrong_user(self) -> None:
        ctx = self._make_ctx(user_id="u1")
        mock_key = MagicMock()
        mock_key.user_id = "other-user"
        mock_key.tenant_id = "t1"

        mock_session = MagicMock()
        mock_session.get.return_value = mock_key
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            with pytest.raises(HTTPException) as exc_info:
                _handle_revoke_api_key("k1", ctx)
        assert exc_info.value.status_code == 404

    def test_raises_404_when_wrong_tenant(self) -> None:
        ctx = self._make_ctx(tenant_id="t1")
        mock_key = MagicMock()
        mock_key.user_id = "u1"
        mock_key.tenant_id = "other-tenant"

        mock_session = MagicMock()
        mock_session.get.return_value = mock_key
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            with pytest.raises(HTTPException) as exc_info:
                _handle_revoke_api_key("k1", ctx)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _handle_me (mocked session + AuthContext)
# ---------------------------------------------------------------------------


class TestHandleMe:
    def _make_ctx(self, user_id="u1", tenant_id="t1", role="owner"):
        ctx = MagicMock()
        ctx.user_id = user_id
        ctx.tenant_id = tenant_id
        ctx.role = role
        return ctx

    def _make_mock_session(self, user=None, tenant=None, membership=None):
        session = MagicMock()
        # session.get(UserDB, ...) → user; session.get(Tenant, ...) → tenant
        session.get.side_effect = lambda model, pk: (
            user if "User" in model.__name__ else tenant
        )
        session.exec.return_value.first.return_value = membership
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=session)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm

    def test_returns_user_and_tenant(self) -> None:
        ctx = self._make_ctx()
        user = MagicMock()
        user.id = "u1"
        user.email = "alice@example.com"
        user.name = "Alice"

        tenant = MagicMock()
        tenant.id = "t1"
        tenant.name = "acme"
        tenant.slug = "acme"
        tenant.plan = "free"

        membership = MagicMock()
        membership.role = "owner"

        mock_cm = self._make_mock_session(
            user=user, tenant=tenant, membership=membership
        )
        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            result = _handle_me(ctx)

        assert result["user"]["id"] == "u1"
        assert result["user"]["email"] == "alice@example.com"
        assert result["tenant"]["id"] == "t1"
        assert result["role"] == "owner"

    def test_raises_404_when_user_not_found(self) -> None:
        ctx = self._make_ctx()
        session = MagicMock()
        session.get.return_value = None  # User not found
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            with pytest.raises(HTTPException) as exc_info:
                _handle_me(ctx)
        assert exc_info.value.status_code == 404

    def test_raises_404_when_tenant_not_found(self) -> None:
        ctx = self._make_ctx()
        user = MagicMock()
        user.id = "u1"
        user.email = "alice@example.com"
        user.name = "Alice"

        session = MagicMock()
        call_count = [0]

        def mock_get(model, pk):
            call_count[0] += 1
            if call_count[0] == 1:
                return user
            return None  # Tenant not found

        session.get.side_effect = mock_get
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            with pytest.raises(HTTPException) as exc_info:
                _handle_me(ctx)
        assert exc_info.value.status_code == 404
        assert "Tenant" in exc_info.value.detail

    def test_falls_back_to_ctx_role_when_no_membership(self) -> None:
        ctx = self._make_ctx(role="viewer")
        user = MagicMock()
        user.id = "u1"
        user.email = "bob@example.com"
        user.name = "Bob"

        tenant = MagicMock()
        tenant.id = "t1"
        tenant.name = "corp"
        tenant.slug = "corp"
        tenant.plan = "pro"

        session = MagicMock()
        # Return user for first call, tenant for second
        call_count = [0]

        def mock_get(model, pk):
            call_count[0] += 1
            if call_count[0] == 1:
                return user
            return tenant

        session.get.side_effect = mock_get
        session.exec.return_value.first.return_value = None  # No membership

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=session)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch(
            "temper_ai.interfaces.server.auth_routes.get_session", return_value=mock_cm
        ):
            result = _handle_me(ctx)

        assert result["role"] == "viewer"  # Falls back to ctx.role


# ---------------------------------------------------------------------------
# _handle_signup (mocked session + mocked request)
# ---------------------------------------------------------------------------


class TestHandleSignup:
    def setup_method(self) -> None:
        _rate_limit_store.clear()

    def _make_request(self, host: str = "127.0.0.1"):
        req = MagicMock()
        req.client.host = host
        return req

    def _make_session_cm(self, session):
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=session)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm

    def test_signup_success(self) -> None:
        session = MagicMock()
        session.exec.return_value.first.return_value = (
            None  # No existing user, no existing tenant
        )

        mock_user = MagicMock()
        mock_user.id = "u1"
        mock_tenant = MagicMock()
        mock_tenant.id = "t1"

        mock_cm = self._make_session_cm(session)
        body = SignupRequest(email="alice@acme.com", name="Alice")
        request = self._make_request()

        with (
            patch(
                "temper_ai.interfaces.server.auth_routes.get_session",
                return_value=mock_cm,
            ),
            patch(
                "temper_ai.interfaces.server.auth_routes._create_user",
                return_value=mock_user,
            ),
            patch(
                "temper_ai.interfaces.server.auth_routes._create_tenant",
                return_value=mock_tenant,
            ),
            patch("temper_ai.interfaces.server.auth_routes._create_membership"),
            patch(
                "temper_ai.interfaces.server.auth_routes._create_api_key",
                return_value=("full-key", MagicMock()),
            ),
        ):
            result = _handle_signup(body, request)

        assert result["user_id"] == "u1"
        assert result["tenant_id"] == "t1"
        assert result["api_key"] == "full-key"

    def test_signup_rate_limited(self) -> None:
        body = SignupRequest(email="alice@acme.com")
        request = self._make_request(host="1.2.3.4")

        # Exhaust rate limit
        for _ in range(SIGNUP_RATE_LIMIT):
            _check_rate_limit("signup:1.2.3.4", SIGNUP_RATE_LIMIT)

        with pytest.raises(HTTPException) as exc_info:
            _handle_signup(body, request)
        assert exc_info.value.status_code == 429

    def test_signup_no_client(self) -> None:
        session = MagicMock()
        session.exec.return_value.first.return_value = None
        mock_cm = self._make_session_cm(session)

        body = SignupRequest(email="alice@acme.com")
        request = MagicMock()
        request.client = None  # No client info

        with (
            patch(
                "temper_ai.interfaces.server.auth_routes.get_session",
                return_value=mock_cm,
            ),
            patch(
                "temper_ai.interfaces.server.auth_routes._create_user",
                return_value=MagicMock(id="u1"),
            ),
            patch(
                "temper_ai.interfaces.server.auth_routes._create_tenant",
                return_value=MagicMock(id="t1"),
            ),
            patch("temper_ai.interfaces.server.auth_routes._create_membership"),
            patch(
                "temper_ai.interfaces.server.auth_routes._create_api_key",
                return_value=("key", MagicMock()),
            ),
        ):
            result = _handle_signup(body, request)
        assert "api_key" in result


# ---------------------------------------------------------------------------
# _handle_create_api_key_endpoint (mocked session + AuthContext)
# ---------------------------------------------------------------------------


class TestHandleCreateApiKeyEndpoint:
    def setup_method(self) -> None:
        _rate_limit_store.clear()

    def _make_ctx(self, user_id="u1", tenant_id="t1"):
        from temper_ai.auth.api_key_auth import AuthContext

        return AuthContext(
            user_id=user_id, tenant_id=tenant_id, role="owner", api_key_id="k1"
        )

    def _make_session_cm(self, session):
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=session)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm

    def test_creates_api_key(self) -> None:
        ctx = self._make_ctx()
        body = CreateApiKeyRequest(label="production")
        session = MagicMock()
        mock_cm = self._make_session_cm(session)

        mock_api_key = MagicMock()
        mock_api_key.id = "key-1"
        mock_api_key.key_prefix = "sk_..."
        mock_api_key.label = "production"

        with (
            patch(
                "temper_ai.interfaces.server.auth_routes.get_session",
                return_value=mock_cm,
            ),
            patch(
                "temper_ai.interfaces.server.auth_routes._create_api_key",
                return_value=("full-key-123", mock_api_key),
            ),
        ):
            result = _handle_create_api_key_endpoint(body, ctx)

        assert result["api_key"] == "full-key-123"
        assert result["api_key_id"] == "key-1"
        assert result["label"] == "production"

    def test_rate_limited(self) -> None:
        ctx = self._make_ctx()
        body = CreateApiKeyRequest()

        # Exhaust rate limit
        for _ in range(API_KEY_RATE_LIMIT):
            _check_rate_limit(f"api-key:{ctx.user_id}", API_KEY_RATE_LIMIT)

        with pytest.raises(HTTPException) as exc_info:
            _handle_create_api_key_endpoint(body, ctx)
        assert exc_info.value.status_code == 429

    def test_default_label(self) -> None:
        ctx = self._make_ctx()
        body = CreateApiKeyRequest()  # label defaults to "default"
        session = MagicMock()
        mock_cm = self._make_session_cm(session)
        mock_api_key = MagicMock()
        mock_api_key.id = "k2"
        mock_api_key.key_prefix = "sk_..."
        mock_api_key.label = "default"

        with (
            patch(
                "temper_ai.interfaces.server.auth_routes.get_session",
                return_value=mock_cm,
            ),
            patch(
                "temper_ai.interfaces.server.auth_routes._create_api_key",
                return_value=("key-456", mock_api_key),
            ),
        ):
            result = _handle_create_api_key_endpoint(body, ctx)
        assert result["label"] == "default"

    def test_none_label_becomes_default(self) -> None:
        ctx = self._make_ctx()
        body = CreateApiKeyRequest(label=None)
        session = MagicMock()
        mock_cm = self._make_session_cm(session)
        mock_api_key = MagicMock()
        mock_api_key.id = "k3"
        mock_api_key.key_prefix = "sk_..."
        mock_api_key.label = "default"

        with (
            patch(
                "temper_ai.interfaces.server.auth_routes.get_session",
                return_value=mock_cm,
            ),
            patch(
                "temper_ai.interfaces.server.auth_routes._create_api_key",
                return_value=("key-789", mock_api_key),
            ),
        ):
            result = _handle_create_api_key_endpoint(body, ctx)
        assert result["label"] == "default"


# ---------------------------------------------------------------------------
# create_auth_router + route integration tests (using TestClient)
# ---------------------------------------------------------------------------


class TestCreateAuthRouter:
    def test_router_has_expected_routes(self) -> None:
        router = create_auth_router()
        paths = [r.path for r in router.routes]
        assert "/api/auth/signup" in paths
        assert "/api/auth/api-keys" in paths
        assert "/api/auth/api-keys/{key_id}" in paths
        assert "/api/auth/ws-ticket" in paths
        assert "/api/auth/me" in paths

    def test_signup_route_via_client(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        router = create_auth_router()
        app.include_router(router)

        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "temper_ai.interfaces.server.auth_routes._handle_signup",
            return_value={"user_id": "u1", "tenant_id": "t1", "api_key": "key"},
        ):
            resp = client.post("/api/auth/signup", json={"email": "test@example.com"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "u1"

    def test_create_api_key_route_via_client(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from temper_ai.auth.api_key_auth import AuthContext, require_auth

        app = FastAPI()
        router = create_auth_router()
        app.include_router(router)

        ctx = AuthContext(user_id="u1", tenant_id="t1", role="owner", api_key_id="k1")

        async def mock_auth():
            return ctx

        app.dependency_overrides[require_auth] = mock_auth

        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "temper_ai.interfaces.server.auth_routes._handle_create_api_key_endpoint",
            return_value={
                "api_key_id": "k2",
                "api_key": "full",
                "key_prefix": "sk_",
                "label": "default",
            },
        ):
            resp = client.post("/api/auth/api-keys", json={"label": "default"})
        assert resp.status_code == 200

    def test_list_api_keys_route_via_client(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from temper_ai.auth.api_key_auth import AuthContext, require_auth

        app = FastAPI()
        router = create_auth_router()
        app.include_router(router)

        ctx = AuthContext(user_id="u1", tenant_id="t1", role="owner", api_key_id="k1")

        async def mock_auth():
            return ctx

        app.dependency_overrides[require_auth] = mock_auth

        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "temper_ai.interfaces.server.auth_routes._handle_list_api_keys",
            return_value={"keys": []},
        ):
            resp = client.get("/api/auth/api-keys")
        assert resp.status_code == 200

    def test_revoke_api_key_route_via_client(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from temper_ai.auth.api_key_auth import AuthContext, require_auth

        app = FastAPI()
        router = create_auth_router()
        app.include_router(router)

        ctx = AuthContext(user_id="u1", tenant_id="t1", role="owner", api_key_id="k1")

        async def mock_auth():
            return ctx

        app.dependency_overrides[require_auth] = mock_auth

        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "temper_ai.interfaces.server.auth_routes._handle_revoke_api_key",
            return_value={"revoked": True},
        ):
            resp = client.delete("/api/auth/api-keys/some-key-id")
        assert resp.status_code == 200

    def test_ws_ticket_route_via_client(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from temper_ai.auth.api_key_auth import AuthContext, require_auth

        app = FastAPI()
        router = create_auth_router()
        app.include_router(router)

        ctx = AuthContext(user_id="u1", tenant_id="t1", role="owner", api_key_id="k1")

        async def mock_auth():
            return ctx

        app.dependency_overrides[require_auth] = mock_auth

        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "temper_ai.auth.ws_tickets.generate_ws_ticket",
            return_value="ticket-123",
        ):
            resp = client.post("/api/auth/ws-ticket")
        assert resp.status_code == 200
        assert resp.json()["ticket"] == "ticket-123"

    def test_me_route_via_client(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from temper_ai.auth.api_key_auth import AuthContext, require_auth

        app = FastAPI()
        router = create_auth_router()
        app.include_router(router)

        ctx = AuthContext(user_id="u1", tenant_id="t1", role="owner", api_key_id="k1")

        async def mock_auth():
            return ctx

        app.dependency_overrides[require_auth] = mock_auth

        client = TestClient(app, raise_server_exceptions=False)
        with patch(
            "temper_ai.interfaces.server.auth_routes._handle_me",
            return_value={
                "user": {"id": "u1", "email": "a@b.com", "name": "A"},
                "tenant": {"id": "t1", "name": "t", "slug": "t", "plan": "free"},
                "role": "owner",
            },
        ):
            resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        assert resp.json()["user"]["id"] == "u1"
