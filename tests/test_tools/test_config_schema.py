"""
Tests for get_config_schema() on BaseTool and concrete tool implementations.
"""

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.bash import Bash
from temper_ai.tools.file_writer import FileWriter

# ---------------------------------------------------------------------------
# Minimal concrete tool for testing BaseTool default
# ---------------------------------------------------------------------------


class _MinimalTool(BaseTool):
    """Minimal tool with no config for testing default get_config_schema()."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(name="MinimalTool", description="A test tool")

    def get_parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="ok")


class TestBaseToolConfigSchema:
    """Test BaseTool.get_config_schema() default."""

    def test_returns_valid_json_schema(self):
        tool = _MinimalTool()
        schema = tool.get_config_schema()
        assert schema["type"] == "object"
        assert "properties" in schema

    def test_default_has_empty_properties(self):
        tool = _MinimalTool()
        schema = tool.get_config_schema()
        assert schema["properties"] == {}


class TestBashConfigSchema:
    """Test Bash.get_config_schema()."""

    def test_returns_valid_json_schema(self):
        bash = Bash()
        schema = bash.get_config_schema()
        assert schema["type"] == "object"
        assert "properties" in schema

    def test_has_allowed_commands(self):
        bash = Bash()
        schema = bash.get_config_schema()
        props = schema["properties"]
        assert "allowed_commands" in props
        assert props["allowed_commands"]["type"] == "array"
        assert props["allowed_commands"]["items"]["type"] == "string"

    def test_has_workspace_root(self):
        bash = Bash()
        schema = bash.get_config_schema()
        props = schema["properties"]
        assert "workspace_root" in props
        assert props["workspace_root"]["type"] == "string"

    def test_has_default_timeout(self):
        bash = Bash()
        schema = bash.get_config_schema()
        props = schema["properties"]
        assert "default_timeout" in props
        assert props["default_timeout"]["type"] == "integer"

    def test_has_shell_mode(self):
        bash = Bash()
        schema = bash.get_config_schema()
        props = schema["properties"]
        assert "shell_mode" in props
        assert props["shell_mode"]["type"] == "boolean"


class TestFileWriterConfigSchema:
    """Test FileWriter.get_config_schema()."""

    def test_returns_valid_json_schema(self):
        fw = FileWriter()
        schema = fw.get_config_schema()
        assert schema["type"] == "object"
        assert "properties" in schema

    def test_has_allowed_root(self):
        fw = FileWriter()
        schema = fw.get_config_schema()
        props = schema["properties"]
        assert "allowed_root" in props
        assert props["allowed_root"]["type"] == "string"
