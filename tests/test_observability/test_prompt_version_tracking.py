"""Tests for WI-4: Prompt version tracking through observability pipeline.

Tests prompt_template_hash and prompt_template_source fields in the
observability pipeline: LLMCallData, LLMCallTrackingData, buffer params,
and backward compatibility.
"""
import pytest
from datetime import datetime, timezone

from temper_ai.observability.backend import LLMCallData
from temper_ai.observability._tracker_helpers import LLMCallTrackingData
from temper_ai.observability.buffer import LLMCallBufferParams, BufferedLLMCall


class TestLLMCallDataPromptFields:
    """Test prompt versioning fields on LLMCallData."""

    def test_defaults_none(self) -> None:
        """prompt_template_hash and prompt_template_source default to None."""
        data = LLMCallData(
            prompt="test",
            response="ok",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
        )
        assert data.prompt_template_hash is None
        assert data.prompt_template_source is None

    def test_with_values(self) -> None:
        """Fields accept values."""
        data = LLMCallData(
            prompt="test",
            response="ok",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            prompt_template_hash="abc123def456abcd",
            prompt_template_source="configs/prompts/researcher.txt",
        )
        assert data.prompt_template_hash == "abc123def456abcd"
        assert data.prompt_template_source == "configs/prompts/researcher.txt"


class TestLLMCallTrackingDataPromptFields:
    """Test prompt versioning on LLMCallTrackingData."""

    def test_defaults_none(self) -> None:
        """Fields default to None."""
        data = LLMCallTrackingData(
            agent_id="a-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="ok",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
        )
        assert data.prompt_template_hash is None
        assert data.prompt_template_source is None

    def test_with_values(self) -> None:
        """Fields accept values."""
        data = LLMCallTrackingData(
            agent_id="a-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="ok",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            prompt_template_hash="abc123",
            prompt_template_source="inline",
        )
        assert data.prompt_template_hash == "abc123"
        assert data.prompt_template_source == "inline"


class TestBufferPromptFields:
    """Test prompt versioning fields on buffer params."""

    def test_buffer_params_defaults(self) -> None:
        """LLMCallBufferParams fields default to None."""
        params = LLMCallBufferParams(
            llm_call_id="lc-1",
            agent_id="a-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="ok",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(timezone.utc),
        )
        assert params.prompt_template_hash is None
        assert params.prompt_template_source is None

    def test_buffered_call_defaults(self) -> None:
        """BufferedLLMCall fields default to None."""
        call = BufferedLLMCall(
            llm_call_id="lc-1",
            agent_id="a-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="ok",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(timezone.utc),
        )
        assert call.prompt_template_hash is None
        assert call.prompt_template_source is None

    def test_buffer_params_with_values(self) -> None:
        """Buffer params accept prompt versioning values."""
        params = LLMCallBufferParams(
            llm_call_id="lc-1",
            agent_id="a-1",
            provider="openai",
            model="gpt-4",
            prompt="test",
            response="ok",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            start_time=datetime.now(timezone.utc),
            prompt_template_hash="abc123",
            prompt_template_source="inline",
        )
        assert params.prompt_template_hash == "abc123"
        assert params.prompt_template_source == "inline"


class TestFailoverFieldsOnLLMCallData:
    """Test failover fields coexist with prompt fields."""

    def test_all_new_fields(self) -> None:
        """All 4 new fields (failover + prompt) set together."""
        data = LLMCallData(
            prompt="test",
            response="ok",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=100,
            estimated_cost_usd=0.01,
            failover_sequence=["openai:gpt-4:TimeoutError", "anthropic:claude:success"],
            failover_from_provider="openai",
            prompt_template_hash="abc123def456abcd",
            prompt_template_source="inline",
        )
        assert len(data.failover_sequence) == 2
        assert data.failover_from_provider == "openai"
        assert data.prompt_template_hash == "abc123def456abcd"
        assert data.prompt_template_source == "inline"
