"""Tests for temper_ai.interfaces.server.profile_routes — profile CRUD endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from temper_ai.auth.api_key_auth import AuthContext
from temper_ai.interfaces.server.profile_routes import (
    EDITOR_ROLES,
    VIEWER_ROLES,
    ProfileCreateRequest,
    ProfileUpdateRequest,
    _handle_create_profile,
    _handle_delete_profile,
    _handle_get_profile,
    _handle_list_profiles,
    _handle_update_profile,
    _validate_profile_type,
)

_MOCK_AUTH_CTX = AuthContext(
    user_id="test-user",
    tenant_id="test-tenant",
    role="owner",
    api_key_id="key-test",
)


class TestValidateProfileType:
    def test_valid_type(self):
        assert _validate_profile_type("llm") == "llm"

    def test_normalizes_hyphen(self):
        assert _validate_profile_type("error-handling") == "error_handling"

    def test_normalizes_case(self):
        assert _validate_profile_type("LLM") == "llm"

    def test_invalid_type(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_profile_type("invalid")
        assert exc_info.value.status_code == 400


class TestHandleCreateProfile:
    @patch("temper_ai.storage.database.manager.get_session")
    def test_success(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_get_session.return_value = mock_session

        body = ProfileCreateRequest(
            name="fast-llm",
            config_data={"provider": "openai", "model": "gpt-4"},
        )
        result = _handle_create_profile("llm", body, _MOCK_AUTH_CTX)
        assert result["name"] == "fast-llm"
        assert result["profile_type"] == "llm"
        assert "id" in result

    @patch("temper_ai.storage.database.manager.get_session")
    def test_duplicate_raises_400(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = (
            MagicMock()
        )
        mock_get_session.return_value = mock_session

        body = ProfileCreateRequest(name="dup", config_data={})
        with pytest.raises(HTTPException) as exc_info:
            _handle_create_profile("llm", body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 400

    def test_empty_name_raises_400(self):
        body = ProfileCreateRequest(name="  ", config_data={})
        with pytest.raises(HTTPException) as exc_info:
            _handle_create_profile("llm", body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 400


class TestHandleListProfiles:
    @patch("temper_ai.storage.database.manager.get_session")
    def test_success(self, mock_get_session):
        mock_record = MagicMock()
        mock_record.name = "fast-llm"
        mock_record.description = "Fast LLM profile"
        mock_record.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_record.updated_at.isoformat.return_value = "2024-01-01T00:00:00"

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.all.return_value = [
            mock_record
        ]
        mock_get_session.return_value = mock_session

        result = _handle_list_profiles("llm", _MOCK_AUTH_CTX)
        assert result["total"] == 1
        assert result["profiles"][0]["name"] == "fast-llm"


class TestHandleGetProfile:
    @patch("temper_ai.storage.database.manager.get_session")
    def test_found(self, mock_get_session):
        mock_record = MagicMock()
        mock_record.id = "p-1"
        mock_record.name = "fast-llm"
        mock_record.description = "desc"
        mock_record.config_data = {"provider": "openai"}
        mock_record.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_record.updated_at.isoformat.return_value = "2024-01-01T00:00:00"

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_record
        )
        mock_get_session.return_value = mock_session

        result = _handle_get_profile("llm", "fast-llm", _MOCK_AUTH_CTX)
        assert result["name"] == "fast-llm"
        assert result["config_data"] == {"provider": "openai"}

    @patch("temper_ai.storage.database.manager.get_session")
    def test_not_found(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_get_session.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            _handle_get_profile("llm", "missing", _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 404


class TestHandleUpdateProfile:
    @patch("temper_ai.storage.database.manager.get_session")
    def test_success(self, mock_get_session):
        mock_record = MagicMock()
        mock_record.id = "p-1"
        mock_record.name = "fast-llm"

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_record
        )
        mock_get_session.return_value = mock_session

        body = ProfileUpdateRequest(config_data={"provider": "anthropic"})
        result = _handle_update_profile("llm", "fast-llm", body, _MOCK_AUTH_CTX)
        assert result["name"] == "fast-llm"

    @patch("temper_ai.storage.database.manager.get_session")
    def test_not_found(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_get_session.return_value = mock_session

        body = ProfileUpdateRequest(description="updated")
        with pytest.raises(HTTPException) as exc_info:
            _handle_update_profile("llm", "missing", body, _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 404


class TestHandleDeleteProfile:
    @patch("temper_ai.storage.database.manager.get_session")
    def test_success(self, mock_get_session):
        mock_record = MagicMock()

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_record
        )
        mock_get_session.return_value = mock_session

        result = _handle_delete_profile("llm", "fast-llm", _MOCK_AUTH_CTX)
        assert result["status"] == "deleted"

    @patch("temper_ai.storage.database.manager.get_session")
    def test_not_found(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_get_session.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            _handle_delete_profile("llm", "missing", _MOCK_AUTH_CTX)
        assert exc_info.value.status_code == 404


class TestConstants:
    def test_editor_roles(self):
        assert "editor" in EDITOR_ROLES
        assert "owner" in EDITOR_ROLES

    def test_viewer_roles(self):
        assert "viewer" in VIEWER_ROLES
        assert "editor" in VIEWER_ROLES
        assert "owner" in VIEWER_ROLES
