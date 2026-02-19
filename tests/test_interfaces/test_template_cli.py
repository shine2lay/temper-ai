"""Tests for CLI template commands."""

from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from temper_ai.interfaces.cli.template_commands import template_group

CONFIGS_DIR = Path(__file__).resolve().parent.parent.parent / "configs"


class TestTemplateList:
    """Tests for `temper-ai template list`."""

    def test_list_shows_templates(self):
        runner = CliRunner()
        result = runner.invoke(
            template_group, ["list", "--config-root", str(CONFIGS_DIR)],
        )
        assert result.exit_code == 0
        assert "api" in result.output
        assert "web_app" in result.output

    def test_list_empty_dir(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            template_group, ["list", "--config-root", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "No templates found" in result.output


class TestTemplateInfo:
    """Tests for `temper-ai template info`."""

    def test_info_shows_details(self):
        runner = CliRunner()
        result = runner.invoke(
            template_group,
            ["info", "api", "--config-root", str(CONFIGS_DIR)],
        )
        assert result.exit_code == 0
        assert "API" in result.output
        assert "Quality Gates" in result.output

    def test_info_missing_template(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            template_group,
            ["info", "nonexistent", "--config-root", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestTemplateCreate:
    """Tests for `temper-ai template create`."""

    def test_create_generates_files(self, tmp_path):
        output = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(
            template_group,
            [
                "create",
                "--type", "api",
                "--name", "myproj",
                "--output", str(output),
                "--config-root", str(CONFIGS_DIR),
            ],
        )
        assert result.exit_code == 0
        assert "Generated" in result.output

        # Verify files were created
        workflow_path = output / "workflows" / "myproj_workflow.yaml"
        assert workflow_path.exists()

    def test_create_with_inference_overrides(self, tmp_path):
        output = tmp_path / "output"
        runner = CliRunner()
        result = runner.invoke(
            template_group,
            [
                "create",
                "--type", "api",
                "--name", "myproj",
                "--output", str(output),
                "--provider", "ollama",
                "--model", "llama3",
                "--config-root", str(CONFIGS_DIR),
            ],
        )
        assert result.exit_code == 0

        # Check agent inference was overridden
        agents_dir = output / "agents"
        agent_files = list(agents_dir.glob("*.yaml"))
        assert len(agent_files) >= 1
        with open(agent_files[0]) as f:
            data = yaml.safe_load(f)
        assert data["agent"]["inference"]["provider"] == "ollama"
        assert data["agent"]["inference"]["model"] == "llama3"

    def test_create_missing_template(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            template_group,
            [
                "create",
                "--type", "nonexistent",
                "--name", "myproj",
                "--output", str(tmp_path),
                "--config-root", str(tmp_path),
            ],
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_create_default_output_uses_config_root(self, tmp_path):
        """When --output is not given, uses config-root as output dir."""
        # Copy a template into tmp_path so we don't pollute real configs
        import shutil
        templates_src = CONFIGS_DIR / "templates" / "api"
        templates_dst = tmp_path / "templates" / "api"
        shutil.copytree(templates_src, templates_dst)

        runner = CliRunner()
        result = runner.invoke(
            template_group,
            [
                "create",
                "--type", "api",
                "--name", "myproj",
                "--config-root", str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        assert "Generated" in result.output
        assert (tmp_path / "workflows" / "myproj_workflow.yaml").exists()

    def test_create_stamps_project_name(self, tmp_path):
        output = tmp_path / "output"
        runner = CliRunner()
        runner.invoke(
            template_group,
            [
                "create",
                "--type", "cli_tool",
                "--name", "awesome_tool",
                "--output", str(output),
                "--config-root", str(CONFIGS_DIR),
            ],
        )
        workflow_path = output / "workflows" / "awesome_tool_workflow.yaml"
        assert workflow_path.exists()
        with open(workflow_path) as f:
            data = yaml.safe_load(f)
        assert "awesome_tool" in data["workflow"]["name"]
        assert "{{project_name}}" not in str(data)
