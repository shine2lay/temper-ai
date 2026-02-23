"""Tests for temper_ai/auth/config_sync.py — ConfigSyncService."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.auth.config_sync import ConfigSyncService

# Minimal valid workflow YAML matching WorkflowConfig schema
VALID_WORKFLOW_YAML = """
name: test-workflow
description: "A test workflow"
stages: []
"""

# Minimal valid agent YAML matching AgentConfig schema
VALID_AGENT_YAML = """
name: test-agent
system_prompt: "You are helpful."
"""

# Minimal valid stage YAML matching StageConfig schema
VALID_STAGE_YAML = """
name: test-stage
agent: test-agent
"""

INVALID_YAML = ": : : bad yaml ["

TENANT_ID = "tenant-abc-123"
USER_ID = "user-xyz-456"


def _make_utcnow() -> datetime:
    return datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _make_record(name: str, version: int = 1) -> MagicMock:
    """Create a mock config DB record."""
    rec = MagicMock()
    rec.name = name
    rec.version = version
    rec.config_data = {"name": name}
    rec.created_at = _make_utcnow()
    rec.updated_at = _make_utcnow()
    return rec


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def service() -> ConfigSyncService:
    return ConfigSyncService()


@pytest.fixture
def mock_session():
    """Context-manager-compatible mock session."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return session, ctx


# ── import_config ─────────────────────────────────────────────────────


def test_import_config_valid_workflow(service, mock_session):
    session, ctx = mock_session
    # No existing record — new creation path
    session.query.return_value.filter_by.return_value.first.return_value = None

    with (
        patch("temper_ai.auth.config_sync.get_session", return_value=ctx),
        patch("temper_ai.auth.config_sync._validate_with_pydantic"),
    ):
        result = service.import_config(
            tenant_id=TENANT_ID,
            config_type="workflow",
            name="my-workflow",
            yaml_content=VALID_WORKFLOW_YAML,
            user_id=USER_ID,
        )

    assert result["name"] == "my-workflow"
    assert result["config_type"] == "workflow"
    assert result["version"] == 1
    session.add.assert_called_once()


def test_import_config_invalid_yaml(service):
    with pytest.raises(ValueError, match="Invalid YAML"):
        service.import_config(
            tenant_id=TENANT_ID,
            config_type="workflow",
            name="bad-workflow",
            yaml_content=INVALID_YAML,
            user_id=USER_ID,
        )


def test_import_config_invalid_type(service):
    with pytest.raises(ValueError, match="Invalid config_type"):
        service.import_config(
            tenant_id=TENANT_ID,
            config_type="unknown_type",
            name="whatever",
            yaml_content=VALID_WORKFLOW_YAML,
            user_id=USER_ID,
        )


def test_import_config_update_existing(service, mock_session):
    session, ctx = mock_session
    existing = _make_record("my-workflow", version=2)
    session.query.return_value.filter_by.return_value.first.return_value = existing

    with (
        patch("temper_ai.auth.config_sync.get_session", return_value=ctx),
        patch("temper_ai.auth.config_sync._validate_with_pydantic"),
        patch("temper_ai.auth.config_sync.utcnow", return_value=_make_utcnow()),
    ):
        result = service.import_config(
            tenant_id=TENANT_ID,
            config_type="workflow",
            name="my-workflow",
            yaml_content=VALID_WORKFLOW_YAML,
            user_id=USER_ID,
        )

    assert result["version"] == 3  # 2 + 1
    assert result["name"] == "my-workflow"
    # The existing record was mutated (not a new add)
    session.add.assert_not_called()


def test_import_config_non_dict_yaml(service):
    """YAML that parses to a non-dict raises ValueError."""
    with pytest.raises(ValueError, match="mapping"):
        service.import_config(
            tenant_id=TENANT_ID,
            config_type="workflow",
            name="list-config",
            yaml_content="- item1\n- item2\n",
            user_id=USER_ID,
        )


# ── export_config ─────────────────────────────────────────────────────


def test_export_config_found(service, mock_session):
    session, ctx = mock_session
    record = _make_record("my-workflow")
    record.config_data = {"name": "my-workflow", "stages": []}
    session.query.return_value.filter_by.return_value.first.return_value = record

    with patch("temper_ai.auth.config_sync.get_session", return_value=ctx):
        yaml_str = service.export_config(
            tenant_id=TENANT_ID,
            config_type="workflow",
            name="my-workflow",
        )

    assert isinstance(yaml_str, str)
    assert "my-workflow" in yaml_str


def test_export_config_not_found(service, mock_session):
    session, ctx = mock_session
    session.query.return_value.filter_by.return_value.first.return_value = None

    with patch("temper_ai.auth.config_sync.get_session", return_value=ctx):
        with pytest.raises(FileNotFoundError, match="not found"):
            service.export_config(
                tenant_id=TENANT_ID,
                config_type="workflow",
                name="nonexistent",
            )


def test_export_config_invalid_type(service):
    with pytest.raises(ValueError, match="Invalid config_type"):
        service.export_config(
            tenant_id=TENANT_ID,
            config_type="garbage",
            name="whatever",
        )


# ── list_configs ──────────────────────────────────────────────────────


def test_list_configs_returns_names(service, mock_session):
    session, ctx = mock_session
    records = [_make_record("wf-a", 1), _make_record("wf-b", 2)]
    session.query.return_value.filter_by.return_value.all.return_value = records

    with patch("temper_ai.auth.config_sync.get_session", return_value=ctx):
        result = service.list_configs(tenant_id=TENANT_ID, config_type="workflow")

    assert result["total"] == 2
    names = [c["name"] for c in result["configs"]]
    assert "wf-a" in names
    assert "wf-b" in names


def test_list_configs_empty(service, mock_session):
    session, ctx = mock_session
    session.query.return_value.filter_by.return_value.all.return_value = []

    with patch("temper_ai.auth.config_sync.get_session", return_value=ctx):
        result = service.list_configs(tenant_id=TENANT_ID, config_type="agent")

    assert result["total"] == 0
    assert result["configs"] == []


def test_list_configs_invalid_type(service):
    with pytest.raises(ValueError, match="Invalid config_type"):
        service.list_configs(tenant_id=TENANT_ID, config_type="invalid")


def test_list_configs_version_in_response(service, mock_session):
    session, ctx = mock_session
    records = [_make_record("stage-1", version=5)]
    session.query.return_value.filter_by.return_value.all.return_value = records

    with patch("temper_ai.auth.config_sync.get_session", return_value=ctx):
        result = service.list_configs(tenant_id=TENANT_ID, config_type="stage")

    assert result["configs"][0]["version"] == 5
