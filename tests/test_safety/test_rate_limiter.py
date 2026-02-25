"""Comprehensive tests for WindowRateLimitPolicy.

Tests cover:
- Configuration and initialization
- Rate limit enforcement (per second, minute, hour)
- Entity tracking (per-agent vs global)
- History cleanup
- Violation severity calculation
- Operation recording
- Reset functionality
- Edge cases and error handling

Target Coverage: 55%+ for rate_limiter.py
"""

import time
from unittest.mock import patch

import pytest

from temper_ai.safety.interfaces import ViolationSeverity
from temper_ai.safety.rate_limiter import WindowRateLimitPolicy


class TestRateLimiterBasics:
    """Basic tests for WindowRateLimitPolicy initialization and properties."""

    def test_default_initialization(self):
        """Test policy with default configuration."""
        policy = WindowRateLimitPolicy()

        assert policy.name == "rate_limiter"
        assert policy.version == "1.0.0"
        assert policy.priority == 85
        assert policy.limits == WindowRateLimitPolicy.DEFAULT_LIMITS
        assert policy.strategy == "sliding_window"
        assert policy.burst_allowance == 1.5
        assert policy.per_entity is True

    def test_empty_config_uses_defaults(self):
        """Test that empty config uses all defaults."""
        policy = WindowRateLimitPolicy({})

        assert policy.limits == WindowRateLimitPolicy.DEFAULT_LIMITS
        assert policy.strategy == "sliding_window"

    def test_none_config_uses_defaults(self):
        """Test that None config uses all defaults."""
        policy = WindowRateLimitPolicy(None)

        assert policy.name == "rate_limiter"
        assert policy.limits == WindowRateLimitPolicy.DEFAULT_LIMITS


class TestRateLimitEnforcement:
    """Tests for rate limit enforcement logic."""

    def test_operation_within_limit(self):
        """Test operation within rate limit passes."""
        policy = WindowRateLimitPolicy()

        # Use default llm_call limit (100/min)
        result = policy.validate(
            action={"operation": "llm_call"}, context={"agent_id": "agent-1"}
        )

        assert result.valid
        assert len(result.violations) == 0

    def test_per_second_limit_exceeded(self):
        """Test that exceeding per-second limit is detected."""
        policy = WindowRateLimitPolicy()

        # Use api_call which has max_per_second: 20 in defaults
        # We'll make 21 calls to exceed
        for i in range(20):
            result = policy.validate(
                action={"operation": "api_call"}, context={"agent_id": "agent-1"}
            )
            assert result.valid, f"Call {i+1} should be valid"

        # 21st operation should fail
        result = policy.validate(
            action={"operation": "api_call"}, context={"agent_id": "agent-1"}
        )

        assert not result.valid
        assert len(result.violations) >= 1
        assert "Rate limit exceeded" in result.violations[0].message
        assert result.violations[0].severity >= ViolationSeverity.HIGH

    def test_per_minute_limit_exceeded(self):
        """Test that exceeding per-minute limit is detected."""
        policy = WindowRateLimitPolicy()

        # Use tool_call which has max_per_minute: 60 in defaults
        for i in range(60):
            result = policy.validate(
                action={"operation": "tool_call"}, context={"agent_id": "test-agent"}
            )
            assert result.valid, f"Call {i+1} should be valid"

        # 61st operation should fail
        result = policy.validate(
            action={"operation": "tool_call"}, context={"agent_id": "test-agent"}
        )

        assert not result.valid
        assert "minute" in result.violations[0].message.lower()

    def test_unknown_operation_allowed(self):
        """Test that operations without configured limits are allowed."""
        policy = WindowRateLimitPolicy()

        result = policy.validate(
            action={"operation": "unconfigured_operation"}, context={}
        )

        assert result.valid

    def test_multiple_violations_same_operation(self):
        """Test multiple limit violations for same operation."""
        policy = WindowRateLimitPolicy()

        # Fill up api_call limit (20/sec, 1000/min)
        for _ in range(20):
            policy.validate(action={"operation": "api_call"}, context={})

        # Next call should violate per_second limit
        result = policy.validate(action={"operation": "api_call"}, context={})

        assert not result.valid
        # Should have at least one violation
        assert len(result.violations) >= 1


