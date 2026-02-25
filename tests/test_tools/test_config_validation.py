"""
Tests for config validation via BaseTool.validate_config() and get_typed_config().

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
# Tests: get_typed_config()
# ---------------------------------------------------------------------------


class TestGetTypedConfig:
    """Test BaseTool.get_typed_config()."""

    def test_returns_model_instance(self):
        tool = _ToolWithConfig(config={"timeout": 60, "enabled": False})
        typed = tool.get_typed_config()
        assert typed is not None
        assert isinstance(typed, _SampleConfig)
        assert typed.timeout == 60
        assert typed.enabled is False

    def test_no_config_model_returns_none(self):
        tool = _ToolWithoutConfig()
        assert tool.get_typed_config() is None

    def test_uses_defaults_for_missing_keys(self):
        tool = _ToolWithConfig(config={})
        typed = tool.get_typed_config()
        assert typed is not None
        assert typed.timeout == 30
        assert typed.enabled is True

    def test_skips_internal_keys(self):
        tool = _ToolWithConfig(
            config={"timeout": 10, "_templates": {"timeout": "{{ x }}"}}
        )
        typed = tool.get_typed_config()
        assert typed is not None
        assert typed.timeout == 10

    def test_skips_jinja2_template_strings(self):
        tool = _ToolWithConfig(config={"timeout": "{{ x }}", "enabled": True})
        typed = tool.get_typed_config()
        assert typed is not None
        assert typed.enabled is True


# ---------------------------------------------------------------------------
# Tests: get_config_schema() auto-derivation
# ---------------------------------------------------------------------------


class TestGetConfigSchemaDerivation:
    """Test that get_config_schema() auto-derives from config_model."""

    def test_auto_derives_from_config_model(self):
        tool = _ToolWithConfig()
        schema = tool.get_config_schema()
        assert schema["type"] == "object"
        assert "timeout" in schema["properties"]
        assert "enabled" in schema["properties"]

    def test_no_config_model_returns_empty(self):
        tool = _ToolWithoutConfig()
        schema = tool.get_config_schema()
        assert schema == {"type": "object", "properties": {}}

    def test_schema_has_descriptions(self):
        tool = _ToolWithConfig()
        schema = tool.get_config_schema()
        assert schema["properties"]["timeout"]["description"] == "Timeout in seconds"

    def test_schema_strips_pydantic_title(self):
        tool = _ToolWithConfig()
        schema = tool.get_config_schema()
        for prop in schema["properties"].values():
            assert "title" not in prop


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
