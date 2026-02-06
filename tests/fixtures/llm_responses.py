"""Realistic LLM response fixtures and test doubles.

Pre-recorded responses from real LLM providers to use in integration tests.
These test doubles return realistic response structures, timing, and errors.

This replaces over-mocking in integration tests with realistic fixtures that:
- Return proper LLMResponse objects with all fields populated
- Include realistic token counts, latency, and metadata
- Support error scenarios with appropriate exception types
- Can simulate retry scenarios for testing error handling
"""

from typing import Optional

from src.agents.llm_providers import LLMResponse
from src.utils.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)

# ============================================================================
# PRE-RECORDED SUCCESSFUL RESPONSES
# ============================================================================

RECORDED_RESPONSES = {
    "ollama_simple_completion": {
        "content": "<answer>Python is a high-level, interpreted programming language known for readability.</answer>",
        "model": "llama3.2:3b",
        "provider": "ollama",
        "prompt_tokens": 45,
        "completion_tokens": 28,
        "total_tokens": 73,
        "latency_ms": 1250,
        "finish_reason": "stop",
        "raw_response": {
            "model": "llama3.2:3b",
            "created_at": "2026-02-01T10:30:00Z",
            "response": "Python is a high-level, interpreted programming language known for readability.",
            "done": True
        }
    },

    "ollama_tool_call_response": {
        "content": '<tool_call>{"name": "calculator", "parameters": {"expression": "2+3"}}</tool_call>',
        "model": "llama3.2:3b",
        "provider": "ollama",
        "prompt_tokens": 120,
        "completion_tokens": 35,
        "total_tokens": 155,
        "latency_ms": 980,
        "finish_reason": "stop",
        "raw_response": {
            "model": "llama3.2:3b",
            "created_at": "2026-02-01T10:30:00Z",
            "response": '{"name": "calculator", "parameters": {"expression": "2+3"}}',
            "done": True
        }
    },

    "ollama_multi_turn_research": {
        "content": "<answer>Research findings: AI advances rapidly with 15 peer-reviewed studies showing 34% improvement. Key themes: safety, scalability, regulation. Confidence: 0.87</answer>",
        "model": "llama2",
        "provider": "ollama",
        "prompt_tokens": 450,
        "completion_tokens": 180,
        "total_tokens": 630,
        "latency_ms": 3200,
        "finish_reason": "stop",
        "raw_response": {
            "model": "llama2",
            "created_at": "2026-02-01T10:30:00Z",
            "response": "Research findings: AI advances rapidly...",
            "done": True
        }
    },

    "openai_gpt4_completion": {
        "content": "Python typing helps catch bugs early through static analysis and improves code maintainability by documenting expected types.",
        "model": "gpt-4-turbo",
        "provider": "openai",
        "prompt_tokens": 50,
        "completion_tokens": 32,
        "total_tokens": 82,
        "latency_ms": 850,
        "finish_reason": "stop",
        "raw_response": {
            "id": "chatcmpl-abc123",
            "object": "chat.completion",
            "created": 1706774400,
            "model": "gpt-4-turbo",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Python typing helps catch bugs early through static analysis and improves code maintainability by documenting expected types."
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 32,
                "total_tokens": 82
            }
        }
    },

    "ollama_synthesis_response": {
        "content": "<answer>Based on the research: Python's type system provides static analysis for early bug detection, improving code quality and maintainability.</answer>",
        "model": "llama3.2:3b",
        "provider": "ollama",
        "prompt_tokens": 200,
        "completion_tokens": 60,
        "total_tokens": 260,
        "latency_ms": 1500,
        "finish_reason": "stop",
        "raw_response": {
            "model": "llama3.2:3b",
            "created_at": "2026-02-01T10:30:00Z",
            "response": "Based on the research: Python's type system provides static analysis...",
            "done": True
        }
    },

    "ollama_writing_response": {
        "content": "<answer>Technical Report:\n\nPython Type System Analysis\n\n1. Introduction\nPython's gradual type system offers static analysis capabilities.\n\n2. Benefits\n- Early bug detection\n- Improved maintainability\n- Better IDE support\n\n3. Conclusion\nType hints provide significant value for large codebases.</answer>",
        "model": "llama3.2:3b",
        "provider": "ollama",
        "prompt_tokens": 300,
        "completion_tokens": 150,
        "total_tokens": 450,
        "latency_ms": 2200,
        "finish_reason": "stop",
        "raw_response": {
            "model": "llama3.2:3b",
            "created_at": "2026-02-01T10:30:00Z",
            "response": "Technical Report:\n\nPython Type System Analysis...",
            "done": True
        }
    },

    "anthropic_claude_completion": {
        "content": "Python's type system, introduced in PEP 484, provides optional static type hints that enable tools like mypy to catch type errors before runtime, significantly improving code reliability.",
        "model": "claude-3-sonnet-20240229",
        "provider": "anthropic",
        "prompt_tokens": 55,
        "completion_tokens": 38,
        "total_tokens": 93,
        "latency_ms": 920,
        "finish_reason": "end_turn",
        "raw_response": {
            "id": "msg_abc123",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "Python's type system, introduced in PEP 484..."
                }
            ],
            "model": "claude-3-sonnet-20240229",
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 55,
                "output_tokens": 38
            }
        }
    }
}


