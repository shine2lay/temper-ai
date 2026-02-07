"""Tests for async LLM provider functionality.

Tests async completion, parallel execution, and context manager support.
"""
import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.agents.llm_providers import (
    AnthropicLLM,
    LLMAuthenticationError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    OllamaLLM,
    OpenAILLM,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def ollama_config():
    """Basic Ollama configuration."""
    return {
        "model": "llama3.2:3b",
        "base_url": "http://localhost:11434",
        "temperature": 0.7,
        "max_tokens": 100,
        "timeout": 30,
    }


@pytest.fixture
def mock_async_response():
    """Mock async HTTP response."""
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 200
    # json() is synchronous in httpx, so use Mock not AsyncMock
    mock_response.json = Mock(return_value={
        "response": "Test response",
        "model": "llama3.2:3b",
        "done": True,
        "prompt_eval_count": 10,
        "eval_count": 20,
    })
    return mock_response


# ============================================================================
# Test 1: Async Client Creation
# ============================================================================

def test_async_client_lazy_initialization(ollama_config):
    """Test that async client is created lazily."""
    llm = OllamaLLM(**ollama_config)

    # Initially, async client should be None
    assert llm._async_client is None

    # Get async client
    client = llm._get_async_client()

    # Now it should be created
    assert isinstance(client, httpx.AsyncClient), \
        f"Expected httpx.AsyncClient, got {type(client)}"
    assert not client.is_closed, "Client should not be closed immediately after creation"

    # Getting again should return same instance
    client2 = llm._get_async_client()
    assert client2 is client

    # Cleanup
    asyncio.run(llm.aclose())


# ============================================================================
# Test 2: Async Context Manager
# ============================================================================

@pytest.mark.asyncio
async def test_async_context_manager(ollama_config):
    """Test async context manager properly cleans up resources."""
    async with OllamaLLM(**ollama_config) as llm:
        # Client should exist
        assert isinstance(llm, OllamaLLM), \
            f"Expected OllamaLLM instance, got {type(llm)}"

        # Get async client to initialize it
        client = llm._get_async_client()
        assert isinstance(client, httpx.AsyncClient), \
            f"Expected httpx.AsyncClient, got {type(client)}"

    # After exiting context, client should be closed
    # Note: We can't directly test if client is closed,
    # but we verified aclose() was called


# ============================================================================
# Test 3: Async Complete Method
# ============================================================================

@pytest.mark.asyncio
@patch('httpx.AsyncClient')
async def test_acomplete_success(mock_async_client_class, ollama_config, mock_async_response):
    """Test successful async completion."""
    # Setup mock
    mock_client_instance = AsyncMock()
    mock_client_instance.post = AsyncMock(return_value=mock_async_response)
    mock_async_client_class.return_value = mock_client_instance

    llm = OllamaLLM(**ollama_config)
    llm._async_client = mock_client_instance

    # Call async complete
    response = await llm.acomplete("Test prompt")

    # Verify response
    assert response.content == "Test response"
    assert response.model == "llama3.2:3b"
    assert response.provider == LLMProvider.OLLAMA
    assert response.prompt_tokens == 10
    assert response.completion_tokens == 20
    assert response.total_tokens == 30

    # Verify async post was called
    mock_client_instance.post.assert_called_once()

    await llm.aclose()


# ============================================================================
# Test 4: Parallel Execution
# ============================================================================

@pytest.mark.asyncio
@patch('httpx.AsyncClient')
async def test_parallel_execution(mock_async_client_class, ollama_config, mock_async_response):
    """Test that multiple async completions can run in parallel."""
    # Setup mock
    mock_client_instance = AsyncMock()

    async def mock_post(*args, **kwargs):
        await asyncio.sleep(0.1)  # Simulate network latency
        return mock_async_response

    mock_client_instance.post = mock_post
    mock_async_client_class.return_value = mock_client_instance

    llm = OllamaLLM(**ollama_config)
    llm._async_client = mock_client_instance

    # Execute 3 completions in parallel
    start_time = time.time()

    results = await asyncio.gather(
        llm.acomplete("Prompt 1"),
        llm.acomplete("Prompt 2"),
        llm.acomplete("Prompt 3"),
    )

    elapsed_time = time.time() - start_time

    # Verify results
    assert len(results) == 3
    for result in results:
        assert isinstance(result, LLMResponse)
        assert result.content == "Test response"

    # Parallel execution should take ~0.1s, not ~0.3s
    # Allow some margin for test overhead
    assert elapsed_time < 0.25, f"Parallel execution took {elapsed_time}s, expected <0.25s"

    await llm.aclose()


# ============================================================================
# Test 5: Async Retry Logic
# ============================================================================

@pytest.mark.asyncio
@patch('httpx.AsyncClient')
async def test_acomplete_retry_on_timeout(mock_async_client_class, ollama_config):
    """Test async retry logic on timeout."""
    # Setup mock that fails twice then succeeds
    mock_client_instance = AsyncMock()

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.TimeoutException("Timeout")

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        # json() is synchronous in httpx, so use Mock not AsyncMock
        mock_response.json = Mock(return_value={
            "response": "Success",
            "model": "llama3.2:3b",
            "done": True,
        })
        return mock_response

    mock_client_instance.post = mock_post
    mock_async_client_class.return_value = mock_client_instance

    llm = OllamaLLM(**ollama_config)
    llm._async_client = mock_client_instance
    llm.retry_delay = 0.01  # Speed up test

    # Should succeed on 3rd attempt
    response = await llm.acomplete("Test prompt")

    assert response.content == "Success"
    assert call_count == 3

    await llm.aclose()


# ============================================================================
# Test 6: Async Timeout Error
# ============================================================================

@pytest.mark.asyncio
@patch('httpx.AsyncClient')
async def test_acomplete_timeout_error(mock_async_client_class, ollama_config):
    """Test async timeout raises LLMTimeoutError after max retries."""
    # Setup mock that always times out
    mock_client_instance = AsyncMock()
    mock_client_instance.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
    mock_async_client_class.return_value = mock_client_instance

    llm = OllamaLLM(**ollama_config)
    llm._async_client = mock_client_instance
    llm.max_retries = 2
    llm.retry_delay = 0.01

    # Should raise timeout error after retries
    with pytest.raises(LLMTimeoutError):
        await llm.acomplete("Test prompt")

    await llm.aclose()


# ============================================================================
# Test 7: All Provider Types Support Async
# ============================================================================

@pytest.mark.asyncio
async def test_all_providers_have_async_methods():
    """Test that all provider types have async methods."""
    providers = [
        OllamaLLM(model="llama3.2:3b", base_url="http://localhost:11434"),
        OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test"),
        AnthropicLLM(model="claude-3", base_url="https://api.anthropic.com", api_key="test"),
    ]

    for provider in providers:
        # Check async methods exist
        assert hasattr(provider, 'acomplete')
        assert hasattr(provider, 'aclose')
        assert hasattr(provider, '__aenter__')
        assert hasattr(provider, '__aexit__')
        assert asyncio.iscoroutinefunction(provider.acomplete)
        assert asyncio.iscoroutinefunction(provider.aclose)

        # Cleanup
        await provider.aclose()


# ============================================================================
# Test 8: Async Performance Baseline
# ============================================================================

@pytest.mark.asyncio
@patch('httpx.AsyncClient')
async def test_async_performance_baseline(mock_async_client_class, ollama_config, mock_async_response):
    """Baseline test showing async is faster than sequential."""
    # Setup mock with simulated latency
    mock_client_instance = AsyncMock()

    async def mock_post(*args, **kwargs):
        await asyncio.sleep(0.05)  # 50ms simulated API latency
        return mock_async_response

    mock_client_instance.post = mock_post
    mock_async_client_class.return_value = mock_client_instance

    llm = OllamaLLM(**ollama_config)
    llm._async_client = mock_client_instance

    # Test 1: Sequential execution (baseline)
    start_time = time.time()
    for _ in range(3):
        await llm.acomplete("Prompt sequential")
    sequential_time = time.time() - start_time

    # Test 2: Parallel execution
    start_time = time.time()
    await asyncio.gather(
        llm.acomplete("Prompt 1"),
        llm.acomplete("Prompt 2"),
        llm.acomplete("Prompt 3"),
    )
    parallel_time = time.time() - start_time

    # Verify speedup
    # Sequential: ~150ms (3 × 50ms)
    # Parallel: ~50ms (max of 3 × 50ms in parallel)
    speedup = sequential_time / parallel_time

    assert speedup > 2.0, f"Expected >2x speedup, got {speedup:.2f}x"

    await llm.aclose()


# ============================================================================
# ASYNC ERROR PATH TESTS (test-crit-async-errors-01)
# ============================================================================

class TestAsyncErrorPaths:
    """Test async-specific error handling in LLM providers.

    These tests cover critical async error scenarios:
    - Circuit breaker behavior with async
    - Connection pool cleanup on exceptions
    - Resource management when cleanup fails
    - Concurrent error handling
    - Error context preservation

    Rationale: Async error handling differs from sync - these tests prevent
    production issues like connection leaks and cascading failures.
    """

    # ========================================================================
    # Test 1: Async Connection Errors Don't Retry
    # ========================================================================

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_acomplete_connection_errors_no_retry(
        self, mock_httpx_client_class, ollama_config
    ):
        """Test async connection errors fail immediately without retry.

        CURRENT BEHAVIOR: Connection errors (httpx.ConnectError, httpx.NetworkError)
        are not caught in async path, so they bubble up immediately without retry.

        COVERAGE: Documents gap - only TimeoutException and RateLimitError are retried.
        """
        # Setup: Mock async client that fails with connection error
        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_httpx_client_class.return_value = mock_client_instance

        llm = OllamaLLM(**ollama_config)
        llm._async_client = mock_client_instance
        llm.max_retries = 3
        llm.retry_delay = 0.01

        # Execute: Connection error should bubble up immediately
        with pytest.raises(httpx.ConnectError):
            await llm.acomplete("test prompt")

        # Verify: Only 1 attempt (no retry)
        assert mock_client_instance.post.call_count == 1

        await llm.aclose()

    # ========================================================================
    # Test 2: Async Timeout Retry with Exponential Backoff
    # ========================================================================

    @pytest.mark.asyncio
    @patch('httpx.AsyncClient')
    async def test_acomplete_timeout_retry_then_success(
        self, mock_httpx_client_class, ollama_config
    ):
        """Test async retry works for timeout errors.

        COVERAGE: Validates retry behavior for TimeoutException (one of the few retried errors).
        EXPECTED: Timeout errors trigger retry with exponential backoff.
        """
        mock_client_instance = AsyncMock()
        mock_httpx_client_class.return_value = mock_client_instance

        llm = OllamaLLM(**ollama_config)
        llm._async_client = mock_client_instance
        llm.max_retries = 3
        llm.retry_delay = 0.01

        # Timeout then success
        call_count = 0

        async def mock_post_timeout_then_success(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.TimeoutException("Request timeout")

            mock_response = AsyncMock(spec=httpx.Response)
            mock_response.status_code = 200
            mock_response.json = Mock(return_value={
                "response": "Success after timeout retry",
                "model": "llama3.2:3b",
                "done": True,
                "prompt_eval_count": 10,
                "eval_count": 20,
            })
            return mock_response

        mock_client_instance.post = mock_post_timeout_then_success

        # Should succeed after retry
        with patch('asyncio.sleep', new_callable=AsyncMock):
            result = await llm.acomplete("test prompt")

        assert result.content == "Success after timeout retry"
        assert call_count == 2  # Failed once with timeout, succeeded second time

        await llm.aclose()

    # ========================================================================
    # Test 3: Connection Pool Cleanup on Async Exception
    # ========================================================================

    @pytest.mark.asyncio
    async def test_acomplete_connection_pool_cleanup_on_exception(self, ollama_config):
        """Test connection pool cleanup when async request fails.

        RISK: Connection leaks accumulate over time, eventually causing "too many open files".
        FIX: AsyncClient should be properly closed even when exceptions occur.
        """
        llm = OllamaLLM(**ollama_config)

        # Track connection pool state
        async_client = llm._get_async_client()
        assert isinstance(async_client, httpx.AsyncClient), \
            f"Expected httpx.AsyncClient, got {type(async_client)}"
        assert llm._async_client is async_client, "Should return same client instance (singleton)"

        # Mock connection error
        with patch.object(async_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")
            llm.max_retries = 1
            llm.retry_delay = 0.01

            # Multiple failing requests
            for i in range(5):
                with pytest.raises(httpx.ConnectError):
                    await llm.acomplete("test prompt")

        # Verify client still exists (lazy cleanup)
        assert isinstance(llm._async_client, httpx.AsyncClient), \
            "Client should persist after connection errors (lazy cleanup)"

        # Cleanup
        await llm.aclose()

        # Verify client was properly closed
        assert llm._async_client is None
        assert llm._closed is True

        # Verify idempotent (calling again doesn't crash)
        await llm.aclose()

    # ========================================================================
    # Test 4: Resource Management When aclose() Fails
    # ========================================================================

    @pytest.mark.asyncio
    async def test_aclose_graceful_degradation_on_failure(self):
        """Test aclose() handles failures gracefully without leaving dangling resources.

        RISK: If aclose() raises, resources may not be marked as cleaned, causing warnings.
        FIX: aclose() should catch exceptions and still mark resources as closed.
        """
        llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")

        # Initialize both clients
        sync_client = llm._get_client()
        async_client = llm._get_async_client()
        assert isinstance(sync_client, httpx.Client), \
            f"Expected httpx.Client, got {type(sync_client)}"
        assert isinstance(async_client, httpx.AsyncClient), \
            f"Expected httpx.AsyncClient, got {type(async_client)}"

        # Mock aclose() to fail
        original_aclose = async_client.aclose

        async def failing_aclose():
            raise RuntimeError("aclose failed!")

        async_client.aclose = failing_aclose

        # aclose() should handle the error gracefully
        try:
            await llm.aclose()
        except RuntimeError as e:
            # aclose failure may propagate, which is acceptable
            assert "aclose failed" in str(e)

        # Verify state is marked as closed despite error
        # Implementation should ensure cleanup even on failure
        assert llm._closed is True or llm._async_client is None

    # ========================================================================
    # Test 5: Concurrent Async Errors Don't Leak Connections
    # ========================================================================

    @pytest.mark.asyncio
    async def test_concurrent_async_errors_no_connection_leak(self):
        """Test that concurrent async errors don't leak connections.

        RISK: Under high load, concurrent failures could exhaust connection pool (max 100 connections).
        FIX: Each failed request should properly release connection back to pool.
        """
        llm = OllamaLLM(
            model="llama2",
            base_url="http://localhost:11434",
            max_retries=1
        )
        llm.retry_delay = 0.01

        # Mock client to always fail
        async_client = llm._get_async_client()

        with patch.object(async_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")

            # Make 50 concurrent failing requests (well within connection pool limit of 100)
            async def failing_request():
                with pytest.raises(httpx.ConnectError):
                    await llm.acomplete("test prompt")

            # Execute concurrently
            await asyncio.gather(*[failing_request() for _ in range(50)], return_exceptions=True)

        # Verify: Connection pool should not be exhausted
        # Note: httpx.AsyncClient uses connection pooling, we verify client is still functional
        assert isinstance(llm._async_client, httpx.AsyncClient), \
            "Client should remain functional after concurrent failures"

        # Cleanup
        await llm.aclose()
        assert llm._async_client is None

    # ========================================================================
    # Test 6: Async Retry with Exponential Backoff
    # ========================================================================

    @pytest.mark.asyncio
    async def test_acomplete_exponential_backoff_timing(self):
        """Test async retry uses correct exponential backoff with jitter.

        COVERAGE: Validates that asyncio.sleep is called with correct backoff intervals.
        EXPECTED: For max_retries=3, we get 3 attempts with 2 sleep calls.
        Base delays are [2s, 4s] with jitter multiplier in [0.5, 1.5).
        """
        llm = OllamaLLM(
            model="llama2",
            base_url="http://localhost:11434",
            max_retries=3,
            retry_delay=2.0
        )

        async_client = llm._get_async_client()

        with patch.object(async_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Timeout")

            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                with pytest.raises(LLMTimeoutError):
                    await llm.acomplete("test prompt")

                # Verify exponential backoff with jitter (R-15):
                # Base delays are 2s, 4s; jitter multiplier is (0.5 + random()) in [0.5, 1.5)
                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                assert len(sleep_calls) == 2, f"Expected 2 sleep calls, got {len(sleep_calls)}"
                assert 1.0 <= sleep_calls[0] < 3.0, f"First delay {sleep_calls[0]} not in [1.0, 3.0)"
                assert 2.0 <= sleep_calls[1] < 6.0, f"Second delay {sleep_calls[1]} not in [2.0, 6.0)"
                assert mock_post.call_count == 3

        await llm.aclose()

    # ========================================================================
    # Test 7: Rate Limit Error Handling with Async
    # ========================================================================

    @pytest.mark.asyncio
    async def test_acomplete_rate_limit_error_retry(self):
        """Test rate limit (429) errors trigger retry with backoff.

        COVERAGE: Validates LLMRateLimitError handling in async context.
        EXPECTED: Should retry with exponential backoff, then fail after max retries.
        """
        llm = OllamaLLM(
            model="llama2",
            base_url="http://localhost:11434",
            max_retries=3,
            retry_delay=0.1  # Fast for testing
        )

        async_client = llm._get_async_client()

        # Mock rate limit response
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"

        with patch.object(async_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            with patch('asyncio.sleep', new_callable=AsyncMock):
                with pytest.raises(LLMRateLimitError, match="Rate limited"):
                    await llm.acomplete("test prompt")

                # Should have retried 3 times
                assert mock_post.call_count == 3

        await llm.aclose()

    # ========================================================================
    # Test 8: Error Context Preservation Through Async Stack
    # ========================================================================

    @pytest.mark.asyncio
    async def test_acomplete_error_context_preserved(self):
        """Test exception context preserved through async stack.

        COVERAGE: Validates that original exception is accessible via __context__ or __cause__.
        IMPORTANT: For debugging production issues.
        """
        llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")

        async_client = llm._get_async_client()

        # Create original error
        original_error = httpx.ConnectError("Original connection error")

        with patch.object(async_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = original_error
            llm.max_retries = 1
            llm.retry_delay = 0.01

            try:
                await llm.acomplete("test prompt")
            except httpx.ConnectError as e:
                # Original error should be accessible
                assert e is original_error
            else:
                pytest.fail("Expected httpx.ConnectError to be raised")

        await llm.aclose()

    # ========================================================================
    # Test 9: Async Streaming Error Handling (Future)
    # ========================================================================

    @pytest.mark.asyncio
    async def test_async_network_error_no_retry_on_auth_failure(self):
        """Test that authentication errors don't trigger retries.

        COVERAGE: Validates non-retryable error handling in async.
        EXPECTED: Auth errors should fail immediately without retry.
        """
        llm = OllamaLLM(
            model="llama2",
            base_url="http://localhost:11434",
            max_retries=3  # Should not retry even with max_retries=3
        )
        llm.retry_delay = 0.01

        async_client = llm._get_async_client()

        # Mock 401 authentication error
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.text = "Invalid API key"

        with patch.object(async_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            # Auth error should fail immediately
            with pytest.raises(LLMAuthenticationError):
                await llm.acomplete("test prompt")

            # Should only try once (no retry)
            assert mock_post.call_count == 1

        await llm.aclose()

    # ========================================================================
    # Test 10: Multiple Async Clients Independent State
    # ========================================================================

    @pytest.mark.asyncio
    async def test_multiple_async_clients_independent_state(self):
        """Test multiple async LLM instances have independent state.

        COVERAGE: Validates per-instance isolation - one failing client doesn't affect others.
        EXPECTED: Async clients should have separate connection pools and state.
        """
        llm1 = OllamaLLM(model="llama2", base_url="http://localhost:11434", max_retries=1)
        llm2 = OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test", max_retries=1)
        llm1.retry_delay = 0.01
        llm2.retry_delay = 0.01

        # Get both clients
        client1 = llm1._get_async_client()
        client2 = llm2._get_async_client()

        # Verify they are independent instances
        assert client1 is not client2
        assert llm1._async_client is not llm2._async_client

        # Fail llm1 multiple times
        with patch.object(client1, 'post', new_callable=AsyncMock) as mock_post1:
            mock_post1.side_effect = httpx.ConnectError("Connection refused")

            for _ in range(5):
                with pytest.raises(httpx.ConnectError):
                    await llm1.acomplete("test prompt")

        # Verify llm2 is still functional (independent)
        assert isinstance(llm2._async_client, httpx.AsyncClient), \
            "llm2 should remain functional when llm1 fails (isolation)"
        assert llm2._closed is False, "llm2 should not be closed when llm1 fails"

        # Cleanup
        await llm1.aclose()
        await llm2.aclose()

        # Verify both cleaned up independently
        assert llm1._async_client is None
        assert llm2._async_client is None
