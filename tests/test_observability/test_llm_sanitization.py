"""
Tests for LLM call sanitization in ExecutionTracker.

Ensures that prompts and responses are sanitized before storage to prevent
PII and secret exposure in the observability database.
"""

from datetime import UTC

import pytest

from temper_ai.observability.backends import SQLObservabilityBackend
from temper_ai.observability.sanitization import SanitizationConfig
from temper_ai.observability.tracker import ExecutionTracker
from temper_ai.storage.database import init_database
from temper_ai.storage.database.models import LLMCall


@pytest.fixture
def sql_backend():
    """Create SQL backend for testing."""
    import temper_ai.storage.database.manager as db_module
    from temper_ai.storage.database.manager import _db_lock

    # Clean up any existing instance
    with _db_lock:
        db_module._db_manager = None

    # Initialize in-memory database
    init_database("sqlite:///:memory:")
    backend = SQLObservabilityBackend(buffer=False)
    yield backend

    # Cleanup
    with _db_lock:
        db_module._db_manager = None


@pytest.fixture
def agent_id(sql_backend):
    """Create a real workflow/stage/agent hierarchy and return the agent_id."""
    from datetime import datetime

    from temper_ai.storage.database import get_session
    from temper_ai.storage.database.models import (
        AgentExecution,
        StageExecution,
        WorkflowExecution,
    )

    now = datetime.now(UTC)
    with get_session() as session:
        session.add(
            WorkflowExecution(
                id="wf-san-1",
                workflow_name="sanitize_test",
                workflow_config_snapshot={},
                status="running",
                start_time=now,
            )
        )
        session.flush()
        session.add(
            StageExecution(
                id="st-san-1",
                workflow_execution_id="wf-san-1",
                stage_name="s1",
                stage_config_snapshot={},
                status="running",
                start_time=now,
            )
        )
        session.flush()
        session.add(
            AgentExecution(
                id="agent-123",
                stage_execution_id="st-san-1",
                agent_name="a1",
                agent_config_snapshot={},
                status="running",
                start_time=now,
            )
        )
        session.commit()
    return "agent-123"


@pytest.fixture
def tracker(sql_backend, agent_id):
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
            prompt="Use API key sk-proj-abc123def456ghi789jkl012mno345 to authenticate",
            response="Authentication successful",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=250,
            estimated_cost_usd=0.001,
        )

        # Retrieve from backend
        with tracker.backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Prompt should be sanitized
            assert "sk-proj-abc123def456ghi789jkl012mno345" not in llm_call.prompt
            assert (
                "[OPENAI_PROJECT_KEY_REDACTED]" in llm_call.prompt
                or "[OPENAI_KEY_REDACTED]" in llm_call.prompt
            )

            # Response should be unchanged (no secrets)
            assert llm_call.response == "Authentication successful"

    def test_email_in_response_redacted(self, tracker):
        """Ensure emails in responses are redacted before storage."""
        config = SanitizationConfig(enable_pii_detection=True)
        tracker_with_pii = ExecutionTracker(
            backend=tracker.backend, sanitization_config=config
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
            estimated_cost_usd=0.002,
        )

        # Retrieve from backend
        with tracker.backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Email should be redacted
            assert "john.doe@company.com" not in llm_call.response
            assert "[EMAIL_REDACTED]" in llm_call.response

    def test_phone_number_in_response_redacted(self, tracker):
        """Ensure phone numbers in responses are redacted."""
        config = SanitizationConfig(
            enable_pii_detection=True, redact_phone_numbers=True
        )
        tracker_with_pii = ExecutionTracker(
            backend=tracker.backend, sanitization_config=config
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
            estimated_cost_usd=0.001,
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
            prompt="AWS key: AKIAIOSFODNN7EXAMPLE, API key: sk-proj-abc123def456ghi789jkl012mno345",
            response="Keys received",
            prompt_tokens=15,
            completion_tokens=3,
            latency_ms=250,
            estimated_cost_usd=0.002,
        )

        # Retrieve from backend
        with tracker.backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Both secrets should be redacted
            assert "AKIAIOSFODNN7EXAMPLE" not in llm_call.prompt
            assert "sk-proj-abc123def456ghi789jkl012mno345" not in llm_call.prompt
            assert "[AWS_ACCESS_KEY_REDACTED]" in llm_call.prompt
            assert "REDACTED" in llm_call.prompt

    def test_large_prompt_truncated(self, tracker):
        """Ensure large prompts are truncated."""
        config = SanitizationConfig(max_prompt_length=100)
        tracker_with_limits = ExecutionTracker(
            backend=tracker.backend, sanitization_config=config
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
            estimated_cost_usd=0.001,
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
            estimated_cost_usd=0.001,
        )

        # Retrieve from backend
        with tracker.backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Content should be unchanged
            assert llm_call.prompt == prompt
            assert llm_call.response == response


class TestSanitizationConfiguration:
    """Test sanitization configuration options."""

    def test_pii_detection_disabled(self, sql_backend, agent_id):
        """Test that PII detection can be disabled."""
        config = SanitizationConfig(enable_pii_detection=False)
        tracker = ExecutionTracker(backend=sql_backend, sanitization_config=config)

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
            estimated_cost_usd=0.001,
        )

        # Retrieve from backend
        with sql_backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Email should NOT be redacted (PII detection disabled)
            assert "john@example.com" in llm_call.prompt

    def test_secret_detection_always_enabled(self, sql_backend, agent_id):
        """Test that secret detection cannot be disabled."""
        config = SanitizationConfig(
            enable_secret_detection=True,  # Always true by default
            enable_pii_detection=False,
        )
        tracker = ExecutionTracker(backend=sql_backend, sanitization_config=config)

        # Track LLM call with API key
        llm_call_id = tracker.track_llm_call(
            agent_id="agent-123",
            provider="openai",
            model="gpt-4",
            prompt="Key: sk-proj-abc123def456ghi789jkl012mno345",
            response="OK",
            prompt_tokens=8,
            completion_tokens=1,
            latency_ms=100,
            estimated_cost_usd=0.001,
        )

        # Retrieve from backend
        with sql_backend.get_session_context() as session:
            llm_call = session.get(LLMCall, llm_call_id)

            # Secret should ALWAYS be redacted
            assert "sk-proj-abc123def456ghi789jkl012mno345" not in llm_call.prompt
            assert "REDACTED" in llm_call.prompt

    def test_custom_length_limits(self, sql_backend, agent_id):
        """Test custom length limits."""
        config = SanitizationConfig(max_prompt_length=50, max_response_length=50)
        tracker = ExecutionTracker(backend=sql_backend, sanitization_config=config)

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
            estimated_cost_usd=0.002,
        )

        # Retrieve from backend
        with sql_backend.get_session_context() as session:
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
        from temper_ai.observability.backends.noop_backend import NoOpBackend

        tracker = ExecutionTracker(backend=NoOpBackend())

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
                estimated_cost_usd=0.001,
            )
        elapsed = time.time() - start

        # Should complete in reasonable time (<5 seconds for 100 calls)
        assert elapsed < 5.0, f"Sanitization too slow: {elapsed:.2f}s for 100 calls"
