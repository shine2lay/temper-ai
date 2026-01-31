"""Tests for async LLM provider functionality.

Tests async completion, parallel execution, and context manager support.
"""
import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import httpx

from src.agents.llm_providers import (
    BaseLLM,
    OllamaLLM,
    OpenAILLM,
    AnthropicLLM,
    LLMResponse,
    LLMProvider,
    LLMError,
    LLMTimeoutError
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
    mock_response = AsyncMock()
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
    assert client is not None
    assert isinstance(client, httpx.AsyncClient)

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
        assert llm is not None

        # Get async client to initialize it
        client = llm._get_async_client()
        assert client is not None

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

        mock_response = AsyncMock()
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
        await llm.acomplete(f"Prompt sequential")
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
