"""Extended tests for temper_ai.interfaces.dashboard.studio_service — cover DB methods and edge cases."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.interfaces.dashboard.studio_service import (
    MAX_CONFIG_SIZE_BYTES,
    VALID_CONFIG_TYPES,
    StudioService,
    _check_data_size,
    _extract_config_summary,
    _validate_config_type,
    _validate_name,
)

# Patch target for lazy imports of get_session and get_db_model
_PATCH_GET_SESSION = "temper_ai.storage.database.manager.get_session"
_PATCH_GET_DB_MODEL = (
    "temper_ai.interfaces.dashboard._studio_validation_helpers.get_db_model"
)


class TestValidateName:
    def test_valid(self):
        _validate_name("my-config_1")

    def test_empty(self):
        with pytest.raises(ValueError):
            _validate_name("")

    def test_invalid_chars(self):
        with pytest.raises(ValueError):
            _validate_name("bad name!")


class TestValidateConfigType:
    def test_valid(self):
        for t in VALID_CONFIG_TYPES:
            _validate_config_type(t)

    def test_invalid(self):
        with pytest.raises(ValueError):
            _validate_config_type("invalid_type")


class TestCheckDataSize:
    def test_small_data(self):
        _check_data_size({"key": "value"})

    def test_oversized_data(self):
        with pytest.raises(ValueError, match="too large"):
            _check_data_size({"key": "x" * (MAX_CONFIG_SIZE_BYTES + 1)})


class TestExtractConfigSummary:
    def test_with_inner_data(self):
        data = {"workflow": {"name": "test", "description": "A test", "version": "1.0"}}
        result = _extract_config_summary(data, "workflow")
        assert result["name"] == "test"
        assert result["description"] == "A test"

    def test_missing_wrapper(self):
        result = _extract_config_summary({}, "workflow")
        assert result["name"] == ""
        assert result["description"] == ""


class TestStudioServiceFileOps:
    def test_list_configs_empty(self, tmp_path):
        (tmp_path / "workflows").mkdir()
        svc = StudioService(config_root=str(tmp_path))
        result = svc.list_configs("workflows")
        assert result["total"] == 0

    def test_get_config_invalid_name(self, tmp_path):
        svc = StudioService(config_root=str(tmp_path))
        with pytest.raises(ValueError):
            svc.get_config("workflows", "bad name!")

    def test_get_config_raw_not_found(self, tmp_path):
        (tmp_path / "workflows").mkdir()
        svc = StudioService(config_root=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            svc.get_config_raw("workflows", "nonexistent")

    def test_create_config_already_exists(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "existing.yaml").write_text("workflow:\n  name: existing")
        svc = StudioService(config_root=str(tmp_path))
        with pytest.raises(FileExistsError):
            svc.create_config(
                "workflows", "existing", {"workflow": {"name": "existing"}}
            )

    def test_update_config_not_found(self, tmp_path):
        (tmp_path / "workflows").mkdir()
        svc = StudioService(config_root=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            svc.update_config("workflows", "missing", {"workflow": {"name": "test"}})

    def test_delete_config_not_found(self, tmp_path):
        (tmp_path / "workflows").mkdir()
        svc = StudioService(config_root=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            svc.delete_config("workflows", "missing")

    def test_validate_config_valid(self, tmp_path):
        svc = StudioService(config_root=str(tmp_path))
        result = svc.validate_config(
            "workflows", {"workflow": {"name": "test", "stages": []}}
        )
        assert "valid" in result
        assert "errors" in result

    def test_validate_config_invalid(self, tmp_path):
        svc = StudioService(config_root=str(tmp_path))
        result = svc.validate_config("workflows", {})
        assert isinstance(result["errors"], list)

    def test_get_schema(self, tmp_path):
        svc = StudioService(config_root=str(tmp_path))
        schema = svc.get_schema("workflows")
        assert isinstance(schema, dict)

    def test_use_db_property(self, tmp_path):
        svc = StudioService(config_root=str(tmp_path), use_db=True)
        assert svc.use_db is True

        svc2 = StudioService(config_root=str(tmp_path), use_db=False)
        assert svc2.use_db is False


def _mock_session_context(session_mock):
    """Helper to create a proper context manager mock for get_session."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=session_mock)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


