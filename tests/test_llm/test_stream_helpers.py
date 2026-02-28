"""Tests for temper_ai/llm/providers/_stream_helpers.py.

Covers process_chunk_content, emit_final_chunk, and build_stream_result
including callback behavior, list mutation, and LLMResponse construction.
"""

from unittest.mock import MagicMock

import pytest

from temper_ai.llm.providers._stream_helpers import (
    build_stream_result,
    emit_final_chunk,
    process_chunk_content,
)
from temper_ai.llm.providers.base import LLMStreamChunk


class TestProcessChunkContent:
    """Tests for process_chunk_content helper."""

    def test_empty_content_is_noop(self) -> None:
        """Empty chunk content leaves lists unchanged and does not call callback."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        on_chunk = MagicMock()

        process_chunk_content(
            "", "content", content_parts, thinking_parts, on_chunk, "gpt-4"
        )

        assert content_parts == []
        assert thinking_parts == []
        on_chunk.assert_not_called()

    def test_content_type_appends_to_content_parts(self) -> None:
        """Chunk type 'content' appends to content_parts and calls callback."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        on_chunk = MagicMock()

        process_chunk_content(
            "hello", "content", content_parts, thinking_parts, on_chunk, "gpt-4"
        )

        assert content_parts == ["hello"]
        assert thinking_parts == []
        on_chunk.assert_called_once()
        chunk: LLMStreamChunk = on_chunk.call_args[0][0]
        assert isinstance(chunk, LLMStreamChunk)
        assert chunk.done is False
        assert chunk.content == "hello"
        assert chunk.chunk_type == "content"
        assert chunk.model == "gpt-4"

    def test_thinking_type_appends_to_thinking_parts(self) -> None:
        """Chunk type 'thinking' appends to thinking_parts, not content_parts."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        on_chunk = MagicMock()

        process_chunk_content(
            "inner thought",
            "thinking",
            content_parts,
            thinking_parts,
            on_chunk,
            "claude-3",
        )

        assert thinking_parts == ["inner thought"]
        assert content_parts == []
        on_chunk.assert_called_once()
        chunk: LLMStreamChunk = on_chunk.call_args[0][0]
        assert chunk.chunk_type == "thinking"
        assert chunk.content == "inner thought"
        assert chunk.done is False

    def test_multiple_chunks_accumulate(self) -> None:
        """Multiple calls accumulate in the lists."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        on_chunk = MagicMock()

        process_chunk_content(
            "A", "content", content_parts, thinking_parts, on_chunk, "m"
        )
        process_chunk_content(
            "B", "thinking", content_parts, thinking_parts, on_chunk, "m"
        )
        process_chunk_content(
            "C", "content", content_parts, thinking_parts, on_chunk, "m"
        )

        assert content_parts == ["A", "C"]
        assert thinking_parts == ["B"]
        assert on_chunk.call_count == 3


class TestEmitFinalChunk:
    """Tests for emit_final_chunk helper."""

    def test_callback_called_with_done_true(self) -> None:
        """Final chunk has done=True and empty content."""
        on_chunk = MagicMock()
        emit_final_chunk(
            on_chunk,
            "gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            finish_reason="stop",
        )

        on_chunk.assert_called_once()
        chunk: LLMStreamChunk = on_chunk.call_args[0][0]
        assert chunk.done is True
        assert chunk.content == ""

    def test_token_counts_passed_through(self) -> None:
        """Token counts and finish_reason are carried into the final chunk."""
        on_chunk = MagicMock()
        emit_final_chunk(
            on_chunk,
            "my-model",
            prompt_tokens=100,
            completion_tokens=50,
            finish_reason="length",
        )

        chunk: LLMStreamChunk = on_chunk.call_args[0][0]
        assert chunk.prompt_tokens == 100
        assert chunk.completion_tokens == 50
        assert chunk.finish_reason == "length"
        assert chunk.model == "my-model"

    def test_none_token_counts_passed_through(self) -> None:
        """None token counts remain None in the final chunk."""
        on_chunk = MagicMock()
        emit_final_chunk(
            on_chunk,
            "m",
            prompt_tokens=None,
            completion_tokens=None,
            finish_reason=None,
        )

        chunk: LLMStreamChunk = on_chunk.call_args[0][0]
        assert chunk.prompt_tokens is None
        assert chunk.completion_tokens is None
        assert chunk.finish_reason is None


class TestBuildStreamResult:
    """Tests for build_stream_result helper."""

    def test_joins_content_parts_into_single_string(self) -> None:
        """content_parts list is joined into full content string."""
        from temper_ai.llm.providers.base import LLMResponse

        result = build_stream_result(
            content_parts=["Hello", " ", "World"],
            model="gpt-4",
            provider="openai",
            prompt_tokens=10,
            completion_tokens=5,
            finish_reason="stop",
        )
        assert isinstance(result, LLMResponse)
        assert result.content == "Hello World"

    def test_total_tokens_is_sum_of_prompt_and_completion(self) -> None:
        """total_tokens = prompt_tokens + completion_tokens when both provided."""
        result = build_stream_result(
            content_parts=["text"],
            model="gpt-4",
            provider="openai",
            prompt_tokens=100,
            completion_tokens=50,
            finish_reason="stop",
        )
        assert result.total_tokens == 150

    def test_total_tokens_is_none_when_both_token_counts_none(self) -> None:
        """total_tokens is None when both prompt and completion tokens are None."""
        result = build_stream_result(
            content_parts=["text"],
            model="gpt-4",
            provider="openai",
            prompt_tokens=None,
            completion_tokens=None,
            finish_reason=None,
        )
        assert result.total_tokens is None

    def test_correct_fields_on_llm_response(self) -> None:
        """LLMResponse has model, provider, and finish_reason set correctly."""
        result = build_stream_result(
            content_parts=["response"],
            model="llama3",
            provider="ollama",
            prompt_tokens=20,
            completion_tokens=10,
            finish_reason="length",
        )
        assert result.model == "llama3"
        assert result.provider == "ollama"
        assert result.finish_reason == "length"
        assert result.prompt_tokens == 20
        assert result.completion_tokens == 10

    def test_empty_content_parts_produces_empty_string(self) -> None:
        """Empty content_parts list results in empty content string."""
        result = build_stream_result(
            content_parts=[],
            model="m",
            provider="p",
            prompt_tokens=5,
            completion_tokens=3,
            finish_reason="stop",
        )
        assert result.content == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
