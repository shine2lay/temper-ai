"""Tests for temper_ai/tools/_registry_helpers.py"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.shared.utils.exceptions import ToolRegistryError
from temper_ai.tools._registry_helpers import (
    _load_tool_class,
    _parse_implementation_path,
    get_error_suggestion,
    get_latest_version,
    validate_tool_interface,
)
from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult

# ---------------------------------------------------------------------------
# Concrete tool fixtures
# ---------------------------------------------------------------------------


class ConcreteTool(BaseTool):
    """Minimal concrete BaseTool subclass for testing."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(name="concrete", description="A concrete test tool")

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True)


class RequiresArgsTool(BaseTool):
    """Tool whose constructor requires arguments – cannot be auto-instantiated."""

    def __init__(self, required_arg: str):  # type: ignore[override]
        # Intentionally do NOT call super(); tests the TypeError discovery path
        pass

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(name="requires_args", description="Needs constructor args")

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True)


# ===========================================================================
# TestValidateToolInterface
# ===========================================================================


class TestValidateToolInterface:
    def test_valid_concrete_basetool_subclass_passes(self):
        valid, errors = validate_tool_interface(ConcreteTool)
        assert valid is True
        assert errors == []

    def test_non_basetool_class_fails(self):
        class NotATool:
            pass

        valid, errors = validate_tool_interface(NotATool)
        assert valid is False
        assert any("BaseTool" in e for e in errors)

    def test_abstract_class_fails(self):
        class AbstractSub(BaseTool):
            pass  # Inherits without implementing abstract methods

        valid, errors = validate_tool_interface(AbstractSub)
        assert valid is False
        assert any("abstract" in e.lower() for e in errors)

    def test_missing_execute_fails(self):
        class MissingExec:
            def get_metadata(self):
                return None

        valid, errors = validate_tool_interface(MissingExec)
        assert valid is False
        assert any("execute" in e for e in errors)

    def test_missing_get_metadata_fails(self):
        class MissingMeta:
            def execute(self, **kwargs):
                return None

        valid, errors = validate_tool_interface(MissingMeta)
        assert valid is False
        assert any("get_metadata" in e for e in errors)

    def test_non_callable_execute_fails(self):
        class NonCallableExec:
            def get_metadata(self):
                return None

            execute = "not a function"

        valid, errors = validate_tool_interface(NonCallableExec)
        assert valid is False
        assert any("not callable" in e for e in errors)

    def test_non_callable_get_metadata_fails(self):
        class NonCallableMeta:
            def execute(self, **kwargs):
                return None

            get_metadata = 42

        valid, errors = validate_tool_interface(NonCallableMeta)
        assert valid is False
        assert any("not callable" in e for e in errors)


# ===========================================================================
# TestGetErrorSuggestion
# ===========================================================================


class TestGetErrorSuggestion:
    def test_matches_requires_init_arguments(self):
        suggestion = get_error_suggestion("Tool requires init arguments")
        assert suggestion is not None
        assert "register" in suggestion.lower() or "default" in suggestion.lower()

    def test_matches_missing_required_method(self):
        suggestion = get_error_suggestion("Missing required method: execute")
        assert suggestion is not None
        assert "BaseTool" in suggestion

    def test_matches_not_inherit_from_basetool(self):
        suggestion = get_error_suggestion(
            "Tool does not inherit from BaseTool — wrong base class"
        )
        assert suggestion is not None
        assert "BaseTool" in suggestion

    def test_unknown_error_returns_none(self):
        result = get_error_suggestion("completely unknown weird error xyz123")
        assert result is None

    def test_case_insensitive_matching(self):
        suggestion = get_error_suggestion("REQUIRES INIT ARGUMENTS please fix")
        assert suggestion is not None


# ===========================================================================
# TestParseImplementationPath
# ===========================================================================


