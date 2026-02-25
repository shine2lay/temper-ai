"""Tests for tool schema building and routing.

Verifies that:
- Native tool definitions are built by default (all providers)
- Text-based schemas are used only when use_text_tool_schemas=True
- Text schemas are appended to the prompt string
- Native defs are NOT appended to the prompt
- _schemas.py does not import provider classes
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

from temper_ai.llm._schemas import build_native_tool_defs
from temper_ai.llm.service import LLMService
from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeTool(BaseTool):
    """Minimal tool for testing."""

    def __init__(self, name: str = "fake_tool"):
        self._name = name
        super().__init__()

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"A fake tool called {self._name}"

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, result="ok")

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"input": {"type": "string"}},
        }

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name, description=self.description, version="1.0.0"
        )


@dataclass
class FakeInferenceConfig:
    """Minimal inference config for schema tests."""

    provider: str = "ollama"
    model: str = "test-model"
    max_retries: int = 0
    use_text_tool_schemas: bool = False


def _make_service(use_text: bool = False) -> LLMService:
    mock_llm = MagicMock()
    config = FakeInferenceConfig(use_text_tool_schemas=use_text)
    return LLMService(llm=mock_llm, inference_config=config)


# ---------------------------------------------------------------------------
# Tests: build_native_tool_defs (no provider gating)
# ---------------------------------------------------------------------------


class TestBuildNativeToolDefs:
    """Test that native tool defs are built for any provider."""

    def test_native_tool_defs_built_by_default(self):
        """Default config should build native tool definitions."""
        tool = FakeTool("my_tool")
        defs, hash_val = build_native_tool_defs([tool], None, None)

        assert defs is not None
        assert len(defs) == 1
        assert defs[0]["type"] == "function"
        assert defs[0]["function"]["name"] == "my_tool"
        assert hash_val is not None

    def test_native_defs_none_for_empty_tools(self):
        """Empty tools list returns None."""
        defs, hash_val = build_native_tool_defs([], None, None)
        assert defs is None
        assert hash_val is None

    def test_native_defs_none_for_none_tools(self):
        """None tools returns None."""
        defs, hash_val = build_native_tool_defs(None, None, None)
        assert defs is None
        assert hash_val is None

    def test_native_defs_caching(self):
        """Cached defs are reused when hash matches."""
        tool = FakeTool("cached_tool")
        defs1, hash1 = build_native_tool_defs([tool], None, None)
        defs2, hash2 = build_native_tool_defs([tool], defs1, hash1)

        assert defs2 is defs1
        assert hash2 == hash1


# ---------------------------------------------------------------------------
# Tests: LLMService schema routing via config flag
# ---------------------------------------------------------------------------


class TestSchemaRouting:
    """Test that LLMService routes between native and text schemas via config."""

    @patch("temper_ai.llm.service.call_with_retry_sync")
    @patch("temper_ai.llm.service.track_call")
    @patch("temper_ai.llm.service.estimate_cost", return_value=0.0)
    @patch("temper_ai.llm.service.emit_llm_iteration_event")
    def test_text_schemas_when_opt_in(
        self,
        mock_emit: MagicMock,
        mock_cost: MagicMock,
        mock_track: MagicMock,
        mock_retry: MagicMock,
    ):
        """use_text_tool_schemas=True should append text schemas to prompt."""
        service = _make_service(use_text=True)
        tool = FakeTool("search")

        response = MagicMock()
        response.content = "Final answer"
        response.total_tokens = 10
        mock_retry.return_value = (response, None)

        service.run("Hello", tools=[tool])

        # The prompt passed to retry should contain tool schema text
        call_args = mock_retry.call_args
        prompt_arg = call_args[0][2]  # positional arg: prompt
        assert "search" in prompt_arg
        assert "Available Tools" in prompt_arg

        # native_tool_defs should be None
        native_defs_arg = call_args[0][4]  # positional arg: native_tool_defs
        assert native_defs_arg is None

    @patch("temper_ai.llm.service.call_with_retry_sync")
    @patch("temper_ai.llm.service.track_call")
    @patch("temper_ai.llm.service.estimate_cost", return_value=0.0)
    @patch("temper_ai.llm.service.emit_llm_iteration_event")
    def test_native_defs_by_default(
        self,
        mock_emit: MagicMock,
        mock_cost: MagicMock,
        mock_track: MagicMock,
        mock_retry: MagicMock,
    ):
        """Default config should pass native tool defs, not text schemas."""
        service = _make_service(use_text=False)
        tool = FakeTool("search")

        response = MagicMock()
        response.content = "Final answer"
        response.total_tokens = 10
        mock_retry.return_value = (response, None)

        service.run("Hello", tools=[tool])

        call_args = mock_retry.call_args
        prompt_arg = call_args[0][2]
        native_defs_arg = call_args[0][4]

        # Prompt should NOT contain text schemas
        assert "Available Tools" not in prompt_arg

        # Native defs should be present
        assert native_defs_arg is not None
        assert len(native_defs_arg) == 1
        assert native_defs_arg[0]["function"]["name"] == "search"

    @patch("temper_ai.llm.service.call_with_retry_sync")
    @patch("temper_ai.llm.service.track_call")
    @patch("temper_ai.llm.service.estimate_cost", return_value=0.0)
    @patch("temper_ai.llm.service.emit_llm_iteration_event")
    def test_text_schemas_appended_to_prompt(
        self,
        mock_emit: MagicMock,
        mock_cost: MagicMock,
        mock_track: MagicMock,
        mock_retry: MagicMock,
    ):
        """Text schemas should be appended to the original prompt."""
        service = _make_service(use_text=True)
        tool = FakeTool("calculator")

        response = MagicMock()
        response.content = "42"
        response.total_tokens = 5
        mock_retry.return_value = (response, None)

        service.run("What is 6 * 7?", tools=[tool])

        prompt_arg = mock_retry.call_args[0][2]
        # Original prompt should be at the start
        assert prompt_arg.startswith("What is 6 * 7?")
        # Text schemas should follow
        assert "calculator" in prompt_arg

    @patch("temper_ai.llm.service.call_with_retry_sync")
    @patch("temper_ai.llm.service.track_call")
    @patch("temper_ai.llm.service.estimate_cost", return_value=0.0)
    @patch("temper_ai.llm.service.emit_llm_iteration_event")
    def test_native_defs_not_in_prompt(
        self,
        mock_emit: MagicMock,
        mock_cost: MagicMock,
        mock_track: MagicMock,
        mock_retry: MagicMock,
    ):
        """Native tool defs should NOT be appended to the prompt text."""
        service = _make_service(use_text=False)
        tool = FakeTool("search")

        response = MagicMock()
        response.content = "result"
        response.total_tokens = 5
        mock_retry.return_value = (response, None)

        service.run("Find something", tools=[tool])

        prompt_arg = mock_retry.call_args[0][2]
        assert prompt_arg == "Find something"


# ---------------------------------------------------------------------------
# Tests: no provider imports in _schemas.py
# ---------------------------------------------------------------------------


class TestNoProviderImports:
    """Verify _schemas.py doesn't import provider classes."""

    def test_no_provider_imports_in_schemas(self):
        """_schemas.py should not import any provider classes."""
        module = inspect.getmodule(build_native_tool_defs)
        module_source = inspect.getsource(module)

        # Parse the module AST and check imports
        tree = ast.parse(module_source)
        provider_names = {"OllamaLLM", "OpenAILLM", "AnthropicLLM", "VllmLLM"}
        imported_names: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)

        overlap = provider_names & imported_names
        assert (
            not overlap
        ), f"_schemas.py should not import provider classes, found: {overlap}"
