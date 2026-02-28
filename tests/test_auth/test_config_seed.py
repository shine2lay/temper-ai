"""Tests for temper_ai/auth/config_seed.py."""

from unittest.mock import MagicMock, patch

from temper_ai.auth.config_seed import (
    _SUBDIR_TO_CONFIG_TYPE,
    _read_yaml_file,
    _seed_directory,
    seed_configs,
)

TENANT_ID = "tenant-abc"
USER_ID = "user-xyz"


# --- _read_yaml_file ---


def test_read_yaml_file_returns_content(tmp_path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("key: value\n", encoding="utf-8")
    assert _read_yaml_file(yaml_file) == "key: value\n"


def test_read_yaml_file_multiline(tmp_path):
    content = "name: test\nstages: []\ndescription: hello\n"
    yaml_file = tmp_path / "multi.yaml"
    yaml_file.write_text(content, encoding="utf-8")
    assert _read_yaml_file(yaml_file) == content


# --- _seed_directory ---


def test_seed_directory_nonexistent_returns_zero(tmp_path):
    sync_service = MagicMock()
    errors: list[str] = []
    result = _seed_directory(
        sync_service=sync_service,
        directory=tmp_path / "nonexistent",
        config_type="workflow",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        errors=errors,
    )
    assert result == 0
    assert errors == []
    sync_service.import_config.assert_not_called()


def test_seed_directory_empty_dir_returns_zero(tmp_path):
    sync_service = MagicMock()
    errors: list[str] = []
    result = _seed_directory(
        sync_service=sync_service,
        directory=tmp_path,
        config_type="workflow",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        errors=errors,
    )
    assert result == 0
    assert errors == []


def test_seed_directory_seeds_yaml_files(tmp_path):
    (tmp_path / "wf1.yaml").write_text("name: wf1\n")
    (tmp_path / "wf2.yaml").write_text("name: wf2\n")
    (tmp_path / "notes.txt").write_text("ignored")
    sync_service = MagicMock()
    errors: list[str] = []

    result = _seed_directory(
        sync_service=sync_service,
        directory=tmp_path,
        config_type="workflow",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        errors=errors,
    )

    assert result == 2
    assert errors == []
    assert sync_service.import_config.call_count == 2


def test_seed_directory_passes_correct_args(tmp_path):
    (tmp_path / "myconfig.yaml").write_text("name: myconfig\n")
    sync_service = MagicMock()
    errors: list[str] = []

    _seed_directory(
        sync_service=sync_service,
        directory=tmp_path,
        config_type="agent",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        errors=errors,
    )

    sync_service.import_config.assert_called_once_with(
        tenant_id=TENANT_ID,
        config_type="agent",
        name="myconfig",
        yaml_content="name: myconfig\n",
        user_id=USER_ID,
    )


def test_seed_directory_catches_value_error(tmp_path):
    (tmp_path / "bad.yaml").write_text("x: 1\n")
    sync_service = MagicMock()
    sync_service.import_config.side_effect = ValueError("bad config")
    errors: list[str] = []

    result = _seed_directory(
        sync_service=sync_service,
        directory=tmp_path,
        config_type="workflow",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        errors=errors,
    )

    assert result == 0
    assert len(errors) == 1
    assert "workflow/bad" in errors[0]


def test_seed_directory_catches_oserror(tmp_path):
    (tmp_path / "file.yaml").write_text("x: 1\n")
    sync_service = MagicMock()
    sync_service.import_config.side_effect = OSError("disk error")
    errors: list[str] = []

    result = _seed_directory(
        sync_service=sync_service,
        directory=tmp_path,
        config_type="stage",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        errors=errors,
    )

    assert result == 0
    assert len(errors) == 1


def test_seed_directory_partial_success(tmp_path):
    """One file succeeds, one raises ValueError."""
    (tmp_path / "good.yaml").write_text("name: good\n")
    (tmp_path / "bad.yaml").write_text("name: bad\n")

    call_count = 0

    def import_side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if kwargs["name"] == "bad":
            raise ValueError("failed")

    sync_service = MagicMock()
    sync_service.import_config.side_effect = import_side_effect
    errors: list[str] = []

    result = _seed_directory(
        sync_service=sync_service,
        directory=tmp_path,
        config_type="workflow",
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        errors=errors,
    )

    assert result == 1
    assert len(errors) == 1


# --- seed_configs ---


def test_seed_configs_returns_dict_structure(tmp_path):
    with patch(
        "temper_ai.auth.config_seed.ConfigSyncService", return_value=MagicMock()
    ):
        result = seed_configs(str(tmp_path), TENANT_ID, USER_ID)

    assert "workflows" in result
    assert "stages" in result
    assert "agents" in result
    assert "errors" in result
    assert isinstance(result["errors"], list)


def test_seed_configs_counts_workflow_files(tmp_path):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "a.yaml").write_text("name: a\n")
    (wf_dir / "b.yaml").write_text("name: b\n")

    mock_svc = MagicMock()
    with patch("temper_ai.auth.config_seed.ConfigSyncService", return_value=mock_svc):
        result = seed_configs(str(tmp_path), TENANT_ID, USER_ID)

    assert result["workflows"] == 2
    assert result["stages"] == 0
    assert result["agents"] == 0


def test_seed_configs_errors_collected(tmp_path):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "bad.yaml").write_text("x: 1\n")

    mock_svc = MagicMock()
    mock_svc.import_config.side_effect = ValueError("boom")
    with patch("temper_ai.auth.config_seed.ConfigSyncService", return_value=mock_svc):
        result = seed_configs(str(tmp_path), TENANT_ID, USER_ID)

    assert len(result["errors"]) == 1
    assert result["workflows"] == 0


# --- _SUBDIR_TO_CONFIG_TYPE ---


def test_subdir_to_config_type_mapping():
    assert _SUBDIR_TO_CONFIG_TYPE["workflows"] == "workflow"
    assert _SUBDIR_TO_CONFIG_TYPE["stages"] == "stage"
    assert _SUBDIR_TO_CONFIG_TYPE["agents"] == "agent"
    assert len(_SUBDIR_TO_CONFIG_TYPE) == 3
