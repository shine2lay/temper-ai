#!/usr/bin/env python3
"""
Demo script showing async LLM provider functionality.

This demonstrates:
1. Async completion with acomplete()
2. Parallel execution with asyncio.gather()
3. Performance improvement from async (2-3x speedup)
"""
import asyncio
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock dependencies to avoid import errors
from unittest.mock import MagicMock


# Create proper exception classes
class LLMError(Exception):
    pass

class LLMTimeoutError(LLMError):
    pass

class LLMRateLimitError(LLMError):
    pass

class LLMAuthenticationError(LLMError):
    pass

class ExecutionContext:
    pass

# Mock modules
sys.modules['temper_ai.llm.cache.llm_cache'] = MagicMock()

# Mock error_handling module
error_handling_mock = MagicMock()
error_handling_mock.retry_with_backoff = lambda func: func
error_handling_mock.RetryStrategy = MagicMock()
sys.modules['temper_ai.shared.utils.error_handling'] = error_handling_mock

# Mock exceptions module with real exception classes
exceptions_mock = MagicMock()
exceptions_mock.LLMError = LLMError
exceptions_mock.LLMTimeoutError = LLMTimeoutError
exceptions_mock.LLMRateLimitError = LLMRateLimitError
exceptions_mock.LLMAuthenticationError = LLMAuthenticationError
exceptions_mock.ExecutionContext = ExecutionContext
sys.modules['temper_ai.shared.utils.exceptions'] = exceptions_mock

# Mock circuit breaker
class CircuitBreaker:
    def __init__(self, name, config):
        pass
    def call(self, func):
        return func()

circuit_breaker_mock = MagicMock()
circuit_breaker_mock.CircuitBreaker = CircuitBreaker
circuit_breaker_mock.CircuitBreakerConfig = lambda: None
circuit_breaker_mock.CircuitBreakerError = Exception
sys.modules['temper_ai.llm.circuit_breaker'] = circuit_breaker_mock

# Now import after mocking
import importlib.util

spec = importlib.util.spec_from_file_location('llm_providers', 'src/agents/llm_providers.py')
llm_providers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm_providers)

# Mock httpx for demo
from unittest.mock import patch

import httpx


async def mock_async_post(*args, **kwargs):
    """Mock async HTTP POST with simulated latency."""
    await asyncio.sleep(0.5)  # Simulate 500ms API latency

    # Create a simple object that has status_code and json() method
    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "response": "This is a simulated response from the LLM.",
                "model": "llama3.2:3b",
                "done": True,
                "prompt_eval_count": 15,
                "eval_count": 25,
            }

    return MockResponse()


async def demo_sequential_execution():
    """Demo 1: Sequential async calls (baseline)."""
    print("\n" + "="*60)
    print("Demo 1: Sequential Async Execution (Baseline)")
    print("="*60)

    with patch.object(httpx.AsyncClient, 'post', new=mock_async_post):
        llm = llm_providers.OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            timeout=30
        )

        prompts = [
            "What is machine learning?",
            "Explain neural networks.",
            "What is reinforcement learning?"
        ]

        print(f"\nExecuting {len(prompts)} prompts sequentially...")
        start_time = time.time()

        responses = []
        for i, prompt in enumerate(prompts, 1):
            print(f"  {i}. Calling LLM for: '{prompt[:40]}...'")
            response = await llm.acomplete(prompt)
            responses.append(response)
            print(f"     ✓ Got response ({response.total_tokens} tokens)")

        elapsed = time.time() - start_time

        print(f"\n{'─'*60}")
        print(f"Sequential execution time: {elapsed:.2f}s")
        print(f"Average per request: {elapsed/len(prompts):.2f}s")
        print(f"{'─'*60}")

        await llm.aclose()

        return elapsed


async def demo_parallel_execution():
    """Demo 2: Parallel async calls (2-3x speedup)."""
    print("\n" + "="*60)
    print("Demo 2: Parallel Async Execution (Target: 2-3x speedup)")
    print("="*60)

    with patch.object(httpx.AsyncClient, 'post', new=mock_async_post):
        llm = llm_providers.OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            timeout=30
        )

        prompts = [
            "What is machine learning?",
            "Explain neural networks.",
            "What is reinforcement learning?"
        ]

        print(f"\nExecuting {len(prompts)} prompts in parallel...")
        start_time = time.time()

        # Create tasks
        tasks = []
        for i, prompt in enumerate(prompts, 1):
            print(f"  {i}. Scheduling: '{prompt[:40]}...'")
            tasks.append(llm.acomplete(prompt))

        print("\n  ⚡ Running all tasks in parallel with asyncio.gather()...")

        # Execute in parallel
        responses = await asyncio.gather(*tasks)

        elapsed = time.time() - start_time

        print(f"\n  ✓ All {len(responses)} responses received!")
        for i, response in enumerate(responses, 1):
            print(f"    {i}. Response {i}: {response.total_tokens} tokens")

        print(f"\n{'─'*60}")
        print(f"Parallel execution time: {elapsed:.2f}s")
        print(f"Average per request: {elapsed/len(prompts):.2f}s")
        print(f"{'─'*60}")

        await llm.aclose()

        return elapsed


async def demo_async_context_manager():
    """Demo 3: Async context manager usage."""
    print("\n" + "="*60)
    print("Demo 3: Async Context Manager")
    print("="*60)

    with patch.object(httpx.AsyncClient, 'post', new=mock_async_post):
        async with llm_providers.OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            timeout=30
        ) as llm:
            print("\n  ✓ LLM client opened with async context manager")

            response = await llm.acomplete("Test prompt")

            print(f"  ✓ Got response: {response.total_tokens} tokens")
            print("  ✓ Client will auto-close on context exit")

        print("  ✓ Context exited - client closed automatically\n")


async def main():
    """Run all demos."""
    print("\n" + "█"*60)
    print("█  ASYNC LLM PROVIDER DEMO")
    print("█  Target: 2-3x speedup with parallel execution")
    print("█"*60)

    # Demo 3: Context manager
    await demo_async_context_manager()

    # Demo 1: Sequential
    sequential_time = await demo_sequential_execution()

    # Demo 2: Parallel
    parallel_time = await demo_parallel_execution()

    # Calculate speedup
    speedup = sequential_time / parallel_time

    print("\n" + "█"*60)
    print("█  RESULTS")
    print("█"*60)
    print(f"\n  Sequential time: {sequential_time:.2f}s")
    print(f"  Parallel time:   {parallel_time:.2f}s")
    print(f"  Speedup:         {speedup:.2f}x")
    print()

    if speedup >= 2.0:
        print("  ✓ SUCCESS: Achieved 2x+ speedup with async execution!")
    else:
        print(f"  ⚠ Note: Speedup of {speedup:.2f}x (target: 2-3x)")

    print("\n" + "█"*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
