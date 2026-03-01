"""LLM Provider Performance Benchmarks.

This module contains 6 performance benchmarks for LLM operations:
- Mock LLM calls (fast and realistic)
- Async LLM speedup tests
- Provider creation and response parsing

Run with: pytest tests/test_benchmarks/test_performance_llm.py --benchmark-only

Save baseline:
    pytest tests/test_benchmarks/test_performance_llm.py --benchmark-only --benchmark-save=llm

Compare with regression detection:
    pytest tests/test_benchmarks/test_performance_llm.py --benchmark-only \
        --benchmark-compare=llm --benchmark-compare-fail=mean:10%
"""

import asyncio
import time

import pytest

from temper_ai.llm.providers.base import LLMResponse
from temper_ai.llm.providers.ollama import OllamaLLM

# ============================================================================
# CATEGORY 3: LLM Provider Performance (8 benchmarks)
# ============================================================================


@pytest.mark.benchmark(group="llm")
def test_llm_mock_call_fast(mock_llm_fast, benchmark):
    """Benchmark fast mock LLM call (10ms).

    Target: ~10ms
    Measures: LLM wrapper overhead
    """
    result = benchmark(mock_llm_fast.complete, "test prompt")
    assert result is not None
    assert result.content is not None


@pytest.mark.benchmark(group="llm")
def test_llm_mock_call_realistic(mock_llm_realistic, benchmark):
    """Benchmark realistic mock LLM call (100ms).

    Target: ~100ms
    Measures: Typical LLM latency
    """
    result = benchmark(mock_llm_realistic.complete, "test prompt")
    assert result is not None


@pytest.mark.benchmark(group="llm")
@pytest.mark.asyncio
async def test_llm_async_speedup_3_calls(mock_async_llm):
    """Benchmark async LLM speedup with 3 parallel calls.

    Target: 2-3x speedup
    Measures: Async concurrency benefits
    """
    llm = mock_async_llm

    # Sequential execution
    start_seq = time.perf_counter()
    for i in range(3):
        await llm.acomplete(f"prompt {i}")
    sequential_time = time.perf_counter() - start_seq

    # Parallel execution
    start_par = time.perf_counter()
    await asyncio.gather(*[llm.acomplete(f"prompt {i}") for i in range(3)])
    parallel_time = time.perf_counter() - start_par

    speedup = sequential_time / parallel_time

    assert speedup >= 1.9, f"Speedup {speedup:.2f}x below target 2-3x"
    assert speedup <= 3.2, f"Speedup {speedup:.2f}x suspiciously high"

    print(f"Async speedup (3 calls): {speedup:.2f}x")


@pytest.mark.benchmark(group="llm")
@pytest.mark.asyncio
async def test_llm_async_speedup_10_calls(mock_async_llm):
    """Benchmark async LLM speedup with 10 parallel calls.

    Target: 5-8x speedup
    Measures: Async scalability
    """
    llm = mock_async_llm

    # Sequential execution
    start_seq = time.perf_counter()
    for i in range(10):
        await llm.acomplete(f"prompt {i}")
    sequential_time = time.perf_counter() - start_seq

    # Parallel execution
    start_par = time.perf_counter()
    await asyncio.gather(*[llm.acomplete(f"prompt {i}") for i in range(10)])
    parallel_time = time.perf_counter() - start_par

    speedup = sequential_time / parallel_time

    assert speedup >= 4.0, f"Speedup {speedup:.2f}x below expected for 10 calls"

    print(f"Async speedup (10 calls): {speedup:.2f}x")


@pytest.mark.benchmark(group="llm")
def test_llm_provider_creation(benchmark):
    """Benchmark LLM provider instantiation.

    Target: <50ms
    Measures: Provider initialization overhead
    """

    def create_provider():
        return OllamaLLM(model="llama2", base_url="http://localhost:11434")

    result = benchmark(create_provider)
    assert result is not None


@pytest.mark.benchmark(group="llm")
def test_llm_response_parsing(benchmark):
    """Benchmark LLM response parsing.

    Target: <5ms
    Measures: Response deserialization overhead
    """
    raw_response = {
        "model": "test",
        "created_at": "2024-01-01T00:00:00Z",
        "response": "Test response",
        "done": True,
        "total_duration": 1000000,
        "prompt_eval_count": 10,
        "eval_count": 20,
    }

    def parse_response():
        return LLMResponse(
            content=raw_response["response"],
            model=raw_response["model"],
            provider="ollama",
            prompt_tokens=raw_response.get("prompt_eval_count"),
            completion_tokens=raw_response.get("eval_count"),
            total_tokens=raw_response.get("prompt_eval_count", 0)
            + raw_response.get("eval_count", 0),
        )

    result = benchmark(parse_response)
    assert result is not None
