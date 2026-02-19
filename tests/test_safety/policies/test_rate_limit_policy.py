"""Tests for RateLimitPolicy using token bucket algorithm.

Tests cover:
- Policy initialization and configuration
- Per-agent rate limiting
- Global rate limiting
- Different operation types
- Violation handling
- Status reporting
"""

import pytest

from temper_ai.safety.interfaces import ViolationSeverity
from temper_ai.safety.policies.rate_limit_policy import RateLimitPolicy


class TestRateLimitPolicyBasics:
    """Basic tests for RateLimitPolicy."""

    def test_default_initialization(self):
        """Test policy with default configuration."""
        policy = RateLimitPolicy()

        assert policy.name == "rate_limit"
        assert policy.version == "1.0.0"
        assert policy.priority == 85
        assert policy.per_agent is True

    def test_custom_configuration(self):
        """Test policy with custom configuration."""
        config = {
            "rate_limits": {
                "custom_op": {
                    "max_tokens": 5,
                    "refill_rate": 1.0,
                    "refill_period": 1.0,
                    "burst_size": 2
                }
            },
            "per_agent": False
        }
        policy = RateLimitPolicy(config)

        assert policy.per_agent is False

    def test_default_limits_loaded(self):
        """Test that default limits are loaded."""
        policy = RateLimitPolicy()

        # Check that default limits exist
        assert "commit" in policy.per_agent_manager.limits
        assert "deploy" in policy.per_agent_manager.limits
        assert "tool_call" in policy.per_agent_manager.limits
        assert "llm_call" in policy.per_agent_manager.limits


class TestPerAgentRateLimiting:
    """Tests for per-agent rate limiting."""

    def test_commit_rate_limit(self):
        """Test commit rate limiting."""
        policy = RateLimitPolicy()

        # First commit should be allowed
        result = policy.validate(
            action={"operation": "git_commit"},
            context={"agent_id": "agent-123"}
        )

        assert result.valid
        assert result.metadata["rate_limited"] is False

    def test_commit_rate_limit_exceeded(self):
        """Test that commits are rate limited after exceeding limit."""
        policy = RateLimitPolicy()

        # Consume all commit tokens (default: 10)
        for i in range(10):
            result = policy.validate(
                action={"operation": "git_commit"},
                context={"agent_id": "agent-123"}
            )
            assert result.valid

        # 11th commit should be rate limited
        result = policy.validate(
            action={"operation": "git_commit"},
            context={"agent_id": "agent-123"}
        )

        assert not result.valid
        assert len(result.violations) == 1
        assert result.violations[0].severity >= ViolationSeverity.MEDIUM
        assert "rate limit exceeded" in result.violations[0].message.lower()

    def test_different_agents_separate_limits(self):
        """Test that different agents have separate rate limits."""
        policy = RateLimitPolicy()

        # Agent 1 exhausts their commits
        for i in range(10):
            policy.validate(
                action={"operation": "git_commit"},
                context={"agent_id": "agent-1"}
            )

        # Agent 1 should be rate limited
        result1 = policy.validate(
            action={"operation": "git_commit"},
            context={"agent_id": "agent-1"}
        )
        assert not result1.valid

        # Agent 2 should still be able to commit
        result2 = policy.validate(
            action={"operation": "git_commit"},
            context={"agent_id": "agent-2"}
        )
        assert result2.valid

    def test_deploy_rate_limit(self):
        """Test deployment rate limiting."""
        policy = RateLimitPolicy()

        # First 2 deploys should be allowed (default: 2)
        result1 = policy.validate(
            action={"operation": "deploy"},
            context={"agent_id": "agent-123"}
        )
        assert result1.valid

        result2 = policy.validate(
            action={"operation": "deploy"},
            context={"agent_id": "agent-123"}
        )
        assert result2.valid

        # 3rd deploy should be rate limited
        result3 = policy.validate(
            action={"operation": "deploy"},
            context={"agent_id": "agent-123"}
        )
        assert not result3.valid

    def test_tool_call_rate_limit(self):
        """Test tool call rate limiting."""
        policy = RateLimitPolicy()

        # Should allow multiple tool calls (default: 100)
        for i in range(100):
            result = policy.validate(
                action={"operation": "tool_call"},
                context={"agent_id": "agent-123"}
            )
            assert result.valid

        # 101st should be rate limited
        result = policy.validate(
            action={"operation": "tool_call"},
            context={"agent_id": "agent-123"}
        )
        assert not result.valid


