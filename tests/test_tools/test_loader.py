"""Tests for temper_ai/tools/loader.py"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from temper_ai.tools.loader import (
    _collect_and_render_templates,
    _render_template_value,
    _resolve_single_tool_templates,
    _restore_saved_templates,
    apply_tool_config,
    ensure_tools_discovered,
    resolve_tool_config_templates,
    resolve_tool_spec,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class MockToolSpec:
    """Simple object with name and config attributes, mimicking a tool spec."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config


class MockTool:
    """Minimal tool stub for loader tests."""

    def __init__(self, config=None, name="mock_tool"):
        self.config = config if config is not None else {}
        self.name = name


class MockToolWithValidation(MockTool):
    """Tool stub that exposes validate_config."""

    def __init__(self, valid: bool = True, error: str = ""):
        super().__init__()
        self._valid = valid
        self._error = error

    def validate_config(self):
        return SimpleNamespace(valid=self._valid, error_message=self._error)


# ===========================================================================
# TestResolveToolSpec
# ===========================================================================


class TestResolveToolSpec:
    def test_string_returns_name_and_empty_config(self):
        name, config = resolve_tool_spec("my_tool")
        assert name == "my_tool"
        assert config == {}

    def test_object_with_config_attribute_returns_name_and_config(self):
        spec = MockToolSpec("my_tool", {"key": "value"})
        name, config = resolve_tool_spec(spec)
        assert name == "my_tool"
        assert config == {"key": "value"}


# ===========================================================================
# TestApplyToolConfig
# ===========================================================================


class TestApplyToolConfig:
    def test_empty_config_is_noop(self):
        tool = MockTool({"existing": "value"})
        apply_tool_config(tool, "tool", {})
        assert tool.config == {"existing": "value"}

    def test_merges_dict_config(self):
        tool = MockTool({"existing": "value"})
        apply_tool_config(tool, "tool", {"new": "added"})
        assert tool.config == {"existing": "value", "new": "added"}

    def test_replaces_non_dict_config(self):
        tool = MockTool()
        tool.config = "not a dict"
        apply_tool_config(tool, "tool", {"key": "value"})
        assert tool.config == {"key": "value"}

    def test_logs_validation_warning_on_failure(self):
        tool = MockToolWithValidation(valid=False, error="Bad config")
        with patch("temper_ai.tools.loader.logger") as mock_logger:
            apply_tool_config(tool, "tool", {"x": 1})
        mock_logger.warning.assert_called_once()


# ===========================================================================
# TestRenderTemplateValue
# ===========================================================================


class TestRenderTemplateValue:
    def test_single_variable(self):
        result = _render_template_value("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_multiple_variables(self):
        result = _render_template_value(
            "{{greeting}} {{name}}", {"greeting": "Hello", "name": "World"}
        )
        assert result == "Hello World"

    def test_missing_variable_left_as_is(self):
        result = _render_template_value("Hello {{missing}}", {})
        assert result == "Hello {{missing}}"

    def test_no_templates_returns_unchanged(self):
        result = _render_template_value("plain text", {"name": "World"})
        assert result == "plain text"


# ===========================================================================
# TestCollectAndRenderTemplates
# ===========================================================================


class TestCollectAndRenderTemplates:
    def test_renders_templates_in_place(self):
        config = {"url": "https://{{host}}/api"}
        changed = _collect_and_render_templates(config, {"host": "example.com"})
        assert config["url"] == "https://example.com/api"
        assert "url" in changed

    def test_skips_internal_keys(self):
        config = {"_internal": "{{skip_me}}"}
        changed = _collect_and_render_templates(config, {"skip_me": "value"})
        assert config["_internal"] == "{{skip_me}}"
        assert "_internal" not in changed

    def test_skips_non_string_values(self):
        config = {"count": 42, "url": "{{host}}"}
        _collect_and_render_templates(config, {"host": "example.com"})
        assert config["count"] == 42

    def test_returns_changed_keys_with_original_templates(self):
        original_template = "https://{{host}}/path"
        config = {"url": original_template}
        changed = _collect_and_render_templates(config, {"host": "example.com"})
        assert changed["url"] == original_template


# ===========================================================================
# TestRestoreSavedTemplates
# ===========================================================================


class TestRestoreSavedTemplates:
    def test_restores_from_templates_key(self):
        original = "https://{{host}}/api"
        config = {
            "url": "https://example.com/api",
            "_templates": {"url": original},
        }
        _restore_saved_templates(config)
        assert config["url"] == original

    def test_no_templates_key_is_noop(self):
        config = {"url": "https://example.com/api"}
        _restore_saved_templates(config)  # Must not raise
        assert config["url"] == "https://example.com/api"


# ===========================================================================
# TestResolveSingleToolTemplates
# ===========================================================================


class TestResolveSingleToolTemplates:
    def test_renders_template_and_stores_backup(self):
        tool = MockTool({"url": "https://{{host}}/api"})
        _resolve_single_tool_templates(tool, {"host": "example.com"}, "agent")
        assert tool.config["url"] == "https://example.com/api"
        assert "_templates" in tool.config
        assert tool.config["_templates"]["url"] == "https://{{host}}/api"

    def test_re_resolves_after_restore_on_second_call(self):
        tool = MockTool({"url": "https://{{host}}/api"})
        _resolve_single_tool_templates(tool, {"host": "first.com"}, "agent")
        assert tool.config["url"] == "https://first.com/api"
        # Second call restores original template then re-renders with new data
        _resolve_single_tool_templates(tool, {"host": "second.com"}, "agent")
        assert tool.config["url"] == "https://second.com/api"

    def test_tool_without_config_attribute_is_noop(self):
        tool = object()  # No config attribute
        _resolve_single_tool_templates(tool, {"host": "example.com"}, "agent")


# ===========================================================================
# TestResolveToolConfigTemplates
# ===========================================================================


class TestResolveToolConfigTemplates:
    def test_none_registry_is_noop(self):
        resolve_tool_config_templates(None, {"host": "example.com"}, "agent")

    def test_empty_tools_dict_is_noop(self):
        mock_registry = MagicMock()
        mock_registry.get_all_tools.return_value = {}
        resolve_tool_config_templates(mock_registry, {}, "agent")

    def test_iterates_tools_and_resolves_templates(self):
        tool = MockTool({"url": "https://{{host}}/api"})
        mock_registry = MagicMock()
        mock_registry.get_all_tools.return_value = {"mock_tool": tool}
        resolve_tool_config_templates(mock_registry, {"host": "example.com"}, "agent")
        assert tool.config["url"] == "https://example.com/api"


# ===========================================================================
# TestEnsureToolsDiscovered
# ===========================================================================


class TestEnsureToolsDiscovered:
    def test_is_noop(self):
        """ensure_tools_discovered is now a no-op (lazy loading handles it)."""
        mock_registry = MagicMock()
        mock_registry.list_tools.return_value = []
        ensure_tools_discovered(mock_registry)
        # Should not call auto_discover — function is a no-op
        mock_registry.auto_discover.assert_not_called()

    def test_does_not_crash_with_tools_present(self):
        mock_registry = MagicMock()
        mock_registry.list_tools.return_value = ["tool1", "tool2"]
        ensure_tools_discovered(mock_registry)
        mock_registry.auto_discover.assert_not_called()
