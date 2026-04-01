"""Tests for BaseTool interface and ToolResult."""

from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult


class DummyTool(BaseTool):
    name = "dummy"
    description = "A test tool"
    parameters = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    modifies_state = False

    def execute(self, **params: Any) -> ToolResult:
        return ToolResult(success=True, result=f"got {params.get('x')}")


class TestToolResult:
    def test_success(self):
        r = ToolResult(success=True, result="ok")
        assert r.success is True
        assert r.result == "ok"
        assert r.error is None
        assert r.metadata == {}

    def test_failure(self):
        r = ToolResult(success=False, result="", error="broke")
        assert r.success is False
        assert r.error == "broke"

    def test_metadata(self):
        r = ToolResult(success=True, result="ok", metadata={"bytes": 42})
        assert r.metadata["bytes"] == 42


class TestBaseTool:
    def test_execute(self):
        tool = DummyTool()
        result = tool.execute(x="hello")
        assert result.success is True
        assert result.result == "got hello"

    def test_to_llm_schema(self):
        tool = DummyTool()
        schema = tool.to_llm_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "dummy"
        assert schema["function"]["description"] == "A test tool"
        assert schema["function"]["parameters"]["required"] == ["x"]

    def test_config(self):
        tool = DummyTool(config={"key": "value"})
        assert tool.config["key"] == "value"

    def test_default_config(self):
        tool = DummyTool()
        assert tool.config == {}

    def test_modifies_state(self):
        tool = DummyTool()
        assert tool.modifies_state is False
