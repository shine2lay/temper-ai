"""Prompt injection and sliding window for LLMService.

Formats tool results into text and applies a sliding window
to keep prompt size within bounds across tool-calling iterations.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from temper_ai.llm.response_parser import sanitize_tool_output
from temper_ai.llm.tool_keys import ToolKeys

logger = logging.getLogger(__name__)


def inject_results(
    system_prompt: str,
    llm_response_content: str,
    tool_results: List[Dict[str, Any]],
    conversation_turns: List[str],
    max_tool_result_size: int,
    max_prompt_length: int,
    remaining_tool_calls: Optional[int] = None,
) -> str:
    """Inject tool results into prompt for next iteration.

    Uses a sliding-window approach to prevent unbounded prompt growth.
    """
    results_text = format_tool_results_text(tool_results, max_tool_result_size, remaining_tool_calls)
    turn_text = "\n\nAssistant: " + llm_response_content + results_text
    conversation_turns.append(turn_text)
    return apply_sliding_window(system_prompt, conversation_turns, max_prompt_length)


def format_tool_results_text(
    tool_results: List[Dict[str, Any]],
    max_tool_result_size: int,
    remaining_tool_calls: Optional[int] = None,
) -> str:
    """Format tool results into text for prompt injection."""
    results_parts = ["\n\nTool Results:\n"]
    for result in tool_results:
        results_parts.append(f"\nTool: {result[ToolKeys.NAME]}\n")
        results_parts.append(f"Parameters: {json.dumps(result[ToolKeys.PARAMETERS])}\n")

        if result[ToolKeys.SUCCESS]:
            safe_result = sanitize_tool_output(str(result[ToolKeys.RESULT]))
            if len(safe_result) > max_tool_result_size:
                original_size = len(safe_result)
                safe_result = safe_result[:max_tool_result_size]
                safe_result += f"\n[truncated — {original_size:,} total chars, showing first {max_tool_result_size:,}]"
            results_parts.append(f"Result: {safe_result}\n")
        else:
            safe_error = sanitize_tool_output(str(result[ToolKeys.ERROR]))
            if len(safe_error) > max_tool_result_size:
                original_size = len(safe_error)
                safe_error = safe_error[:max_tool_result_size]
                safe_error += f"\n[truncated — {original_size:,} total chars, showing first {max_tool_result_size:,}]"
            results_parts.append(f"Error: {safe_error}\n")

    if remaining_tool_calls is not None:
        if remaining_tool_calls > 0:
            results_parts.append(
                f"\n[System Info: You have {remaining_tool_calls} tool call(s) remaining in your budget.]\n"
            )
        else:
            results_parts.append(
                "\n[System Info: This is your last tool call. Budget exhausted after this iteration.]\n"
            )

    return ''.join(results_parts)


def apply_sliding_window(
    system_prompt: str,
    conversation_turns: List[str],
    max_prompt_length: int,
) -> str:
    """Apply sliding window to conversation turns to fit within max_prompt_length."""
    suffix = "\n\nPlease continue:"
    budget = max_prompt_length - len(system_prompt) - len(suffix)

    if budget <= 0:
        recent_turn = sanitize_tool_output(conversation_turns[-1])
        return system_prompt + recent_turn + suffix

    included_turns: List[str] = []
    total_turn_chars = 0
    for turn in reversed(conversation_turns):
        if total_turn_chars + len(turn) > budget:
            break
        included_turns.append(turn)
        total_turn_chars += len(turn)

    included_turns.reverse()

    dropped_count = len(conversation_turns) - len(included_turns)
    truncation_marker = ""
    if dropped_count > 0:
        truncation_marker = f"\n\n[...{dropped_count} earlier iteration(s) omitted for brevity...]\n"

    # NOTE: Do NOT re-sanitize assembled turns. Tool results are already
    # sanitized individually. Re-sanitizing escapes the LLM's own <tool_call> tags.
    assembled_turns = truncation_marker + ''.join(included_turns)

    # Prune old turns to free memory
    if dropped_count > 0:
        conversation_turns[:] = included_turns

    return system_prompt + assembled_turns + suffix
