"""Tests for LLM response parsing."""

from temper_ai.llm.models import LLMResponse
from temper_ai.llm.response_parser import extract_final_answer, parse_tool_calls


class TestParseToolCalls:
    def test_no_tool_calls(self):
        resp = LLMResponse(content="Hello", model="gpt-4", provider="test")
        assert parse_tool_calls(resp) == []

    def test_empty_tool_calls(self):
        resp = LLMResponse(
            content="Hello", model="gpt-4", provider="test", tool_calls=[],
        )
        assert parse_tool_calls(resp) == []

    def test_single_tool_call(self):
        resp = LLMResponse(
            content=None, model="gpt-4", provider="test",
            tool_calls=[{
                "id": "call_123",
                "name": "bash",
                "arguments": '{"command": "ls -la"}',
            }],
        )
        parsed = parse_tool_calls(resp)
        assert len(parsed) == 1
        assert parsed[0]["id"] == "call_123"
        assert parsed[0]["name"] == "bash"
        assert parsed[0]["arguments"] == {"command": "ls -la"}

    def test_multiple_tool_calls(self):
        resp = LLMResponse(
            content=None, model="gpt-4", provider="test",
            tool_calls=[
                {"id": "c1", "name": "bash", "arguments": '{"command": "ls"}'},
                {"id": "c2", "name": "file_writer", "arguments": '{"path": "x.py", "content": "hi"}'},
            ],
        )
        parsed = parse_tool_calls(resp)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "bash"
        assert parsed[1]["name"] == "file_writer"
        assert parsed[1]["arguments"]["path"] == "x.py"

    def test_malformed_json_arguments(self):
        resp = LLMResponse(
            content=None, model="gpt-4", provider="test",
            tool_calls=[{
                "id": "c1",
                "name": "bash",
                "arguments": "not valid json {{{",
            }],
        )
        parsed = parse_tool_calls(resp)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "bash"
        assert "_raw" in parsed[0]["arguments"]

    def test_dict_arguments(self):
        """Arguments already parsed as dict (not a string)."""
        resp = LLMResponse(
            content=None, model="gpt-4", provider="test",
            tool_calls=[{
                "id": "c1",
                "name": "bash",
                "arguments": {"command": "ls"},
            }],
        )
        parsed = parse_tool_calls(resp)
        assert parsed[0]["arguments"] == {"command": "ls"}

    def test_missing_fields_skipped(self):
        """Tool calls with missing id or name are dropped."""
        resp = LLMResponse(
            content=None, model="gpt-4", provider="test",
            tool_calls=[{}],
        )
        parsed = parse_tool_calls(resp)
        assert parsed == []

    def test_missing_name_skipped(self):
        resp = LLMResponse(
            content=None, model="gpt-4", provider="test",
            tool_calls=[{"id": "c1"}],
        )
        parsed = parse_tool_calls(resp)
        assert parsed == []

    def test_missing_id_skipped(self):
        resp = LLMResponse(
            content=None, model="gpt-4", provider="test",
            tool_calls=[{"name": "bash"}],
        )
        parsed = parse_tool_calls(resp)
        assert parsed == []

    def test_valid_mixed_with_malformed(self):
        """Valid tool calls are kept, malformed ones are dropped."""
        resp = LLMResponse(
            content=None, model="gpt-4", provider="test",
            tool_calls=[
                {"id": "c1", "name": "bash", "arguments": '{"cmd": "ls"}'},
                {"id": "", "name": "bad_tool"},  # empty id
                {"id": "c3", "name": "file_writer", "arguments": '{}'},
            ],
        )
        parsed = parse_tool_calls(resp)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "bash"
        assert parsed[1]["name"] == "file_writer"


class TestExtractFinalAnswer:
    def test_with_content(self):
        resp = LLMResponse(content="The answer is 42", model="gpt-4", provider="test")
        assert extract_final_answer(resp) == "The answer is 42"

    def test_with_none_content(self):
        resp = LLMResponse(content=None, model="gpt-4", provider="test")
        assert extract_final_answer(resp) == ""

    def test_with_empty_content(self):
        resp = LLMResponse(content="", model="gpt-4", provider="test")
        assert extract_final_answer(resp) == ""
