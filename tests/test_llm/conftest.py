"""LLM test fixtures — mock providers for testing the service layer."""

import pytest

from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.llm.providers.base import BaseLLM, StreamCallback


class MockProvider(BaseLLM):
    """A mock LLM provider that returns canned responses in sequence.

    Usage:
        responses = [
            LLMResponse(content=None, model="mock", provider="mock",
                        tool_calls=[...], finish_reason="tool_calls"),
            LLMResponse(content="Done!", model="mock", provider="mock",
                        finish_reason="stop"),
        ]
        provider = MockProvider(responses)
        # First call returns responses[0], second returns responses[1], etc.
    """

    def __init__(self, responses: list[LLMResponse], **kwargs):
        super().__init__(model="mock-model", base_url="http://mock", **kwargs)
        self._responses = list(responses)
        self._call_index = 0
        self.calls: list[dict] = []  # record what was called

    def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        self.calls.append({"method": "complete", "messages": messages, "kwargs": kwargs})
        return self._next_response()

    def stream(
        self, messages: list[dict], on_chunk: StreamCallback | None = None, **kwargs
    ) -> LLMResponse:
        self.calls.append({"method": "stream", "messages": messages, "kwargs": kwargs})
        resp = self._next_response()
        if on_chunk:
            if resp.content:
                on_chunk(LLMStreamChunk(content=resp.content, done=False, model=resp.model))
            on_chunk(LLMStreamChunk(content="", done=True, finish_reason=resp.finish_reason))
        return resp

    def _next_response(self) -> LLMResponse:
        if self._call_index >= len(self._responses):
            raise RuntimeError(
                f"MockProvider exhausted: {self._call_index} calls but only "
                f"{len(self._responses)} responses configured"
            )
        resp = self._responses[self._call_index]
        self._call_index += 1
        return resp

    # Abstract methods (unused — complete/stream are overridden)
    def _build_request(self, messages, **kwargs):
        return {}

    def _parse_response(self, response, latency_ms):
        return LLMResponse(content="", model="mock", provider="mock")

    def _get_headers(self):
        return {}

    def _get_endpoint(self):
        return "/mock"

    def _consume_stream(self, response, on_chunk):
        return LLMResponse(content="", model="mock", provider="mock")


@pytest.fixture
def mock_provider():
    """Create a MockProvider factory."""
    def _factory(responses: list[LLMResponse], **kwargs) -> MockProvider:
        return MockProvider(responses, **kwargs)
    return _factory
