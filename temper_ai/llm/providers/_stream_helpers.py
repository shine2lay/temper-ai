"""Shared helpers for stream processing across LLM providers.

Reduces code duplication in ollama.py and vllm_provider.py where sync/async
stream consumers are nearly identical.
"""
from typing import Any, Callable, List, Optional

from temper_ai.llm.providers.base import LLMStreamChunk


def process_chunk_content(
    chunk_content: str,
    chunk_type: str,
    content_parts: List[str],
    thinking_parts: List[str],
    on_chunk: Callable[[LLMStreamChunk], None],
    model: str,
) -> None:
    """Process and emit chunk content (shared by sync/async)."""
    if not chunk_content:
        return

    if chunk_type == "thinking":
        thinking_parts.append(chunk_content)
    else:
        content_parts.append(chunk_content)

    on_chunk(LLMStreamChunk(
        content=chunk_content,
        chunk_type=chunk_type,
        done=False,
        model=model,
    ))


def emit_final_chunk(
    on_chunk: Callable[[LLMStreamChunk], None],
    model: str,
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    finish_reason: Optional[str],
) -> None:
    """Emit final completion chunk with token counts."""
    on_chunk(LLMStreamChunk(
        content="",
        chunk_type="content",
        done=True,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        finish_reason=finish_reason,
    ))


def build_stream_result(
    content_parts: List[str],
    model: str,
    provider: str,
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    finish_reason: Optional[str],
) -> Any:  # Returns LLMResponse
    """Build final LLMResponse from accumulated stream chunks."""
    from temper_ai.llm.providers.base import LLMResponse

    full_content = "".join(content_parts)
    total = (prompt_tokens or 0) + (completion_tokens or 0) or None

    return LLMResponse(
        content=full_content,
        model=model,
        provider=provider,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        finish_reason=finish_reason,
        raw_response=None,
    )