# ============================================================================
# PRE-RECORDED ERROR RESPONSES
# ============================================================================

RECORDED_ERRORS = {
    "rate_limit_error": {
        "error_type": "rate_limit",
        "message": "Rate limit exceeded. Please retry after 15 seconds.",
        "status_code": 429,
        "retry_after": 15,
        "provider": "openai",
        "raw_error": {
            "error": {
                "message": "Rate limit exceeded",
                "type": "rate_limit_error",
                "code": "rate_limit_exceeded"
            }
        }
    },

    "timeout_error": {
        "error_type": "timeout",
        "message": "Request timed out after 30000ms",
        "status_code": 504,
        "provider": "ollama",
        "timeout_ms": 30000
    },

    "authentication_error": {
        "error_type": "authentication",
        "message": "Invalid API key provided",
        "status_code": 401,
        "provider": "openai",
        "raw_error": {
            "error": {
                "message": "Incorrect API key provided",
                "type": "invalid_request_error",
                "code": "invalid_api_key"
            }
        }
    },

    "model_not_found": {
        "error_type": "not_found",
        "message": "Model 'llama-nonexistent' not found",
        "status_code": 404,
        "provider": "ollama"
    },

    "context_length_exceeded": {
        "error_type": "invalid_request",
        "message": "Context length exceeded. Maximum tokens: 4096, requested: 5000",
        "status_code": 400,
        "provider": "openai",
        "raw_error": {
            "error": {
                "message": "This model's maximum context length is 4096 tokens",
                "type": "invalid_request_error",
                "code": "context_length_exceeded"
            }
        }
    }
}


# ============================================================================
# TEST DOUBLE: Realistic LLM Provider
# ============================================================================

class RealisticLLMTestDouble:
    """Test double that returns pre-recorded LLM responses.

    This replaces Mock() in integration tests with realistic response behavior:
    - Returns properly structured LLMResponse objects
    - Includes realistic token counts, latency, metadata
    - Supports error scenarios with proper exception types
    - Can simulate retry scenarios

    Example:
        >>> llm = RealisticLLMTestDouble(scenario="ollama_simple_completion")
        >>> response = llm.complete("What is Python?")
        >>> assert isinstance(response, LLMResponse)
        >>> assert response.total_tokens == 73
        >>> assert response.latency_ms == 1250
    """

    def __init__(
        self,
        scenario: str = "ollama_simple_completion",
        error_scenario: Optional[str] = None,
        fail_on_attempt: Optional[int] = None
    ):
        """Initialize test double.

        Args:
            scenario: Response scenario key from RECORDED_RESPONSES
            error_scenario: Optional error scenario from RECORDED_ERRORS
            fail_on_attempt: Optional attempt number to fail on (for retry testing)
        """
        self.scenario = scenario
        self.error_scenario = error_scenario
        self.fail_on_attempt = fail_on_attempt
        self.attempt_count = 0

    def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """Complete with pre-recorded response.

        Args:
            prompt: Input prompt (logged but not used)
            **kwargs: Additional parameters (ignored in test double)

        Returns:
            LLMResponse with realistic data

        Raises:
            LLMRateLimitError: If error_scenario="rate_limit_error"
            LLMTimeoutError: If error_scenario="timeout_error"
            LLMAuthenticationError: If error_scenario="authentication_error"
            LLMError: For other error scenarios
        """
        self.attempt_count += 1

        # Simulate retry scenario (fail on specific attempt)
        if self.fail_on_attempt and self.attempt_count == self.fail_on_attempt:
            if self.error_scenario:
                self._raise_error(self.error_scenario)

        # Return error if error_scenario set and no retry logic
        if self.error_scenario and not self.fail_on_attempt:
            self._raise_error(self.error_scenario)

        # Return successful response
        response_data = RECORDED_RESPONSES[self.scenario]
        return LLMResponse(**response_data)

    def _raise_error(self, error_scenario: str):
        """Raise appropriate error for scenario."""
        error_data = RECORDED_ERRORS[error_scenario]

        if error_data["error_type"] == "rate_limit":
            raise LLMRateLimitError(
                error_data["message"],
                retry_after=error_data.get("retry_after")
            )
        elif error_data["error_type"] == "timeout":
            raise LLMTimeoutError(error_data["message"])
        elif error_data["error_type"] == "authentication":
            raise LLMAuthenticationError(error_data["message"])
        else:
            raise LLMError(error_data["message"])