class TestEntityTracking:
    """Tests for per-entity vs global rate limiting."""

    def test_per_entity_tracking(self):
        """Test that per_entity=True tracks limits per agent."""
        policy = WindowRateLimitPolicy()

        # Agent 1 uses some of their api_call limit
        for _ in range(10):
            result = policy.validate(
                action={"operation": "api_call"}, context={"agent_id": "agent-1"}
            )
            assert result.valid

        # Agent 2 should still have their own capacity
        for _ in range(10):
            result = policy.validate(
                action={"operation": "api_call"}, context={"agent_id": "agent-2"}
            )
            assert result.valid

    def test_entity_key_extraction(self):
        """Test entity key extraction from context."""
        # Intentional private access: unit test for key derivation logic
        policy = WindowRateLimitPolicy()

        # Test with agent_id
        key1 = policy._get_entity_key({"agent_id": "agent-1", "user_id": "user-1"})
        assert key1 == "agent-1"

        # Test with user_id (no agent_id)
        key2 = policy._get_entity_key({"user_id": "user-2"})
        assert key2 == "user-2"

        # Test with workflow_id (no agent_id or user_id)
        key3 = policy._get_entity_key({"workflow_id": "workflow-1"})
        assert key3 == "workflow-1"

        # Test with no entity info
        key4 = policy._get_entity_key({})
        assert key4 == "global"


class TestHistoryCleanup:
    """Tests for history cleanup and memory management."""

    def test_old_records_cleaned(self):
        """Test that old records are removed from history."""
        policy = WindowRateLimitPolicy()

        # Add some operations at time 1000
        with patch("time.time", return_value=1000.0):
            policy.validate(action={"operation": "api_call"}, context={})

        # Simulate time passing (2 seconds) - old record should be cleaned
        with patch("time.time", return_value=1002.0):
            # Should have capacity since old records are cleaned
            result = policy.validate(action={"operation": "api_call"}, context={})
            assert result.valid

    def test_clean_old_records_function(self):
        """Test _clean_old_records helper method."""
        # Intentional private access: unit test for history cleanup logic
        policy = WindowRateLimitPolicy()

        now = time.time()
        history = [
            now - 100,  # 100s ago
            now - 50,  # 50s ago
            now - 5,  # 5s ago
            now - 1,  # 1s ago
        ]

        # Keep records from last 10 seconds
        cleaned = policy._clean_old_records(history, max_age_seconds=10.0)

        assert len(cleaned) == 2  # Only last two records
        assert cleaned[0] == history[2]
        assert cleaned[1] == history[3]


class TestResetFunctionality:
    """Tests for reset_limits() functionality."""

    def test_reset_all_limits(self):
        """Test resetting all rate limits."""
        policy = WindowRateLimitPolicy()

        # Use up some api_call limit
        for _ in range(20):
            policy.validate(
                action={"operation": "api_call"}, context={"agent_id": "agent-1"}
            )

        # Should be blocked now
        result = policy.validate(
            action={"operation": "api_call"}, context={"agent_id": "agent-1"}
        )
        assert not result.valid

        # Reset all limits
        policy.reset_limits()

        # Should now work
        result = policy.validate(
            action={"operation": "api_call"}, context={"agent_id": "agent-1"}
        )
        assert result.valid

    def test_reset_specific_operation(self):
        """Test resetting limits for specific operation."""
        policy = WindowRateLimitPolicy()

        # Use up limits for two operations
        for _ in range(20):
            policy.validate(action={"operation": "api_call"}, context={})
        for _ in range(60):
            policy.validate(action={"operation": "tool_call"}, context={})

        # Both should be blocked
        assert not policy.validate(action={"operation": "api_call"}, context={}).valid
        assert not policy.validate(action={"operation": "tool_call"}, context={}).valid

        # Reset only api_call
        policy.reset_limits(operation="api_call")

        # api_call should work
        result = policy.validate(action={"operation": "api_call"}, context={})
        assert result.valid

        # tool_call should still be blocked
        result = policy.validate(action={"operation": "tool_call"}, context={})
        assert not result.valid

    def test_reset_specific_entity(self):
        """Test resetting limits for specific entity."""
        policy = WindowRateLimitPolicy()

        # Use up limits for two agents
        for _ in range(20):
            policy.validate(
                action={"operation": "api_call"}, context={"agent_id": "agent-1"}
            )
        for _ in range(20):
            policy.validate(
                action={"operation": "api_call"}, context={"agent_id": "agent-2"}
            )

        # Both should be blocked
        assert not policy.validate(
            action={"operation": "api_call"}, context={"agent_id": "agent-1"}
        ).valid
        assert not policy.validate(
            action={"operation": "api_call"}, context={"agent_id": "agent-2"}
        ).valid

        # Reset only agent-1
        policy.reset_limits(entity="agent-1")

        # agent-1 should work
        result = policy.validate(
            action={"operation": "api_call"}, context={"agent_id": "agent-1"}
        )
        assert result.valid

        # agent-2 should still be blocked
        result = policy.validate(
            action={"operation": "api_call"}, context={"agent_id": "agent-2"}
        )
        assert not result.valid


