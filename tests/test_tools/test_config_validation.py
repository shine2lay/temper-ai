"""
Tests for config validation via BaseTool.validate_config().

Verifies that tools with config_model validate YAML config correctly,
including template skipping, internal key skipping, and error detection.
"""

from pydantic import BaseModel, Field

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult

# ---------------------------------------------------------------------------
# Fixtures: minimal tools for testing
# ---------------------------------------------------------------------------


class _SampleConfig(BaseModel):
    timeout: int = Field(default=30, description="Timeout in seconds")
    enabled: bool = Field(default=True, description="Feature toggle")
    name: str | None = Field(default=None, description="Optional name")


class _ToolWithConfig(BaseTool):
    """Tool with a config_model for testing validation."""

    config_model = _SampleConfig

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(name="ConfigTool", description="test tool")

    def get_parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="ok")


class _ToolWithoutConfig(BaseTool):
    """Tool without a config_model."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(name="NoConfigTool", description="test tool")

    def get_parameters_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="ok")


# ---------------------------------------------------------------------------
# Tests: validate_config()
# ---------------------------------------------------------------------------


class TestValidateConfig:
    """Test BaseTool.validate_config()."""

    def test_valid_config_passes(self):
        tool = _ToolWithConfig(config={"timeout": 60, "enabled": False})
        result = tool.validate_config()
        assert result.valid
        assert result.errors == []

    def test_wrong_type_detected(self):
        tool = _ToolWithConfig(config={"timeout": "not_a_number"})
        result = tool.validate_config()
        assert not result.valid
        assert any("timeout" in e for e in result.errors)

    def test_no_config_model_always_passes(self):
        tool = _ToolWithoutConfig(config={"anything": "goes"})
        result = tool.validate_config()
        assert result.valid

    def test_empty_config_passes(self):
        tool = _ToolWithConfig(config={})
        result = tool.validate_config()
        assert result.valid

    def test_jinja2_template_strings_skipped(self):
        tool = _ToolWithConfig(config={"timeout": "{{ agent_timeout }}"})
        result = tool.validate_config()
        assert result.valid

    def test_internal_keys_skipped(self):
        tool = _ToolWithConfig(config={"_templates": {"timeout": "{{ x }}"}})
        result = tool.validate_config()
        assert result.valid

    def test_partial_config_uses_defaults(self):
        tool = _ToolWithConfig(config={"timeout": 10})
        result = tool.validate_config()
        assert result.valid


# ---------------------------------------------------------------------------
# Tests: Real tools with config_model
# ---------------------------------------------------------------------------


class TestRealToolConfigValidation:
    """Test config validation on real tools."""

    def test_bash_valid_config(self):
        from temper_ai.tools.bash import Bash

        bash = Bash(config={"shell_mode": True, "default_timeout": 60})
        result = bash.validate_config()
        assert result.valid

    def test_bash_wrong_type(self):
        from temper_ai.tools.bash import Bash

        bash = Bash()
        bash.config = {"default_timeout": "not_a_number"}
        result = bash.validate_config()
        assert not result.valid

    def test_file_writer_valid_config(self):
        from temper_ai.tools.file_writer import FileWriter

        fw = FileWriter(config={"allowed_root": "/tmp/test"})
        result = fw.validate_config()
        assert result.valid

    def test_web_search_valid_config(self):
        from temper_ai.tools.web_search import WebSearch

        ws = WebSearch(config={"provider": "searxng", "language": "en"})
        result = ws.validate_config()
        assert result.valid


# ---------------------------------------------------------------------------
# Tests: Bash dynamic schema preserved
# ---------------------------------------------------------------------------


class TestBashDynamicSchema:
    """Test that Bash.get_parameters_schema() still varies by shell_mode."""

    def test_strict_mode_schema(self):
        from temper_ai.tools.bash import Bash

        bash_strict = Bash()
        schema = bash_strict.get_parameters_schema()
        assert "command" in schema["properties"]
        assert "working_directory" in schema["properties"]
        assert "timeout" in schema["properties"]
        # Strict mode mentions "No shell metacharacters"
        assert "metacharacter" in schema["properties"]["command"]["description"].lower()

    def test_shell_mode_schema(self):
        from temper_ai.tools.bash import Bash

        bash_shell = Bash(config={"shell_mode": True})
        schema = bash_shell.get_parameters_schema()
        # Shell mode mentions "redirections" or "pipes"
        desc = schema["properties"]["command"]["description"].lower()
        assert "redirect" in desc or "pipe" in desc

    def test_schemas_differ(self):
        from temper_ai.tools.bash import Bash

        strict = Bash().get_parameters_schema()
        shell = Bash(config={"shell_mode": True}).get_parameters_schema()
        assert (
            strict["properties"]["command"]["description"]
            != shell["properties"]["command"]["description"]
        )