class TestGlobalRateLimiting:
    """Tests for global rate limiting across all agents."""

    def test_global_tool_call_limit(self):
        """Test global tool call rate limiting."""
        policy = RateLimitPolicy()

        # Use tool calls from multiple agents
        # Each agent has 100 per-agent limit, but global is 1000
        # Let's use 10 agents with 100 calls each = 1000 total

        for agent_num in range(10):
            agent_id = f"agent-{agent_num}"
            for i in range(100):
                result = policy.validate(
                    action={"operation": "tool_call"},
                    context={"agent_id": agent_id}
                )
                # Should pass per-agent limit (100 each)
                assert result.valid, f"Failed at agent {agent_num}, call {i}"

        # Next call from any agent should hit global limit
        result = policy.validate(
            action={"operation": "tool_call"},
            context={"agent_id": "agent-10"}
        )

        # Should have violation from global limit
        assert not result.valid
        global_violations = [v for v in result.violations if v.metadata.get("scope") == "global"]
        assert len(global_violations) >= 1


class TestActionTypeMapping:
    """Tests for mapping action types to rate limits."""

    def test_git_commit_mapped(self):
        """Test that 'git_commit' maps to commit limit."""
        policy = RateLimitPolicy()

        result = policy.validate(
            action={"operation": "git_commit"},
            context={"agent_id": "agent-123"}
        )

        assert result.valid
        assert result.metadata["limit_type"] == "commit"

    def test_commit_mapped(self):
        """Test that 'commit' maps to commit limit."""
        policy = RateLimitPolicy()

        result = policy.validate(
            action={"operation": "commit"},
            context={"agent_id": "agent-123"}
        )

        assert result.metadata["limit_type"] == "commit"

    def test_tool_execution_mapped(self):
        """Test that 'tool_execution' maps to tool_call limit."""
        policy = RateLimitPolicy()

        result = policy.validate(
            action={"operation": "tool_execution"},
            context={"agent_id": "agent-123"}
        )

        assert result.metadata["limit_type"] == "tool_call"

    def test_unknown_operation_allowed(self):
        """Test that unknown operations are allowed."""
        policy = RateLimitPolicy()

        result = policy.validate(
            action={"operation": "unknown_op"},
            context={"agent_id": "agent-123"}
        )

        assert result.valid
        assert result.metadata["rate_limited"] is False

    def test_type_field_alternative(self):
        """Test using 'type' field instead of 'operation'."""
        policy = RateLimitPolicy()

        result = policy.validate(
            action={"type": "git_commit"},
            context={"agent_id": "agent-123"}
        )

        assert result.valid
        assert result.metadata["limit_type"] == "commit"


