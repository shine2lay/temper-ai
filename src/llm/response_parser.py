"""Response parsing utilities for extracting tool calls and answers from LLM output.

Provides pure functions for parsing XML-tagged tool calls, answers, and reasoning
from LLM response text, plus sanitization of tool output to prevent prompt injection.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from src.llm.constants import REGEX_XML_TAG_CLOSING

logger = logging.getLogger(__name__)

# XML tag constants for parsing LLM responses
TOOL_CALL_TAG = "tool_call"
ANSWER_TAG = "answer"
REASONING_TAGS = ["reasoning", "thinking", "think", "thought"]

# Pre-compiled regex patterns for performance (compiled once at module load)
TOOL_CALL_PATTERN = re.compile(rf'<{TOOL_CALL_TAG}{REGEX_XML_TAG_CLOSING}{TOOL_CALL_TAG}>', re.DOTALL)
ANSWER_PATTERN = re.compile(rf'<{ANSWER_TAG}{REGEX_XML_TAG_CLOSING}{ANSWER_TAG}>', re.DOTALL)

# Pattern to match structural tags in tool output (for sanitization) (AG-02)
# Covers: tool_call, answer, reasoning, thinking, think, thought,
# and role delimiters (Assistant:, User:, System:) that could be injected
_SANITIZE_TAGS = [TOOL_CALL_TAG, ANSWER_TAG] + REASONING_TAGS
_TOOL_RESULT_SANITIZE_PATTERN = re.compile(
    r'<\s*/?\s*(?:' + '|'.join(re.escape(t) for t in _SANITIZE_TAGS) + r')[^>]*>'
    r'|(?:^|\n)\s*(?:Assistant|User|System|Human)\s*:',
    re.IGNORECASE | re.MULTILINE,
)
REASONING_PATTERNS = {
    tag: re.compile(f'<{tag}{REGEX_XML_TAG_CLOSING}{tag}>', re.DOTALL)
    for tag in REASONING_TAGS
}


def _extract_tool_calls_from_text(text: str) -> List[Dict[str, Any]]:
    """Extract tool call dicts from text containing <tool_call> tags."""
    tool_calls = []
    for match in TOOL_CALL_PATTERN.findall(text):
        try:
            tool_call = json.loads(match.strip())
            if "name" in tool_call:
                tool_calls.append(tool_call)
        except json.JSONDecodeError:
            logger.warning(
                "Malformed JSON in <tool_call> tag: %s",
                match[:200],  # noqa: scanner: skip-magic
            )
    return tool_calls


# Literal tag strings used for replacement and detection
_TOOL_CALL_OPEN_TAG = "<tool_call>"
_TOOL_CALL_CLOSE_TAG = "</tool_call>"

# HTML-encoded tool_call tags that some models produce in multi-turn
_HTML_TOOL_CALL_OPEN = "&lt;tool_call&gt;"
_HTML_TOOL_CALL_CLOSE = "&lt;/tool_call&gt;"


def _extract_bare_json_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Extract tool call dicts from bare JSON objects in text.

    Scans for JSON objects containing a "name" key, which indicates
    a tool call. Uses json.JSONDecoder().raw_decode() for robust
    parsing of nested JSON (e.g., FileWriter content parameters).
    """
    tool_calls = []
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(text):
        idx = text.find("{", pos)
        if idx == -1:
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            if isinstance(obj, dict) and "name" in obj:
                # Normalize "arguments" → "parameters" for compatibility
                if "arguments" in obj and "parameters" not in obj:
                    obj["parameters"] = obj.pop("arguments")
                tool_calls.append(obj)
            pos = end
        except json.JSONDecodeError:
            pos = idx + 1
    return tool_calls


def parse_tool_calls(llm_response: str) -> List[Dict[str, Any]]:
    """Parse tool calls from LLM response.

    Looks for function calling format like:
    <tool_call>
    {"name": "calculator", "parameters": {"expression": "2+2"}}
    </tool_call>

    Also handles HTML-encoded variants (&lt;tool_call&gt;) that some
    models produce in multi-turn conversations.

    Args:
        llm_response: Raw LLM response text

    Returns:
        List of tool call dicts with 'name' and 'parameters' keys
    """
    tool_calls = _extract_tool_calls_from_text(llm_response)

    # Fallback: some models HTML-encode the tags in multi-turn
    if not tool_calls and _HTML_TOOL_CALL_OPEN in llm_response:
        decoded = llm_response.replace(
            _HTML_TOOL_CALL_OPEN, _TOOL_CALL_OPEN_TAG
        ).replace(
            _HTML_TOOL_CALL_CLOSE, _TOOL_CALL_CLOSE_TAG
        )
        tool_calls = _extract_tool_calls_from_text(decoded)
        if tool_calls:
            logger.info(
                "Recovered %d tool call(s) from HTML-encoded tags",
                len(tool_calls),
            )

    # Fallback: recover bare JSON tool calls from text
    if not tool_calls:
        tool_calls = _extract_bare_json_tool_calls(llm_response)
        if tool_calls:
            logger.info(
                "Recovered %d tool call(s) from bare JSON in text",
                len(tool_calls),
            )

    # Diagnostic: detect tool calls written as text but not parsed
    if not tool_calls and _TOOL_CALL_OPEN_TAG in llm_response:
        unclosed = llm_response.count(_TOOL_CALL_OPEN_TAG)
        closed = llm_response.count(_TOOL_CALL_CLOSE_TAG)
        logger.warning(
            "Response contains <tool_call> text (%d open, %d close) "
            "but 0 valid tool calls parsed — possible truncation or "
            "malformed XML",
            unclosed,
            closed,
        )

    return tool_calls


def sanitize_tool_output(text: str) -> str:
    """Escape tool_call tags in tool output to prevent prompt injection.

    Tool results are injected into the prompt and re-parsed by the LLM.
    If a tool returns text containing <tool_call>...</tool_call>, the
    parser would treat it as a real tool invocation. This escapes those
    tags so they are treated as literal text.

    Args:
        text: Raw tool output string

    Returns:
        Sanitized string with tool_call tags escaped
    """
    text = str(text)
    return _TOOL_RESULT_SANITIZE_PATTERN.sub(
        lambda m: m.group(0).replace('<', '&lt;').replace('>', '&gt;'),
        text,
    )


def extract_final_answer(llm_response: str) -> str:
    """Extract final answer from LLM response.

    Looks for <answer> tags or returns full response if not found.

    Args:
        llm_response: LLM response text

    Returns:
        Extracted answer
    """
    answer_match = ANSWER_PATTERN.search(llm_response)
    if answer_match:
        return answer_match.group(1).strip()

    return llm_response.strip()


def extract_reasoning(llm_response: str) -> Optional[str]:
    """Extract reasoning/thought process from LLM response.

    Looks for <reasoning>, <thinking>, or <thought> tags.

    Args:
        llm_response: LLM response text

    Returns:
        Extracted reasoning or None
    """
    for tag in REASONING_TAGS:
        pattern = REASONING_PATTERNS[tag]
        match = pattern.search(llm_response)
        if match:
            return match.group(1).strip()

    return None
