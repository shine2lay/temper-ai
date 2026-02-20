"""Tests for the `temper-ai visualize` CLI command (R3)."""
import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from temper_ai.interfaces.cli.visualize_commands import visualize

MINIMAL_WORKFLOW = textwrap.dedent("""\
    workflow:
      name: test_workflow
      stages:
        - name: stage_a
          stage_ref: stages/a.yaml
        - name: stage_b
          stage_ref: stages/b.yaml
          depends_on: [stage_a]
""")


@pytest.fixture()
def workflow_file(tmp_path: Path) -> Path:
    f = tmp_path / "workflow.yaml"
    f.write_text(MINIMAL_WORKFLOW, encoding="utf-8")
    return f


class TestVisualizeCommand:
    def test_visualize_ascii(self, workflow_file: Path):
        runner = CliRunner()
        result = runner.invoke(visualize, [str(workflow_file)])
        assert result.exit_code == 0
        assert "stage_a" in result.output
        assert "stage_b" in result.output

    def test_visualize_mermaid_format(self, workflow_file: Path):
        runner = CliRunner()
        result = runner.invoke(visualize, [str(workflow_file), "--format", "mermaid"])
        assert result.exit_code == 0
        assert "graph TD" in result.output
        assert "stage_a --> stage_b" in result.output

    def test_visualize_dot_format(self, workflow_file: Path):
        runner = CliRunner()
        result = runner.invoke(visualize, [str(workflow_file), "--format", "dot"])
        assert result.exit_code == 0
        assert "digraph workflow" in result.output
        assert "stage_a" in result.output

    def test_visualize_output_file(self, workflow_file: Path, tmp_path: Path):
        out_file = tmp_path / "dag.md"
        runner = CliRunner()
        result = runner.invoke(
            visualize,
            [str(workflow_file), "--format", "mermaid", "--output", str(out_file)],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        content = out_file.read_text()
        assert "graph TD" in content

    def test_visualize_invalid_path(self):
        runner = CliRunner()
        result = runner.invoke(visualize, ["/nonexistent/path/workflow.yaml"])
        assert result.exit_code != 0

    def test_visualize_invalid_yaml(self, tmp_path: Path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("{{ invalid: yaml: [", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(visualize, [str(bad_yaml)])
        assert result.exit_code != 0

    def test_visualize_missing_workflow_key(self, tmp_path: Path):
        no_workflow = tmp_path / "empty.yaml"
        no_workflow.write_text("other_key: value\n", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(visualize, [str(no_workflow)])
        assert result.exit_code != 0
