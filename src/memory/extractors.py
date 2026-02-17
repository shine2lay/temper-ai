"""LLM-based procedural memory extraction.

After a successful agent run, this module can extract actionable
patterns (rules, best-practices, lessons) from agent output text
using the agent's own LLM.
"""

from __future__ import annotations

import re
from typing import Callable, List

MAX_PATTERNS_PER_EXTRACTION = 5
MAX_PATTERN_LENGTH = 500

EXTRACTION_PROMPT = """\
Analyze the following agent output and extract actionable procedural \
patterns — rules, best-practices, or lessons learned that could help \
future executions of similar tasks.

Return ONLY a numbered list (1. 2. 3. etc.) of patterns. Each pattern \
should be a concise, actionable statement. Return at most {max_patterns} \
patterns. If no clear patterns can be extracted, return "NONE".

Agent output:
---
{text}
---
"""

_NUMBERED_ITEM_RE = re.compile(r"^\s*\d+[\.\)][ \t]*(.+)", re.MULTILINE)


def extract_procedural_patterns(
    text: str,
    llm_fn: Callable[[str], str],
) -> List[str]:
    """Extract procedural patterns from *text* using an LLM.

    Args:
        text: Agent output text to analyse.
        llm_fn: Callable that takes a prompt string and returns the LLM
                 response as a string (e.g. ``lambda p: llm.complete(p).content``).

    Returns:
        List of pattern strings (may be empty).

    Raises:
        Whatever *llm_fn* raises — callers should handle gracefully.
    """
    if not text or not text.strip():
        return []

    prompt = EXTRACTION_PROMPT.format(
        text=text,
        max_patterns=MAX_PATTERNS_PER_EXTRACTION,
    )
    response = llm_fn(prompt)
    return _parse_patterns(response)


def _parse_patterns(response: str) -> List[str]:
    """Parse numbered list items from an LLM response string."""
    if not response or "NONE" in response.upper():
        return []

    patterns: List[str] = []
    for match in _NUMBERED_ITEM_RE.finditer(response):
        pattern = match.group(1).strip()
        if pattern:
            if len(pattern) > MAX_PATTERN_LENGTH:
                pattern = pattern[:MAX_PATTERN_LENGTH]
            patterns.append(pattern)
        if len(patterns) >= MAX_PATTERNS_PER_EXTRACTION:
            break
    return patterns
