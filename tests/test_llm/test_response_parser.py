"""Tests for temper_ai/llm/response_parser.py.

Covers pure-function parsing utilities:
- parse_tool_calls: XML tags, HTML-encoded tags, bare JSON fallback, edge cases
- sanitize_tool_output: escaping structural tags and role delimiters
- extract_final_answer: <answer> tag extraction or full-text fallback
- extract_reasoning: <reasoning>/<thinking>/<think>/<thought> tag extraction
"""

import pytest

from temper_ai.llm.response_parser import (
    extract_final_answer,
    extract_reasoning,
    parse_tool_calls,
    sanitize_tool_output,
)


class TestParseToolCalls:
    """Tests for parse_tool_calls — all parsing paths."""

    def test_simple_xml_tag(self):
        """Parses a single well-formed <tool_call> tag."""
        response = '<tool_call>{"name": "calc", "parameters": {"x": 1}}</tool_call>'
        result = parse_tool_calls(response)
        assert len(result) == 1
        assert result[0]["name"] == "calc"
        assert result[0]["parameters"] == {"x": 1}

    def test_multiple_tool_calls(self):
        """Parses multiple <tool_call> tags in a single response."""
        response = (
            '<tool_call>{"name": "add", "parameters": {"a": 1}}</tool_call>\n'
            '<tool_call>{"name": "sub", "parameters": {"b": 2}}</tool_call>'
        )
        result = parse_tool_calls(response)
        assert len(result) == 2
        assert result[0]["name"] == "add"
        assert result[1]["name"] == "sub"

    def test_html_encoded_tags(self):
        """Falls back to HTML-decoded tags when &lt;tool_call&gt; form is present."""
        response = (
            '&lt;tool_call&gt;{"name": "calc", "parameters": {}}&lt;/tool_call&gt;'
        )
        result = parse_tool_calls(response)
        assert len(result) == 1
        assert result[0]["name"] == "calc"

    def test_bare_json_fallback(self):
        """Falls back to bare JSON extraction when no XML tags present."""
        response = 'Sure, here: {"name": "calc", "parameters": {}}'
        result = parse_tool_calls(response)
        assert len(result) == 1
        assert result[0]["name"] == "calc"

    def test_bare_json_arguments_normalization(self):
        """'arguments' key is normalized to 'parameters' in bare JSON fallback."""
        response = '{"name": "calc", "arguments": {"x": 5}}'
        result = parse_tool_calls(response)
        assert len(result) == 1
        assert "parameters" in result[0]
        assert result[0]["parameters"] == {"x": 5}
        assert "arguments" not in result[0]

    def test_malformed_json_in_tag_skipped(self):
        """Malformed JSON inside <tool_call> tags is skipped without raising."""
        response = "<tool_call>not-valid-json!!!</tool_call>"
        result = parse_tool_calls(response)
        assert result == []

    def test_empty_response(self):
        """Empty response returns an empty list."""
        result = parse_tool_calls("")
        assert result == []

    def test_no_tool_calls_returns_empty(self):
        """Plain text with no tool calls returns empty list."""
        result = parse_tool_calls("Hello, how can I help you today?")
        assert result == []

    def test_nested_json_parameters(self):
        """Handles deeply nested JSON parameters inside XML tags."""
        response = (
            '<tool_call>{"name": "writer", "parameters": '
            '{"data": {"key": "value", "list": [1, 2, 3]}}}</tool_call>'
        )
        result = parse_tool_calls(response)
        assert len(result) == 1
        assert result[0]["parameters"]["data"]["list"] == [1, 2, 3]

    def test_tool_call_without_name_skipped(self):
        """JSON in tag without 'name' key is not included in results."""
        response = '<tool_call>{"parameters": {"x": 1}}</tool_call>'
        result = parse_tool_calls(response)
        assert result == []

    def test_xml_tag_with_surrounding_text(self):
        """Extracts tool call even when surrounded by prose text."""
        response = (
            "I will now call the tool.\n"
            '<tool_call>{"name": "search", "parameters": {"q": "hello"}}</tool_call>\n'
            "Done."
        )
        result = parse_tool_calls(response)
        assert len(result) == 1
        assert result[0]["name"] == "search"

    def test_bare_json_no_name_key_not_included(self):
        """Bare JSON without 'name' key is not extracted as a tool call."""
        response = '{"foo": "bar", "baz": 42}'
        result = parse_tool_calls(response)
        assert result == []

    def test_multiline_json_in_tag(self):
        """Parses tool call JSON spanning multiple lines inside a tag."""
        response = (
            "<tool_call>\n"
            '{"name": "format", "parameters": {"text": "hello\\nworld"}}\n'
            "</tool_call>"
        )
        result = parse_tool_calls(response)
        assert len(result) == 1
        assert result[0]["name"] == "format"


