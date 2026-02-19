"""
Tests for LLM call sanitization in ExecutionTracker.

Ensures that prompts and responses are sanitized before storage to prevent
PII and secret exposure in the observability database.
"""
import pytest

from temper_ai.observability.backends import SQLObservabilityBackend
from temper_ai.observability.database import init_database
from temper_ai.observability.models import LLMCall
from temper_ai.observability.sanitization import SanitizationConfig
from temper_ai.observability.tracker import ExecutionTracker


@pytest.fixture
def sql_backend():
    """Create SQL backend for testing."""
    import temper_ai.observability.database as db_module
    from temper_ai.observability.database import _db_lock

    # Clean up any existing instance
    with _db_lock:
        db_module._db_manager = None

    # Initialize in-memory database
    db_manager = init_database("sqlite:///:memory:")
    backend = SQLObservabilityBackend()
    yield backend

    # Cleanup
    with _db_lock:
        db_module._db_manager = None


@pytest.fixture
def tracker(sql_backend):
    """Create tracker with SQL backend."""
    return ExecutionTracker(backend=sql_backend)


class TestLLMCallSanitization:
    """Test that LLM calls are sanitized before storage."""

    def test_api_key_in_prompt_redacted(self, tracker):
        """Ensure API keys in prompts are redacted before storage."""
        # Track LLM call with API key in prompt
        llm_call_id = tracker.track_llm_call(
            agent_id="agent-123",
            provider="openai",
            model="gpt-4",
            prompt="Use API key sk-proj-abc123def456ghi789 to authenticate",
            response="Authentication successful",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=250,
            estimated_cost_usd=0.001
        )

        # Retrieve from backend
        with tracker.backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Prompt should be sanitized
            assert "sk-proj-abc123def456ghi789" not in llm_call.prompt
            assert "[OPENAI_KEY_REDACTED]" in llm_call.prompt or "[GENERIC_API_KEY_REDACTED]" in llm_call.prompt

            # Response should be unchanged (no secrets)
            assert llm_call.response == "Authentication successful"

    def test_email_in_response_redacted(self, tracker):
        """Ensure emails in responses are redacted before storage."""
        config = SanitizationConfig(enable_pii_detection=True)
        tracker_with_pii = ExecutionTracker(
            backend=tracker.backend,
            sanitization_config=config
        )

        # Track LLM call with email in response
        llm_call_id = tracker_with_pii.track_llm_call(
            agent_id="agent-123",
            provider="openai",
            model="gpt-4",
            prompt="Who is the contact?",
            response="Contact John Doe at john.doe@company.com",
            prompt_tokens=5,
            completion_tokens=10,
            latency_ms=300,
            estimated_cost_usd=0.002
        )

        # Retrieve from backend
        with tracker.backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Email should be redacted
            assert "john.doe@company.com" not in llm_call.response
            assert "[EMAIL_REDACTED]" in llm_call.response

    def test_phone_number_in_response_redacted(self, tracker):
        """Ensure phone numbers in responses are redacted."""
        config = SanitizationConfig(enable_pii_detection=True, redact_phone_numbers=True)
        tracker_with_pii = ExecutionTracker(
            backend=tracker.backend,
            sanitization_config=config
        )

        # Track LLM call with phone number in response
        llm_call_id = tracker_with_pii.track_llm_call(
            agent_id="agent-123",
            provider="openai",
            model="gpt-4",
            prompt="What's the phone number?",
            response="Call 555-123-4567 for support",
            prompt_tokens=5,
            completion_tokens=8,
            latency_ms=200,
            estimated_cost_usd=0.001
        )

        # Retrieve from backend
        with tracker.backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Phone should be redacted
            assert "555-123-4567" not in llm_call.response
            assert "[PHONE_US_REDACTED]" in llm_call.response

    def test_multiple_secrets_all_redacted(self, tracker):
        """Ensure multiple secrets are all redacted."""
        # Track LLM call with multiple secrets
        llm_call_id = tracker.track_llm_call(
            agent_id="agent-123",
            provider="openai",
            model="gpt-4",
            prompt="AWS key: AKIAIOSFODNN7EXAMPLE, API key: sk-proj-abc123def456",
            response="Keys received",
            prompt_tokens=15,
            completion_tokens=3,
            latency_ms=250,
            estimated_cost_usd=0.002
        )

        # Retrieve from backend
        with tracker.backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Both secrets should be redacted
            assert "AKIAIOSFODNN7EXAMPLE" not in llm_call.prompt
            assert "sk-proj-abc123def456" not in llm_call.prompt
            assert "[AWS_ACCESS_KEY_REDACTED]" in llm_call.prompt
            assert "REDACTED" in llm_call.prompt

    def test_large_prompt_truncated(self, tracker):
        """Ensure large prompts are truncated."""
        config = SanitizationConfig(max_prompt_length=100)
        tracker_with_limits = ExecutionTracker(
            backend=tracker.backend,
            sanitization_config=config
        )

        # Create large prompt
        large_prompt = "A" * 1000

        llm_call_id = tracker_with_limits.track_llm_call(
            agent_id="agent-123",
            provider="openai",
            model="gpt-4",
            prompt=large_prompt,
            response="OK",
            prompt_tokens=250,
            completion_tokens=1,
            latency_ms=100,
            estimated_cost_usd=0.001
        )

        # Retrieve from backend
        with tracker.backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Should be truncated
            assert len(llm_call.prompt) <= 120  # 100 + truncation marker
            assert "[TRUNCATED:" in llm_call.prompt

    def test_no_sanitization_when_clean(self, tracker):
        """Ensure clean content passes through without modification."""
        # Track LLM call with no secrets/PII
        prompt = "What is the capital of France?"
        response = "The capital of France is Paris."

        llm_call_id = tracker.track_llm_call(
            agent_id="agent-123",
            provider="openai",
            model="gpt-4",
            prompt=prompt,
            response=response,
            prompt_tokens=8,
            completion_tokens=8,
            latency_ms=150,
            estimated_cost_usd=0.001
        )

        # Retrieve from backend
        with tracker.backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Content should be unchanged
            assert llm_call.prompt == prompt
            assert llm_call.response == response


