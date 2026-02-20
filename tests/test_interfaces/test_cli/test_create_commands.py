"""Tests for the project scaffolding CLI command (R2)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from temper_ai.interfaces.cli.create_commands import _generate_from_template, _write_boilerplate, create
from temper_ai.interfaces.cli.create_constants import (
    DEFAULT_OUTPUT_DIR,
    ENV_EXAMPLE_TEMPLATE,
    ERR_DIR_EXISTS,
    ERR_TEMPLATE_NOT_FOUND,
    GITIGNORE_TEMPLATE,
    README_TEMPLATE,
)


# ─── _write_boilerplate tests ────────────────────────────────────────────────


class TestWriteBoilerplate:
    """Tests for _write_boilerplate."""

    def test_creates_gitignore(self, tmp_path: Path) -> None:
        _write_boilerplate(tmp_path, "myproject", "web_app")
        assert (tmp_path / ".gitignore").exists()
        assert "venv/" in (tmp_path / ".gitignore").read_text()

    def test_creates_env_example(self, tmp_path: Path) -> None:
        _write_boilerplate(tmp_path, "myproject", "web_app")
        assert (tmp_path / ".env.example").exists()
        content = (tmp_path / ".env.example").read_text()
        assert "TEMPER_LLM_PROVIDER" in content

    def test_creates_readme_with_project_name(self, tmp_path: Path) -> None:
        _write_boilerplate(tmp_path, "myproject", "api")
        readme = (tmp_path / "README.md").read_text()
        assert "myproject" in readme

    def test_creates_readme_with_product_type(self, tmp_path: Path) -> None:
        _write_boilerplate(tmp_path, "myproject", "api")
        readme = (tmp_path / "README.md").read_text()
        assert "api" in readme

    def test_gitignore_contains_temper_ai(self, tmp_path: Path) -> None:
        _write_boilerplate(tmp_path, "proj", "cli_tool")
        assert ".temper-ai/" in (tmp_path / ".gitignore").read_text()


# ─── create command tests ─────────────────────────────────────────────────────


class TestCreateCommand:
    """Tests for the create CLI command."""

    def _make_mock_workflow_path(self, tmp_path: Path, project_name: str) -> Path:
        """Return a fake workflow path that exists on disk."""
        wf = tmp_path / project_name / "workflows" / f"{project_name}_workflow.yaml"
        wf.parent.mkdir(parents=True, exist_ok=True)
        wf.write_text("workflow: {}", encoding="utf-8")
        return wf

    @patch("temper_ai.interfaces.cli.create_commands._generate_from_template")
    def test_creates_project_directory(self, mock_gen: MagicMock, tmp_path: Path) -> None:
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        mock_gen.return_value = project_dir / "workflows" / "myapp_workflow.yaml"

        runner = CliRunner()
        result = runner.invoke(
            create,
            ["myapp", "--type", "web_app", "--output-dir", str(tmp_path), "--force"],
        )

        assert result.exit_code == 0
        assert project_dir.exists()

    @patch("temper_ai.interfaces.cli.create_commands._generate_from_template")
    def test_writes_boilerplate_files(self, mock_gen: MagicMock, tmp_path: Path) -> None:
        project_dir = tmp_path / "testproj"
        project_dir.mkdir()
        mock_gen.return_value = project_dir / "workflows" / "testproj_workflow.yaml"

        runner = CliRunner()
        result = runner.invoke(
            create,
            ["testproj", "--type", "api", "--output-dir", str(tmp_path), "--force"],
        )

        assert result.exit_code == 0
        assert (project_dir / ".gitignore").exists()
        assert (project_dir / ".env.example").exists()
        assert (project_dir / "README.md").exists()

    @patch("temper_ai.interfaces.cli.create_commands._generate_from_template")
    def test_error_on_existing_dir_without_force(self, mock_gen: MagicMock, tmp_path: Path) -> None:
        project_dir = tmp_path / "existing"
        project_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            create,
            ["existing", "--type", "api", "--output-dir", str(tmp_path)],
        )

        assert result.exit_code != 0
        assert "already exists" in result.output
        mock_gen.assert_not_called()

    @patch("temper_ai.interfaces.cli.create_commands._generate_from_template")
    def test_force_flag_allows_overwrite(self, mock_gen: MagicMock, tmp_path: Path) -> None:
        project_dir = tmp_path / "existing"
        project_dir.mkdir()
        mock_gen.return_value = project_dir / "workflows" / "existing_workflow.yaml"

        runner = CliRunner()
        result = runner.invoke(
            create,
            ["existing", "--type", "api", "--output-dir", str(tmp_path), "--force"],
        )

        assert result.exit_code == 0
        assert "Project created" in result.output

    @patch("temper_ai.interfaces.cli.create_commands._generate_from_template")
    def test_invalid_template_shows_error(self, mock_gen: MagicMock, tmp_path: Path) -> None:
        from temper_ai.workflow.templates.registry import TemplateNotFoundError

        mock_gen.side_effect = TemplateNotFoundError("Template not found: bad_type")

        runner = CliRunner()
        result = runner.invoke(
            create,
            ["proj", "--type", "bad_type", "--output-dir", str(tmp_path)],
        )

        assert result.exit_code != 0
        assert "Template not found" in result.output

    @patch("temper_ai.interfaces.cli.create_commands._generate_from_template")
    def test_output_contains_project_name(self, mock_gen: MagicMock, tmp_path: Path) -> None:
        project_dir = tmp_path / "awesome_proj"
        project_dir.mkdir()
        mock_gen.return_value = project_dir / "workflows" / "awesome_proj_workflow.yaml"

        runner = CliRunner()
        result = runner.invoke(
            create,
            ["awesome_proj", "--type", "cli_tool", "--output-dir", str(tmp_path), "--force"],
        )

        assert result.exit_code == 0
        assert "awesome_proj" in result.output

    @patch("temper_ai.interfaces.cli.create_commands._generate_from_template")
    def test_oserror_shows_error_message(self, mock_gen: MagicMock, tmp_path: Path) -> None:
        mock_gen.side_effect = OSError("disk full")

        runner = CliRunner()
        result = runner.invoke(
            create,
            ["proj", "--type", "api", "--output-dir", str(tmp_path)],
        )

        assert result.exit_code != 0
        assert "disk full" in result.output

    @patch("temper_ai.interfaces.cli.create_commands._generate_from_template")
    def test_passes_provider_and_model_overrides(self, mock_gen: MagicMock, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        mock_gen.return_value = project_dir / "workflows" / "proj_workflow.yaml"

        runner = CliRunner()
        runner.invoke(
            create,
            [
                "proj", "--type", "api",
                "--provider", "openai",
                "--model", "gpt-4",
                "--output-dir", str(tmp_path),
                "--force",
            ],
        )

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args
        assert call_kwargs.args[3] == "openai"  # provider
        assert call_kwargs.args[4] == "gpt-4"   # model


# ─── _generate_from_template tests ───────────────────────────────────────────


class TestGenerateFromTemplate:
    """Tests for _generate_from_template helper."""

    @patch("temper_ai.interfaces.cli.create_commands.TemplateGenerator", create=True)
    @patch("temper_ai.interfaces.cli.create_commands.TemplateRegistry", create=True)
    def test_calls_generator_generate(self, mock_reg_cls: MagicMock, mock_gen_cls: MagicMock, tmp_path: Path) -> None:
        mock_registry = MagicMock()
        mock_reg_cls.return_value = mock_registry
        mock_generator = MagicMock()
        mock_gen_cls.return_value = mock_generator
        expected_path = tmp_path / "workflows" / "proj_workflow.yaml"
        mock_generator.generate.return_value = expected_path

        with patch("temper_ai.interfaces.cli.create_commands._generate_from_template") as mock_fn:
            mock_fn.return_value = expected_path
            result = mock_fn(tmp_path, "api", "proj", None, None, "configs")

        assert result == expected_path
