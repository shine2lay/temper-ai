"""Shared mock helpers for testing."""
from unittest.mock import Mock, AsyncMock, patch
import pytest


@pytest.fixture
def mock_llm():
    """Mock LLM provider for agent tests."""
    from src.agents.llm.base import BaseLLM
    llm = Mock(spec=BaseLLM)
    llm.generate.return_value = {"text": "Mock response", "tokens": 10}
    return llm


@pytest.fixture
def mock_httpx_client():
    """Mock httpx client for OAuth tests."""
    import httpx
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def mock_subprocess():
    """Mock subprocess for scanner tool tests."""
    import subprocess
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Mock output",
            stderr=""
        )
        yield mock_run