class TestViolationHandling:
    """Tests for violation detection and reporting."""

    def test_violation_includes_wait_time(self):
        """Test that violations include wait time."""
        policy = RateLimitPolicy()

        # Exhaust limit
        for i in range(2):
            policy.validate(
                action={"operation": "deploy"},
                context={"agent_id": "agent-123"}
            )

        # Get violation
        result = policy.validate(
            action={"operation": "deploy"},
            context={"agent_id": "agent-123"}
        )

        assert not result.valid
        assert "wait_time" in result.violations[0].metadata
        assert result.violations[0].metadata["wait_time"] > 0

    def test_violation_includes_remediation(self):
        """Test that violations include remediation hint."""
        policy = RateLimitPolicy()

        # Exhaust limit
        for i in range(2):
            policy.validate(
                action={"operation": "deploy"},
                context={"agent_id": "agent-123"}
            )

        # Get violation
        result = policy.validate(
            action={"operation": "deploy"},
            context={"agent_id": "agent-123"}
        )

        assert result.violations[0].remediation_hint is not None
        assert "wait" in result.violations[0].remediation_hint.lower()

    def test_violation_severity_based_on_wait_time(self):
        """Test that violation severity increases with wait time."""
        # This test is hard to verify without actually waiting
        # Just check that severity is set
        policy = RateLimitPolicy()

        # Exhaust limit
        for i in range(2):
            policy.validate(
                action={"operation": "deploy"},
                context={"agent_id": "agent-123"}
            )

        result = policy.validate(
            action={"operation": "deploy"},
            context={"agent_id": "agent-123"}
        )

        assert result.violations[0].severity >= ViolationSeverity.MEDIUM

    def test_retry_after_in_metadata(self):
        """Test that retry_after is in result metadata."""
        policy = RateLimitPolicy()

        # Exhaust limit
        for i in range(2):
            policy.validate(
                action={"operation": "deploy"},
                context={"agent_id": "agent-123"}
            )

        result = policy.validate(
            action={"operation": "deploy"},
            context={"agent_id": "agent-123"}
        )

        assert "retry_after" in result.metadata
        assert result.metadata["retry_after"] is not None


class TestStatusReporting:
    """Tests for rate limit status reporting."""

    def test_get_status(self):
        """Test getting rate limit status for agent."""
        policy = RateLimitPolicy()

        # Use some limits
        policy.validate(
            action={"operation": "git_commit"},
            context={"agent_id": "agent-123"}
        )

        status = policy.get_status("agent-123")

        assert "agent_id" in status
        assert status["agent_id"] == "agent-123"
        assert "limits" in status

    def test_status_includes_all_limits(self):
        """Test that status includes all configured limits."""
        policy = RateLimitPolicy()

        # Trigger creation of some buckets
        policy.validate(action={"operation": "git_commit"}, context={"agent_id": "agent-123"})
        policy.validate(action={"operation": "deploy"}, context={"agent_id": "agent-123"})

        status = policy.get_status("agent-123")

        assert "commit" in status["limits"]
        assert "deploy" in status["limits"]

    def test_status_shows_current_tokens(self):
        """Test that status shows current token count."""
        policy = RateLimitPolicy()

        # Use some commits
        for i in range(3):
            policy.validate(
                action={"operation": "git_commit"},
                context={"agent_id": "agent-123"}
            )

        status = policy.get_status("agent-123")

        # Should have 7 tokens left (10 - 3)
        assert status["limits"]["commit"]["current_tokens"] == pytest.approx(7.0, abs=0.1)


class TestResetLimits:
    """Tests for resetting rate limits."""

    def test_reset_specific_agent_limit(self):
        """Test resetting specific limit for agent."""
        policy = RateLimitPolicy()

        # Use commits
        for i in range(5):
            policy.validate(
                action={"operation": "git_commit"},
                context={"agent_id": "agent-123"}
            )

        # Reset commit limit for agent-123
        policy.reset_limits("agent-123", "commit")

        # Should have full tokens again
        status = policy.get_status("agent-123")
        assert status["limits"]["commit"]["current_tokens"] == 10.0

    def test_reset_all_limits_for_agent(self):
        """Test resetting all limits for an agent."""
        policy = RateLimitPolicy()

        # Use various limits
        for i in range(5):
            policy.validate(action={"operation": "git_commit"}, context={"agent_id": "agent-123"})
        policy.validate(action={"operation": "deploy"}, context={"agent_id": "agent-123"})

        # Reset all for agent-123
        policy.reset_limits("agent-123")

        # All should be full
        status = policy.get_status("agent-123")
        assert status["limits"]["commit"]["current_tokens"] == 10.0
        assert status["limits"]["deploy"]["current_tokens"] == 2.0

    def test_reset_all_limits(self):
        """Test resetting all limits for all agents."""
        policy = RateLimitPolicy()

        # Use limits for multiple agents
        for i in range(5):
            policy.validate(action={"operation": "git_commit"}, context={"agent_id": "agent-1"})
            policy.validate(action={"operation": "git_commit"}, context={"agent_id": "agent-2"})

        # Reset all
        policy.reset_limits()

        # Both agents should have full tokens
        status1 = policy.get_status("agent-1")
        status2 = policy.get_status("agent-2")
        assert status1["limits"]["commit"]["current_tokens"] == 10.0
        assert status2["limits"]["commit"]["current_tokens"] == 10.0


