"""Coverage tests for temper_ai/llm/_schemas.py.

Covers: build_text_schemas and build_native_tool_defs —
empty tools, cache hits, cache misses, result schemas.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from temper_ai.llm._schemas import build_native_tool_defs, build_text_schemas


def _make_tool(name: str = "test_tool", desc: str = "A test tool") -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = desc
    tool.get_parameters_schema.return_value = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
    }
    tool.get_result_schema.return_value = None
    return tool


class TestBuildTextSchemas:
    def test_none_tools(self) -> None:
        result, hash_val = build_text_schemas(None, None, None)
        assert result is None
        assert hash_val is None

    def test_empty_tools(self) -> None:
        result, hash_val = build_text_schemas([], None, None)
        assert result is None
        assert hash_val is None

    def test_builds_schemas(self) -> None:
        tool = _make_tool()
        result, hash_val = build_text_schemas([tool], None, None)
        assert result is not None
        assert "Available Tools" in result
        assert "test_tool" in result
        assert hash_val is not None

    def test_cache_hit(self) -> None:
        tool = _make_tool()
        result1, hash1 = build_text_schemas([tool], None, None)
        result2, hash2 = build_text_schemas([tool], result1, hash1)
        assert result2 is result1
        assert hash2 == hash1

    def test_cache_miss_different_tools(self) -> None:
        tool1 = _make_tool("tool1")
        tool2 = _make_tool("tool2")
        result1, hash1 = build_text_schemas([tool1], None, None)
        result2, hash2 = build_text_schemas([tool2], result1, hash1)
        assert result2 is not result1
        assert hash2 != hash1


class TestBuildNativeToolDefs:
    def test_none_tools(self) -> None:
        result, hash_val = build_native_tool_defs(None, None, None)
        assert result is None
        assert hash_val is None

    def test_empty_tools(self) -> None:
        result, hash_val = build_native_tool_defs([], None, None)
        assert result is None
        assert hash_val is None

    def test_builds_defs(self) -> None:
        tool = _make_tool()
        result, hash_val = build_native_tool_defs([tool], None, None)
        assert result is not None
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "test_tool"

    def test_with_result_schema(self) -> None:
        tool = _make_tool()
        tool.get_result_schema.return_value = {"type": "string"}
        result, hash_val = build_native_tool_defs([tool], None, None)
        assert result is not None
        assert "Result schema" in result[0]["function"]["description"]

    def test_cache_hit(self) -> None:
        tool = _make_tool()
        result1, hash1 = build_native_tool_defs([tool], None, None)
        result2, hash2 = build_native_tool_defs([tool], result1, hash1)
        assert result2 is result1
        assert hash2 == hash1

    def test_cache_miss_different_schemas(self) -> None:
        tool1 = _make_tool("tool1")
        tool2 = _make_tool("tool2")
        result1, hash1 = build_native_tool_defs([tool1], None, None)
        result2, hash2 = build_native_tool_defs([tool2], result1, hash1)
        assert hash2 != hash1

    def test_tools_with_empty_dict_after_filter(self) -> None:
        """Test where tools list has items but tools_dict ends up empty."""
        # This is an edge case - tools_dict is {t.name: t for t in tools}
        # If tool has a name, tools_dict won't be empty.
        # Let's test with name="" which would still have one entry.
        tool = _make_tool(name="")
        result, _ = build_native_tool_defs([tool], None, None)
        assert result is not None