class TestSanitizationConfiguration:
    """Test sanitization configuration options."""

    def test_pii_detection_disabled(self):
        """Test that PII detection can be disabled."""
        db_manager = init_database("sqlite:///:memory:")
        config = SanitizationConfig(enable_pii_detection=False)
        backend = SQLObservabilityBackend()
        tracker = ExecutionTracker(backend=backend, sanitization_config=config)

        # Track LLM call with email (PII detection disabled)
        llm_call_id = tracker.track_llm_call(
            agent_id="agent-123",
            provider="openai",
            model="gpt-4",
            prompt="Email: john@example.com",
            response="OK",
            prompt_tokens=5,
            completion_tokens=1,
            latency_ms=100,
            estimated_cost_usd=0.001
        )

        # Retrieve from backend
        with backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Email should NOT be redacted (PII detection disabled)
            assert "john@example.com" in llm_call.prompt



    def test_secret_detection_always_enabled(self):
        """Test that secret detection cannot be disabled."""
        db_manager = init_database("sqlite:///:memory:")
        config = SanitizationConfig(
            enable_secret_detection=True,  # Always true by default
            enable_pii_detection=False
        )
        backend = SQLObservabilityBackend()
        tracker = ExecutionTracker(backend=backend, sanitization_config=config)

        # Track LLM call with API key
        llm_call_id = tracker.track_llm_call(
            agent_id="agent-123",
            provider="openai",
            model="gpt-4",
            prompt="Key: sk-proj-abc123def456ghi789",
            response="OK",
            prompt_tokens=8,
            completion_tokens=1,
            latency_ms=100,
            estimated_cost_usd=0.001
        )

        # Retrieve from backend
        with backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Secret should ALWAYS be redacted
            assert "sk-proj-abc123def456ghi789" not in llm_call.prompt
            assert "REDACTED" in llm_call.prompt



    def test_custom_length_limits(self):
        """Test custom length limits."""
        db_manager = init_database("sqlite:///:memory:")
        config = SanitizationConfig(
            max_prompt_length=50,
            max_response_length=50
        )
        backend = SQLObservabilityBackend()
        tracker = ExecutionTracker(backend=backend, sanitization_config=config)

        # Track LLM call with long content
        llm_call_id = tracker.track_llm_call(
            agent_id="agent-123",
            provider="openai",
            model="gpt-4",
            prompt="A" * 100,
            response="B" * 100,
            prompt_tokens=25,
            completion_tokens=25,
            latency_ms=200,
            estimated_cost_usd=0.002
        )

        # Retrieve from backend
        with backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Both should be truncated
            assert len(llm_call.prompt) <= 70  # 50 + marker
            assert len(llm_call.response) <= 70
            assert "[TRUNCATED:" in llm_call.prompt
            assert "[TRUNCATED:" in llm_call.response




class TestSanitizationPerformance:
    """Test performance of sanitization."""

    def test_sanitization_overhead_acceptable(self):
        """Ensure sanitization adds minimal overhead."""
        db_manager = init_database("sqlite:///:memory:")
        backend = SQLObservabilityBackend()
        tracker = ExecutionTracker(backend=backend)

        import time

        # Measure time for 100 calls
        start = time.time()
        for i in range(100):
            tracker.track_llm_call(
                agent_id=f"agent-{i}",
                provider="openai",
                model="gpt-4",
                prompt="What is 2+2?" * 10,  # Moderate size
                response="4",
                prompt_tokens=10,
                completion_tokens=1,
                latency_ms=100,
                estimated_cost_usd=0.001
            )
        elapsed = time.time() - start

        # Should complete in reasonable time (<5 seconds for 100 calls)
        assert elapsed < 5.0, f"Sanitization too slow: {elapsed:.2f}s for 100 calls"