class TestSanitizeToolOutput:
    """Tests for sanitize_tool_output — prompt injection prevention."""

    def test_escapes_tool_call_open_tag(self):
        """Opening <tool_call> tag is HTML-escaped."""
        result = sanitize_tool_output("data <tool_call> more")
        assert "&lt;tool_call&gt;" in result
        assert "<tool_call>" not in result

    def test_escapes_tool_call_close_tag(self):
        """Closing </tool_call> tag is HTML-escaped."""
        result = sanitize_tool_output("data </tool_call> more")
        assert "&lt;/tool_call&gt;" in result
        assert "</tool_call>" not in result

    def test_escapes_answer_tag(self):
        """<answer> tag is HTML-escaped."""
        result = sanitize_tool_output("<answer>42</answer>")
        assert "&lt;answer&gt;" in result
        assert "&lt;/answer&gt;" in result
        assert "<answer>" not in result

    def test_escapes_reasoning_tag(self):
        """<reasoning> tag is HTML-escaped."""
        result = sanitize_tool_output("<reasoning>my thought</reasoning>")
        assert "&lt;reasoning&gt;" in result
        assert "<reasoning>" not in result

    def test_escapes_thinking_tag(self):
        """<thinking> tag is HTML-escaped."""
        result = sanitize_tool_output("<thinking>consider this</thinking>")
        assert "&lt;thinking&gt;" in result
        assert "<thinking>" not in result

    def test_escapes_think_tag(self):
        """<think> tag is HTML-escaped."""
        result = sanitize_tool_output("<think>step 1</think>")
        assert "&lt;think&gt;" in result
        assert "<think>" not in result

    def test_escapes_thought_tag(self):
        """<thought> tag is HTML-escaped."""
        result = sanitize_tool_output("<thought>my idea</thought>")
        assert "&lt;thought&gt;" in result
        assert "<thought>" not in result

    def test_role_delimiter_assistant_matched(self):
        """Role delimiter 'Assistant:' at line start is handled without error."""
        text = "output\nAssistant: hello"
        result = sanitize_tool_output(text)
        # Pattern matches but no <> to replace — text is returned as-is
        assert isinstance(result, str)
        assert "Assistant:" in result

    def test_safe_text_unchanged(self):
        """Text with no structural tags is returned unchanged."""
        text = "This is a safe tool result with no tags."
        assert sanitize_tool_output(text) == text

    def test_empty_string(self):
        """Empty string input returns empty string."""
        assert sanitize_tool_output("") == ""

    def test_non_string_input_converted(self):
        """Non-string inputs are converted via str() before sanitizing."""
        result = sanitize_tool_output(42)
        assert result == "42"


class TestExtractFinalAnswer:
    """Tests for extract_final_answer — <answer> tag extraction."""

    def test_answer_tag_present(self):
        """Extracts content between <answer> tags."""
        response = "Some reasoning. <answer>42</answer>"
        assert extract_final_answer(response) == "42"

    def test_no_answer_tag_returns_full_text(self):
        """Returns full response (stripped) when no <answer> tag found."""
        response = "  The answer is 42.  "
        assert extract_final_answer(response) == "The answer is 42."

    def test_empty_answer_tags(self):
        """Returns empty string for empty <answer></answer> tags."""
        response = "<answer></answer>"
        assert extract_final_answer(response) == ""

    def test_answer_tag_strips_whitespace(self):
        """Strips whitespace from extracted answer content."""
        response = "<answer>  Hello World  </answer>"
        assert extract_final_answer(response) == "Hello World"

    def test_answer_with_surrounding_text(self):
        """Extracts only the answer even when surrounded by other text."""
        response = "Thinking... <answer>Final answer here</answer> Done."
        assert extract_final_answer(response) == "Final answer here"

    def test_multiline_answer(self):
        """Handles multiline content inside <answer> tags."""
        response = "<answer>line1\nline2\nline3</answer>"
        result = extract_final_answer(response)
        assert "line1" in result
        assert "line3" in result


class TestExtractReasoning:
    """Tests for extract_reasoning — reasoning block extraction."""

    def test_reasoning_tag(self):
        """Extracts content from <reasoning> tags."""
        response = "<reasoning>I think step 1 then step 2.</reasoning>"
        assert extract_reasoning(response) == "I think step 1 then step 2."

    def test_thinking_tag(self):
        """Extracts content from <thinking> tags."""
        response = "<thinking>Let me consider this carefully.</thinking>"
        assert extract_reasoning(response) == "Let me consider this carefully."

    def test_think_tag(self):
        """Extracts content from <think> tags."""
        response = "<think>Hmm, what about X?</think>"
        assert extract_reasoning(response) == "Hmm, what about X?"

    def test_thought_tag(self):
        """Extracts content from <thought> tags."""
        response = "<thought>Yes, this makes sense.</thought>"
        assert extract_reasoning(response) == "Yes, this makes sense."

    def test_no_reasoning_tag_returns_none(self):
        """Returns None when no reasoning tags are present."""
        response = "The answer is 42."
        assert extract_reasoning(response) is None

    def test_empty_response_returns_none(self):
        """Returns None for empty string input."""
        assert extract_reasoning("") is None

    def test_reasoning_strips_whitespace(self):
        """Strips leading/trailing whitespace from extracted reasoning."""
        response = "<reasoning>  My thoughts here.  </reasoning>"
        assert extract_reasoning(response) == "My thoughts here."

    def test_first_matching_tag_wins(self):
        """When multiple reasoning block types present, first matching tag wins."""
        # 'reasoning' is first in REASONING_TAGS list, so it should win
        response = (
            "<reasoning>first reasoning</reasoning> "
            "<thinking>second thinking</thinking>"
        )
        result = extract_reasoning(response)
        assert result == "first reasoning"

    def test_multiline_reasoning(self):
        """Handles multiline reasoning block content."""
        response = "<reasoning>\nStep 1: analyze\nStep 2: conclude\n</reasoning>"
        result = extract_reasoning(response)
        assert "Step 1" in result
        assert "Step 2" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
