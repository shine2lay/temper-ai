"""Tests for lifecycle CLI commands."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from temper_ai.interfaces.cli.lifecycle_commands import lifecycle_group


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def config_dir(tmp_path):
    profile_file = tmp_path / "lean.yaml"
    profile_file.write_text(
        "name: lean\n"
        "description: Lean profile\n"
        "rules:\n"
        "  - name: skip_design\n"
        "    action: skip\n"
        "    stage_name: design\n"
        "    condition: \"{{ size == 'small' }}\"\n"
        "enabled: true\n"
    )
    return tmp_path


@pytest.fixture
def workflow_file(tmp_path):
    wf = tmp_path / "test.yaml"
    wf.write_text(
        "workflow:\n"
        "  name: test\n"
        "  lifecycle:\n"
        "    enabled: true\n"
        "    profile: lean\n"
        "  stages:\n"
        "    - name: design\n"
        "      stage_ref: stages/design.yaml\n"
        "    - name: implement\n"
        "      stage_ref: stages/impl.yaml\n"
    )
    return str(wf)


@pytest.fixture
def input_file(tmp_path):
    inp = tmp_path / "input.yaml"
    inp.write_text(
        "size: small\nrisk_level: low\n"
    )
    return str(inp)


class TestLifecycleProfiles:
    def test_profiles_list(self, runner, config_dir):
        result = runner.invoke(
            lifecycle_group,
            ["profiles", "list", "--config-dir", str(config_dir),
             "--db", "sqlite:///:memory:"],
        )
        assert result.exit_code == 0
        assert "lean" in result.output

    def test_profiles_show(self, runner, config_dir):
        result = runner.invoke(
            lifecycle_group,
            ["profiles", "show", "lean", "--config-dir", str(config_dir),
             "--db", "sqlite:///:memory:"],
        )
        assert result.exit_code == 0
        assert "skip_design" in result.output

    def test_profiles_show_missing(self, runner, config_dir):
        result = runner.invoke(
            lifecycle_group,
            ["profiles", "show", "nonexistent",
             "--config-dir", str(config_dir),
             "--db", "sqlite:///:memory:"],
        )
        assert result.exit_code != 0


class TestLifecycleClassify:
    def test_classify(self, runner, workflow_file, input_file):
        result = runner.invoke(
            lifecycle_group,
            ["classify", workflow_file, "--input", input_file],
        )
        assert result.exit_code == 0
        assert "small" in result.output


class TestLifecycleHistory:
    def test_history_empty(self, runner):
        result = runner.invoke(
            lifecycle_group,
            ["history", "--db", "sqlite:///:memory:"],
        )
        assert result.exit_code == 0
        assert "No adaptation records" in result.output
