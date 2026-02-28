"""Tests for temper_ai/workflow/db_config_loader.py.

Covers:
- _load_config: found/not found
- DBConfigLoader.load_workflow: happy path
- DBConfigLoader.load_stage: with/without validation
- DBConfigLoader.load_agent: with/without validation
- DBConfigLoader.list_configs: valid types, unknown type raises
- _list_names: returns name list
"""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.storage.database.models_tenancy import (
    StageConfigDB,
    WorkflowConfigDB,
)
from temper_ai.workflow.db_config_loader import (
    DBConfigLoader,
    _list_names,
    _load_config,
)


@pytest.fixture
def mock_session():
    """Create a mock DB session context manager."""
    session = MagicMock()
    return session


@pytest.fixture
def mock_get_session(mock_session):
    """Patch get_session to return mock session."""
    with patch("temper_ai.workflow.db_config_loader.get_session") as mock_gs:
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_gs, mock_session


# ============================================================================
# _load_config
# ============================================================================


class TestLoadConfig:
    """Tests for _load_config — DB query and error handling."""

    def test_found_returns_config_data(self, mock_get_session):
        """Returns config_data dict when record is found."""
        _, session = mock_get_session
        record = MagicMock()
        record.config_data = {"workflow": {"name": "test"}}
        session.exec.return_value.first.return_value = record

        result = _load_config("tenant-1", WorkflowConfigDB, "my_wf")
        assert result == {"workflow": {"name": "test"}}

    def test_not_found_raises_file_not_found(self, mock_get_session):
        """Raises FileNotFoundError when no record matches."""
        _, session = mock_get_session
        session.exec.return_value.first.return_value = None

        with pytest.raises(FileNotFoundError, match="not found for tenant"):
            _load_config("tenant-1", WorkflowConfigDB, "missing_wf")


# ============================================================================
# _list_names
# ============================================================================


class TestListNames:
    """Tests for _list_names — returns list of config names."""

    def test_returns_names_list(self, mock_get_session):
        """Returns list of name strings."""
        _, session = mock_get_session
        session.exec.return_value.all.return_value = ["wf1", "wf2"]

        result = _list_names("tenant-1", WorkflowConfigDB)
        assert result == ["wf1", "wf2"]

    def test_empty_result(self, mock_get_session):
        """Returns empty list when no configs exist."""
        _, session = mock_get_session
        session.exec.return_value.all.return_value = []

        result = _list_names("tenant-1", StageConfigDB)
        assert result == []


# ============================================================================
# DBConfigLoader
# ============================================================================


class TestDBConfigLoader:
    """Tests for DBConfigLoader class methods."""

    def test_init_stores_tenant_id(self):
        """Constructor stores tenant_id."""
        loader = DBConfigLoader("tenant-abc")
        assert loader._tenant_id == "tenant-abc"

    @patch("temper_ai.workflow.db_config_loader._load_config")
    def test_load_workflow(self, mock_load):
        """load_workflow delegates to _load_config with WorkflowConfigDB."""
        mock_load.return_value = {"workflow": {"name": "wf1"}}
        loader = DBConfigLoader("t1")
        result = loader.load_workflow("wf1")
        assert result == {"workflow": {"name": "wf1"}}
        mock_load.assert_called_once()

    @patch("temper_ai.workflow.db_config_loader._load_config")
    def test_load_stage_without_validation(self, mock_load):
        """load_stage with validate=False skips Pydantic check."""
        mock_load.return_value = {"stage": {"name": "s1"}}
        loader = DBConfigLoader("t1")
        result = loader.load_stage("s1", validate=False)
        assert result == {"stage": {"name": "s1"}}

    @patch("temper_ai.workflow.db_config_loader._load_config")
    def test_load_stage_with_validation(self, mock_load):
        """load_stage with validate=True calls _validate_with_pydantic."""
        mock_load.return_value = {"stage": {"name": "s1"}}
        loader = DBConfigLoader("t1")
        with patch(
            "temper_ai.auth.config_sync._validate_with_pydantic"
        ) as mock_validate:
            result = loader.load_stage("s1", validate=True)
            mock_validate.assert_called_once_with("stage", result)

    @patch("temper_ai.workflow.db_config_loader._load_config")
    def test_load_agent_without_validation(self, mock_load):
        """load_agent with validate=False skips Pydantic check."""
        mock_load.return_value = {"agent": {"name": "a1"}}
        loader = DBConfigLoader("t1")
        result = loader.load_agent("a1", validate=False)
        assert result == {"agent": {"name": "a1"}}

    @patch("temper_ai.workflow.db_config_loader._load_config")
    def test_load_agent_with_validation(self, mock_load):
        """load_agent with validate=True calls _validate_with_pydantic."""
        mock_load.return_value = {"agent": {"name": "a1"}}
        loader = DBConfigLoader("t1")
        with patch(
            "temper_ai.auth.config_sync._validate_with_pydantic"
        ) as mock_validate:
            result = loader.load_agent("a1", validate=True)
            mock_validate.assert_called_once_with("agent", result)

    def test_list_configs_unknown_type_raises(self):
        """Unknown config_type raises ValueError."""
        loader = DBConfigLoader("t1")
        with pytest.raises(ValueError, match="Unknown config_type"):
            loader.list_configs("invalid_type")

    @patch("temper_ai.workflow.db_config_loader._list_names")
    def test_list_configs_workflow(self, mock_list):
        """list_configs('workflow') delegates to _list_names."""
        mock_list.return_value = ["wf1", "wf2"]
        loader = DBConfigLoader("t1")
        result = loader.list_configs("workflow")
        assert result == ["wf1", "wf2"]

    @patch("temper_ai.workflow.db_config_loader._list_names")
    def test_list_configs_stage(self, mock_list):
        """list_configs('stage') delegates to _list_names."""
        mock_list.return_value = ["s1"]
        loader = DBConfigLoader("t1")
        result = loader.list_configs("stage")
        assert result == ["s1"]

    @patch("temper_ai.workflow.db_config_loader._list_names")
    def test_list_configs_agent(self, mock_list):
        """list_configs('agent') delegates to _list_names."""
        mock_list.return_value = ["a1", "a2"]
        loader = DBConfigLoader("t1")
        result = loader.list_configs("agent")
        assert result == ["a1", "a2"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
