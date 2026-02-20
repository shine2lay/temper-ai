"""Context window management (R0.5).

Provides token counting and prompt trimming strategies to keep prompts
within model context window limits.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Approximate characters per token for quick estimation
_CHARS_PER_TOKEN = 4

# Default model context window size (tokens)
DEFAULT_MODEL_CONTEXT = 128000  # scanner: skip-magic

_TRUNCATED_MARKER = "\n\n[Content truncated to fit context window]"


def count_tokens(text: str, method: str = "approximate") -> int:
    """Count tokens in text using the specified method.

    Args:
        text: Input text to count tokens for.
        method: Either "tiktoken" (accurate) or "approximate" (fast).

    Returns:
        Estimated token count.
    """
    if method == "tiktoken":
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            logger.warning("tiktoken not installed, falling back to approximate")
    return len(text) // _CHARS_PER_TOKEN


def trim_to_budget(
    text: str,
    max_tokens: int,
    reserved_output: int,
    strategy: str,
    token_counter: str = "approximate",  # noqa: S107
) -> str:
    """Trim text to fit within the token budget.

    Args:
        text: Input text to potentially trim.
        max_tokens: Maximum context window tokens.
        reserved_output: Tokens reserved for model output.
        strategy: One of "truncate", "sliding_window", "summarize".
        token_counter: Token counting method.

    Returns:
        Text trimmed to fit within the budget, or unchanged if within limits.
    """
    budget = max_tokens - reserved_output
    if budget <= 0:
        return text

    current_tokens = count_tokens(text, token_counter)
    if current_tokens <= budget:
        return text

    if strategy == "sliding_window":
        return _sliding_window(text, budget, token_counter)
    if strategy == "summarize":
        return _summarize(text, budget, token_counter)
    # Default: truncate
    return _truncate(text, budget, token_counter)


def _truncate(text: str, target_tokens: int, token_counter: str) -> str:
    """Truncate text from the end, keeping the beginning."""
    target_chars = target_tokens * _CHARS_PER_TOKEN
    if len(text) <= target_chars:
        return text
    marker_budget = len(_TRUNCATED_MARKER)
    trimmed = text[: target_chars - marker_budget]
    return trimmed + _TRUNCATED_MARKER


def _sliding_window(text: str, target_tokens: int, token_counter: str) -> str:
    """Keep the most recent content (truncate from beginning)."""
    target_chars = target_tokens * _CHARS_PER_TOKEN
    if len(text) <= target_chars:
        return text
    marker = "[Earlier content omitted]\n\n"
    marker_budget = len(marker)
    trimmed = text[-(target_chars - marker_budget):]
    return marker + trimmed


def _summarize(text: str, target_tokens: int, token_counter: str) -> str:
    """Placeholder: truncate with a summary marker.

    Full summarization would require an LLM call; for v1 this simply
    truncates with a descriptive marker.
    """
    target_chars = target_tokens * _CHARS_PER_TOKEN
    if len(text) <= target_chars:
        return text
    marker = "\n\n[Content summarized to fit context window]"
    marker_budget = len(marker)
    trimmed = text[: target_chars - marker_budget]
    return trimmed + marker
