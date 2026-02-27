"""
Integration tests for scripts/generate_tool_docs.py.
"""

import json
import subprocess
import sys
from pathlib import Path

# Import the script's functions directly for unit-level tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
from generate_tool_docs import (
    build_json_dump,
    check_stale,
    discover_tools,
    generate_markdown,
    render_index_markdown,
    render_tool_markdown,
)

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "generate_tool_docs.py"
)


class TestDiscoverTools:
    """Test tool discovery."""

    def test_discovers_tools(self):
        tools = discover_tools()
        assert len(tools) > 0

    def test_all_tools_are_base_tool_instances(self):
        from temper_ai.tools.base import BaseTool

        tools = discover_tools()
        for name, tool in tools.items():
            assert isinstance(tool, BaseTool), f"{name} is not a BaseTool"


class TestRenderToolMarkdown:
    """Test per-tool markdown rendering."""

    def test_contains_tool_name(self):
        tools = discover_tools()
        tool = next(iter(tools.values()))
        md = render_tool_markdown(tool)
        assert tool.get_metadata().name in md

    def test_contains_auto_generated_header(self):
        tools = discover_tools()
        tool = next(iter(tools.values()))
        md = render_tool_markdown(tool)
        assert "Auto-generated" in md

    def test_contains_parameters_section(self):
        tools = discover_tools()
        tool = next(iter(tools.values()))
        md = render_tool_markdown(tool)
        assert "## Parameters" in md

    def test_contains_yaml_config_section(self):
        tools = discover_tools()
        tool = next(iter(tools.values()))
        md = render_tool_markdown(tool)
        assert "## YAML Config" in md

    def test_contains_usage_section(self):
        tools = discover_tools()
        tool = next(iter(tools.values()))
        md = render_tool_markdown(tool)
        assert "## Usage" in md


class TestRenderIndexMarkdown:
    """Test index page rendering."""

    def test_contains_header(self):
        tools = discover_tools()
        md = render_index_markdown(tools)
        assert "# Tool Reference" in md

    def test_lists_all_tools(self):
        tools = discover_tools()
        md = render_index_markdown(tools)
        for _name, tool in tools.items():
            assert tool.get_metadata().name in md


class TestGenerateMarkdown:
    """Test markdown file generation."""

    def test_generates_files_for_all_tools(self, tmp_path):
        tools = discover_tools()
        written = generate_markdown(tmp_path, tools)

        # Should have index + one file per tool
        assert len(written) == len(tools) + 1

        # index.md should exist
        assert (tmp_path / "index.md").exists()

        # Each tool should have a file
        for name in tools:
            safe_name = name.lower().replace(" ", "_")
            assert (tmp_path / f"{safe_name}.md").exists()


class TestBuildJsonDump:
    """Test JSON output."""

    def test_has_generated_at(self):
        tools = discover_tools()
        data = build_json_dump(tools)
        assert "generated_at" in data

    def test_has_all_tools(self):
        tools = discover_tools()
        data = build_json_dump(tools)
        assert len(data["tools"]) == len(tools)

    def test_tool_has_expected_keys(self):
        tools = discover_tools()
        data = build_json_dump(tools)
        for _name, tool_data in data["tools"].items():
            assert "metadata" in tool_data
            assert "parameters_schema" in tool_data
            assert "config_schema" in tool_data
            assert "result_schema" in tool_data

    def test_json_serializable(self):
        tools = discover_tools()
        data = build_json_dump(tools)
        serialized = json.dumps(data)
        assert isinstance(serialized, str)
        assert len(serialized) > 0


class TestCheckStale:
    """Test --check staleness detection."""

    def test_fresh_after_generate(self, tmp_path):
        tools = discover_tools()
        generate_markdown(tmp_path, tools)
        assert check_stale(tmp_path, tools) is True

    def test_stale_when_dir_missing(self, tmp_path):
        tools = discover_tools()
        missing_dir = tmp_path / "nonexistent"
        assert check_stale(missing_dir, tools) is False

    def test_stale_when_file_modified(self, tmp_path):
        tools = discover_tools()
        generate_markdown(tmp_path, tools)

        # Modify a file
        index = tmp_path / "index.md"
        index.write_text("tampered content", encoding="utf-8")

        assert check_stale(tmp_path, tools) is False


class TestCLI:
    """Test the script invoked as a CLI."""

    def test_generate_markdown_cli(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--output", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Generated docs for" in result.stdout
        assert (tmp_path / "index.md").exists()

    def test_generate_json_cli(self, tmp_path):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--output",
                str(tmp_path),
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Generated JSON for" in result.stdout
        assert (tmp_path / "tools.json").exists()

        data = json.loads((tmp_path / "tools.json").read_text(encoding="utf-8"))
        assert "tools" in data

    def test_check_passes_after_generate(self, tmp_path):
        # Generate first
        subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--output", str(tmp_path)],
            capture_output=True,
        )
        # Check should pass
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--check", "--output", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_check_fails_when_stale(self, tmp_path):
        # Generate first
        subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--output", str(tmp_path)],
            capture_output=True,
        )
        # Tamper with a file
        (tmp_path / "index.md").write_text("tampered", encoding="utf-8")

        # Check should fail
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--check", "--output", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