class TestStudioServiceDBMethods:
    @patch(_PATCH_GET_DB_MODEL)
    @patch(_PATCH_GET_SESSION)
    def test_list_configs_db(self, mock_get_session, mock_get_model):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        mock_session = MagicMock()
        mock_session.exec.return_value.all.return_value = [
            ("config1", 1, "desc1"),
        ]
        mock_get_session.return_value = _mock_session_context(mock_session)

        svc = StudioService(config_root="/tmp", use_db=True)
        result = svc.list_configs_db("workflows", "test-tenant")
        assert result["total"] == 1
        assert result["configs"][0]["name"] == "config1"

    @patch(_PATCH_GET_DB_MODEL)
    @patch(_PATCH_GET_SESSION)
    def test_get_config_db_found(self, mock_get_session, mock_get_model):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = {"data": "test"}
        mock_get_session.return_value = _mock_session_context(mock_session)

        svc = StudioService(config_root="/tmp", use_db=True)
        result = svc.get_config_db("workflows", "test-config", "test-tenant")
        assert result == {"data": "test"}

    @patch(_PATCH_GET_DB_MODEL)
    @patch(_PATCH_GET_SESSION)
    def test_get_config_db_not_found(self, mock_get_session, mock_get_model):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = None
        mock_get_session.return_value = _mock_session_context(mock_session)

        svc = StudioService(config_root="/tmp", use_db=True)
        with pytest.raises(FileNotFoundError):
            svc.get_config_db("workflows", "missing", "test-tenant")

    @patch(_PATCH_GET_DB_MODEL)
    @patch(_PATCH_GET_SESSION)
    def test_create_config_db_exists(self, mock_get_session, mock_get_model):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = "existing"
        mock_get_session.return_value = _mock_session_context(mock_session)

        svc = StudioService(config_root="/tmp", use_db=True)
        with patch.object(
            svc, "validate_config", return_value={"valid": True, "errors": []}
        ):
            with pytest.raises(FileExistsError):
                svc.create_config_db("workflows", "test", {}, "tenant1", "user1")

    def test_create_config_db_validation_fails(self):
        svc = StudioService(config_root="/tmp", use_db=True)
        with patch.object(
            svc,
            "validate_config",
            return_value={"valid": False, "errors": ["name: required"]},
        ):
            with pytest.raises(ValueError, match="validation failed"):
                svc.create_config_db("workflows", "test", {}, "tenant1", "user1")

    @patch(_PATCH_GET_DB_MODEL)
    @patch(_PATCH_GET_SESSION)
    def test_create_config_db_success(self, mock_get_session, mock_get_model):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = None
        mock_get_session.return_value = _mock_session_context(mock_session)

        svc = StudioService(config_root="/tmp", use_db=True)
        data = {"workflow": {"name": "test"}}
        with patch.object(
            svc, "validate_config", return_value={"valid": True, "errors": []}
        ):
            result = svc.create_config_db("workflows", "test", data, "tenant1", "user1")
        assert result == data

    @patch(_PATCH_GET_DB_MODEL)
    @patch(_PATCH_GET_SESSION)
    def test_update_config_db_not_found(self, mock_get_session, mock_get_model):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = None
        mock_get_session.return_value = _mock_session_context(mock_session)

        svc = StudioService(config_root="/tmp", use_db=True)
        with patch.object(
            svc, "validate_config", return_value={"valid": True, "errors": []}
        ):
            with pytest.raises(FileNotFoundError):
                svc.update_config_db("workflows", "missing", {}, "tenant1", "user1")

    def test_update_config_db_validation_fails(self):
        svc = StudioService(config_root="/tmp", use_db=True)
        with patch.object(
            svc,
            "validate_config",
            return_value={"valid": False, "errors": ["bad field"]},
        ):
            with pytest.raises(ValueError, match="validation failed"):
                svc.update_config_db("workflows", "test", {}, "tenant1", "user1")

    @patch(_PATCH_GET_DB_MODEL)
    @patch(_PATCH_GET_SESSION)
    def test_update_config_db_success(self, mock_get_session, mock_get_model):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        record = MagicMock()
        record.version = 1
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = record
        mock_get_session.return_value = _mock_session_context(mock_session)

        svc = StudioService(config_root="/tmp", use_db=True)
        with patch.object(
            svc, "validate_config", return_value={"valid": True, "errors": []}
        ):
            result = svc.update_config_db(
                "workflows", "test", {"data": "new"}, "tenant1", "user1"
            )
        assert result == {"data": "new"}

    @patch(_PATCH_GET_DB_MODEL)
    @patch(_PATCH_GET_SESSION)
    def test_delete_config_db_not_found(self, mock_get_session, mock_get_model):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = None
        mock_get_session.return_value = _mock_session_context(mock_session)

        svc = StudioService(config_root="/tmp", use_db=True)
        with pytest.raises(FileNotFoundError):
            svc.delete_config_db("workflows", "missing", "tenant1")

    @patch(_PATCH_GET_DB_MODEL)
    @patch(_PATCH_GET_SESSION)
    def test_delete_config_db_success(self, mock_get_session, mock_get_model):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model
        record = MagicMock()
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = record
        mock_get_session.return_value = _mock_session_context(mock_session)

        svc = StudioService(config_root="/tmp", use_db=True)
        result = svc.delete_config_db("workflows", "test", "tenant1")
        assert "deleted" in result