# ============================================================================
# SCENARIO BUILDER HELPERS
# ============================================================================

def create_llm_test_double(
    scenario_type: str = "simple",
    provider: str = "ollama",
    should_fail: bool = False,
    error_type: Optional[str] = None
) -> RealisticLLMTestDouble:
    """Create LLM test double for common scenarios.

    Args:
        scenario_type: One of "simple", "tool_call", "research", "synthesis", "writing"
        provider: "ollama", "openai", or "anthropic"
        should_fail: Whether to simulate failure
        error_type: Type of error if should_fail=True
                   Options: "rate_limit", "timeout", "authentication", "not_found"

    Returns:
        Configured RealisticLLMTestDouble

    Example:
        >>> # Success scenario
        >>> llm = create_llm_test_double("simple", "ollama")
        >>> response = llm.complete("test prompt")
        >>> assert response.content
        >>>
        >>> # Error scenario
        >>> llm = create_llm_test_double("simple", "openai", should_fail=True, error_type="rate_limit")
        >>> try:
        ...     llm.complete("test")
        ... except LLMRateLimitError as e:
        ...     assert "Rate limit exceeded" in str(e)
    """
    scenario_map = {
        ("simple", "ollama"): "ollama_simple_completion",
        ("tool_call", "ollama"): "ollama_tool_call_response",
        ("research", "ollama"): "ollama_multi_turn_research",
        ("synthesis", "ollama"): "ollama_synthesis_response",
        ("writing", "ollama"): "ollama_writing_response",
        ("simple", "openai"): "openai_gpt4_completion",
        ("simple", "anthropic"): "anthropic_claude_completion",
    }

    scenario = scenario_map.get((scenario_type, provider), "ollama_simple_completion")

    error_scenario = None
    if should_fail:
        error_scenario = f"{error_type}_error" if error_type else "timeout_error"

    return RealisticLLMTestDouble(scenario=scenario, error_scenario=error_scenario)


def create_mock_llm_with_response(response_content: str, tokens: int = 100) -> RealisticLLMTestDouble:
    """Create a simple mock LLM with custom response content.

    Useful for quick tests where you need custom response text but still want
    realistic response structure.

    Args:
        response_content: Custom content to return
        tokens: Total token count (default: 100)

    Returns:
        Test double configured with custom response

    Example:
        >>> llm = create_mock_llm_with_response("<answer>Custom test response</answer>")
        >>> response = llm.complete("any prompt")
        >>> assert response.content == "<answer>Custom test response</answer>"
    """
    # Create custom scenario
    custom_scenario = f"custom_{id(response_content)}"
    RECORDED_RESPONSES[custom_scenario] = {
        "content": response_content,
        "model": "llama3.2:3b",
        "provider": "ollama",
        "prompt_tokens": int(tokens * 0.6),
        "completion_tokens": int(tokens * 0.4),
        "total_tokens": tokens,
        "latency_ms": 1000,
        "finish_reason": "stop",
        "raw_response": {}
    }

    return RealisticLLMTestDouble(scenario=custom_scenario)