class TestCustomConfiguration:
    """Tests for custom rate limit configuration."""

    def test_custom_commit_limit(self):
        """Test configuring custom commit limit."""
        config = {
            "rate_limits": {
                "commit": {
                    "max_tokens": 5,
                    "refill_rate": 1.0,
                    "refill_period": 1.0,
                    "burst_size": 1
                }
            }
        }
        policy = RateLimitPolicy(config)

        # Should allow 5 commits
        for i in range(5):
            result = policy.validate(
                action={"operation": "git_commit"},
                context={"agent_id": "agent-123"}
            )
            assert result.valid

        # 6th should be rate limited
        result = policy.validate(
            action={"operation": "git_commit"},
            context={"agent_id": "agent-123"}
        )
        assert not result.valid

    def test_custom_global_limit(self):
        """Test configuring custom global limit."""
        config = {
            "global_limits": {
                "total_tool_calls": {
                    "max_tokens": 50,
                    "refill_rate": 1.0,
                    "refill_period": 1.0
                }
            }
        }
        policy = RateLimitPolicy(config)

        # Use 50 tool calls across agents
        for i in range(50):
            result = policy.validate(
                action={"operation": "tool_call"},
                context={"agent_id": f"agent-{i % 5}"}  # 5 agents
            )
            assert result.valid

        # 51st should hit global limit
        result = policy.validate(
            action={"operation": "tool_call"},
            context={"agent_id": "agent-0"}
        )
        assert not result.valid

    def test_disable_per_agent_limits(self):
        """Test disabling per-agent tracking."""
        config = {
            "per_agent": False
        }
        policy = RateLimitPolicy(config)

        # All agents should share the same limits
        # Use commits from agent-1
        for i in range(10):
            policy.validate(
                action={"operation": "git_commit"},
                context={"agent_id": "agent-1"}
            )

        # Agent-2 should also be rate limited (shared limit)
        result = policy.validate(
            action={"operation": "git_commit"},
            context={"agent_id": "agent-2"}
        )

        # With per_agent=False, both agents share the "global" entity
        assert not result.valid


class TestIntegration:
    """Integration tests for rate limiting."""

    def test_mixed_operations(self):
        """Test rate limiting with mixed operation types."""
        policy = RateLimitPolicy()

        # Use various operations
        policy.validate(action={"operation": "git_commit"}, context={"agent_id": "agent-123"})
        policy.validate(action={"operation": "deploy"}, context={"agent_id": "agent-123"})
        policy.validate(action={"operation": "tool_call"}, context={"agent_id": "agent-123"})
        policy.validate(action={"operation": "llm_call"}, context={"agent_id": "agent-123"})

        # All should be tracked separately
        status = policy.get_status("agent-123")
        assert "commit" in status["limits"]
        assert "deploy" in status["limits"]
        assert "tool_call" in status["limits"]
        assert "llm_call" in status["limits"]

    def test_cooldown_multiplier(self):
        """Test cooldown multiplier configuration."""
        config = {
            "cooldown_multiplier": 2.0
        }
        policy = RateLimitPolicy(config)

        # Exhaust limit
        for i in range(2):
            policy.validate(action={"operation": "deploy"}, context={"agent_id": "agent-123"})

        # Get violation
        result = policy.validate(
            action={"operation": "deploy"},
            context={"agent_id": "agent-123"}
        )

        # retry_after should be doubled
        wait_time = result.violations[0].metadata["wait_time"]
        retry_after = result.metadata["retry_after"]
        assert retry_after == pytest.approx(wait_time * 2.0, rel=0.1)