class TestFormatWindow:
    """Tests for time window formatting."""

    def test_format_seconds(self):
        """Test formatting for seconds."""
        policy = WindowRateLimitPolicy()

        assert policy._format_window(1.0) == "1 second"
        assert policy._format_window(2.0) == "2 seconds"
        assert policy._format_window(30.0) == "30 seconds"

    def test_format_minutes(self):
        """Test formatting for minutes."""
        policy = WindowRateLimitPolicy()

        assert policy._format_window(60.0) == "1 minute"
        assert policy._format_window(120.0) == "2 minutes"
        assert policy._format_window(300.0) == "5 minutes"

    def test_format_hours(self):
        """Test formatting for hours."""
        policy = WindowRateLimitPolicy()

        assert policy._format_window(3600.0) == "1 hour"
        assert policy._format_window(7200.0) == "2 hours"


class TestAsyncValidation:
    """Tests for async validation support."""

    @pytest.mark.asyncio
    async def test_async_validation_basic(self):
        """Test basic async validation."""
        policy = WindowRateLimitPolicy()

        # Should work like sync version
        result = await policy.validate_async(
            action={"operation": "llm_call"}, context={}
        )

        assert result.valid

    @pytest.mark.asyncio
    async def test_async_validation_enforces_limits(self):
        """Test that async validation enforces limits."""
        policy = WindowRateLimitPolicy()

        # Fill up api_call limit
        for _ in range(20):
            await policy.validate_async(action={"operation": "api_call"}, context={})

        # Next should fail
        result = await policy.validate_async(
            action={"operation": "api_call"}, context={}
        )
        assert not result.valid


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_empty_action(self):
        """Test with empty action dict."""
        policy = WindowRateLimitPolicy()

        result = policy.validate(action={}, context={})
        assert result.valid  # Unknown operation is allowed

    def test_missing_operation_field(self):
        """Test action without operation field."""
        policy = WindowRateLimitPolicy()

        result = policy.validate(action={"other_field": "value"}, context={})
        assert result.valid  # Defaults to "unknown"

    def test_empty_context(self):
        """Test with empty context."""
        policy = WindowRateLimitPolicy()

        result = policy.validate(action={"operation": "llm_call"}, context={})
        assert result.valid

    def test_violation_metadata(self):
        """Test that violations include useful metadata."""
        policy = WindowRateLimitPolicy()

        # Use up api_call limit
        for _ in range(20):
            policy.validate(action={"operation": "api_call"}, context={})

        # Trigger violation
        result = policy.validate(action={"operation": "api_call"}, context={})

        assert not result.valid
        violation = result.violations[0]
        assert "current_count" in violation.metadata
        assert "max_count" in violation.metadata
        assert "window_seconds" in violation.metadata
        assert "overage_ratio" in violation.metadata
        assert "wait_seconds" in violation.context

    def test_remediation_hint_provided(self):
        """Test that violations include remediation hints."""
        policy = WindowRateLimitPolicy()

        # Use up limit
        for _ in range(20):
            policy.validate(action={"operation": "api_call"}, context={})

        result = policy.validate(action={"operation": "api_call"}, context={})

        assert not result.valid
        assert result.violations[0].remediation_hint is not None
        assert "Wait" in result.violations[0].remediation_hint

    def test_check_limit_function(self):
        """Test _check_limit helper method."""
        # Intentional private access: unit test for limit checking logic
        policy = WindowRateLimitPolicy()

        now = time.time()
        history = [now - 0.5, now - 0.3, now - 0.1]  # 3 recent operations

        # Should return violation when over limit
        violation = policy._check_limit(
            history=history, max_count=2, window_seconds=1.0, operation="test_op"
        )

        assert violation is not None
        assert violation.severity >= ViolationSeverity.HIGH
        assert "test_op" in violation.message

    def test_check_limit_no_violation(self):
        """Test _check_limit when within limit."""
        # Intentional private access: unit test for limit checking logic
        policy = WindowRateLimitPolicy()

        now = time.time()
        history = [now - 0.5]  # 1 operation

        # Should return None when within limit
        violation = policy._check_limit(
            history=history, max_count=5, window_seconds=1.0, operation="test_op"
        )

        assert violation is None
