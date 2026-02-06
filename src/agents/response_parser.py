"""Response parsing utilities for extracting tool calls and answers from LLM output.

Provides pure functions for parsing XML-tagged tool calls, answers, and reasoning
from LLM response text, plus sanitization of tool output to prevent prompt injection.
"""
import json
import re
from typing import Any, Dict, List, Optional

# XML tag constants for parsing LLM responses
TOOL_CALL_TAG = "tool_call"
ANSWER_TAG = "answer"
REASONING_TAGS = ["reasoning", "thinking", "think", "thought"]

# Pre-compiled regex patterns for performance (compiled once at module load)
TOOL_CALL_PATTERN = re.compile(rf'<{TOOL_CALL_TAG}>(.*?)</{TOOL_CALL_TAG}>', re.DOTALL)
ANSWER_PATTERN = re.compile(rf'<{ANSWER_TAG}>(.*?)</{ANSWER_TAG}>', re.DOTALL)

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
    tag: re.compile(f'<{tag}>(.*?)</{tag}>', re.DOTALL)
    for tag in REASONING_TAGS
}


def parse_tool_calls(llm_response: str) -> List[Dict[str, Any]]:
    """Parse tool calls from LLM response.

    Looks for function calling format like:
    <tool_call>
    {"name": "calculator", "parameters": {"expression": "2+2"}}
    </tool_call>

    Args:
        llm_response: Raw LLM response text

    Returns:
        List of tool call dicts with 'name' and 'parameters' keys
    """
    tool_calls = []

    matches = TOOL_CALL_PATTERN.findall(llm_response)

    for match in matches:
        try:
            tool_call = json.loads(match.strip())
            if "name" in tool_call:
                tool_calls.append(tool_call)
        except json.JSONDecodeError:
            continue

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
    if not isinstance(text, str):
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
