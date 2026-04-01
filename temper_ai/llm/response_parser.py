"""Response parsing — extract tool calls and final answers from LLM responses.

Handles the native tool calling path (OpenAI function calling format).
"""

import json
import logging
from typing import Any

from temper_ai.llm.models import LLMResponse

logger = logging.getLogger(__name__)


def parse_tool_calls(response: LLMResponse) -> list[dict[str, Any]]:
    """Extract tool calls from an LLM response.

    Returns a list of dicts, each with:
        - id: tool call ID (for message threading)
        - name: tool/function name
        - arguments: parsed dict of arguments
    """
    if not response.tool_calls:
        return []

    parsed = []
    for tc in response.tool_calls:
        tc_id = tc.get("id", "")
        tc_name = tc.get("name", "")

        if not tc_id or not tc_name:
            logger.warning(
                "Skipping malformed tool call (missing id or name): %s",
                {k: tc.get(k) for k in ("id", "name")},
            )
            continue

        args = tc.get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse tool call arguments for '%s': %s",
                    tc_name,
                    args[:200],
                )
                args = {"_raw": args}

        parsed.append({
            "id": tc_id,
            "name": tc_name,
            "arguments": args,
        })

    return parsed


def extract_final_answer(response: LLMResponse) -> str:
    """Extract the final text answer from an LLM response."""
    return response.content or ""