class TestParseImplementationPath:
    def test_string_passthrough(self):
        result = _parse_implementation_path("my.module.MyClass", "test_tool")
        assert result == "my.module.MyClass"

    def test_dict_with_module_and_class(self):
        impl = {"module": "my.module", "class": "MyClass"}
        result = _parse_implementation_path(impl, "test_tool")
        assert result == "my.module.MyClass"

    def test_dict_missing_module_raises(self):
        impl = {"class": "MyClass"}
        with pytest.raises(ToolRegistryError):
            _parse_implementation_path(impl, "test_tool")

    def test_dict_missing_class_raises(self):
        impl = {"module": "my.module"}
        with pytest.raises(ToolRegistryError):
            _parse_implementation_path(impl, "test_tool")

    def test_non_string_non_dict_raises(self):
        with pytest.raises(ToolRegistryError, match="Invalid implementation format"):
            _parse_implementation_path(12345, "test_tool")

    def test_list_raises(self):
        with pytest.raises(ToolRegistryError, match="Invalid implementation format"):
            _parse_implementation_path(["my.module", "MyClass"], "test_tool")


# ===========================================================================
# TestLoadToolClass
# ===========================================================================


class TestLoadToolClass:
    def test_invalid_format_no_dot_raises(self):
        with pytest.raises(ToolRegistryError, match="Invalid class path format"):
            _load_tool_class("nodot")

    @patch("temper_ai.tools._registry_helpers.importlib.import_module")
    def test_import_error_raises(self, mock_import):
        mock_import.side_effect = ImportError("no module named foo")
        with pytest.raises(ToolRegistryError, match="Failed to import"):
            _load_tool_class("some.module.MyClass")

    @patch("temper_ai.tools._registry_helpers.importlib.import_module")
    def test_missing_attribute_raises(self, mock_import):
        # types.ModuleType has no user attributes → getattr raises AttributeError
        mock_import.return_value = types.ModuleType("fake_module")
        with pytest.raises(ToolRegistryError, match="Tool class not found in module"):
            _load_tool_class("fake_module.NonExistentClass")

    @patch("temper_ai.tools._registry_helpers.importlib.import_module")
    def test_non_basetool_subclass_raises(self, mock_import):
        mock_module = MagicMock()
        mock_module.NotATool = str  # str doesn't inherit from BaseTool
        mock_import.return_value = mock_module
        with pytest.raises(ToolRegistryError, match="must inherit from BaseTool"):
            _load_tool_class("some.module.NotATool")

    @patch("temper_ai.tools._registry_helpers.importlib.import_module")
    def test_valid_class_returned(self, mock_import):
        mock_module = MagicMock()
        mock_module.ConcreteTool = ConcreteTool
        mock_import.return_value = mock_module
        result = _load_tool_class("some.module.ConcreteTool")
        assert result is ConcreteTool


# ===========================================================================
# TestGetLatestVersion
# ===========================================================================


class TestGetLatestVersion:
    def test_single_version(self):
        assert get_latest_version(["1.0.0"]) == "1.0.0"

    def test_multiple_versions_returns_latest(self):
        assert get_latest_version(["1.0", "2.0", "1.1"]) == "2.0"

    def test_empty_list_raises_value_error(self):
        with pytest.raises(ValueError, match="No versions"):
            get_latest_version([])

    def test_three_part_version_ordering(self):
        assert get_latest_version(["1.0.0", "1.2.3", "1.1.9"]) == "1.2.3"

    def test_single_entry_returns_that_version(self):
        assert get_latest_version(["3.5.2"]) == "3.5.2"


# ===========================================================================
# TestStaticRegistry (replaces removed auto-discovery tests)
# ===========================================================================


class TestStaticRegistryIntegration:
    def test_lazy_get_instantiates_from_tool_classes(self):
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        tool = registry.get("Calculator")
        assert tool is not None
        assert tool.name == "Calculator"

    def test_has_checks_tool_classes(self):
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        assert registry.has("Bash")
        assert not registry.has("NonExistent")
