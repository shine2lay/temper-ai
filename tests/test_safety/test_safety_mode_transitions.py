"""Safety mode state transition tests.

Tests for safety mode transitions between:
- execute: Normal execution mode
- dry_run: Simulation mode (no actual changes)
- require_approval: Manual approval required

These modes are defined in SafetyConfig and control how risky
operations are handled during workflow execution.
"""
import pytest
from pydantic import ValidationError

from temper_ai.storage.schemas.agent_config import SafetyConfig


class TestSafetyModeValidation:
    """Test safety mode configuration validation."""

    def test_valid_execute_mode(self):
        """Test execute mode is valid."""
        config = SafetyConfig(mode="execute")
        assert config.mode == "execute"
        assert config.risk_level == "medium"  # default

    def test_valid_dry_run_mode(self):
        """Test dry_run mode is valid."""
        config = SafetyConfig(mode="dry_run")
        assert config.mode == "dry_run"

    def test_valid_require_approval_mode(self):
        """Test require_approval mode is valid."""
        config = SafetyConfig(mode="require_approval")
        assert config.mode == "require_approval"

    def test_invalid_mode_rejected(self):
        """Test invalid mode is rejected."""
        with pytest.raises(ValidationError):
            SafetyConfig(mode="invalid_mode")

    def test_mode_is_required(self):
        """Test mode defaults to execute if not specified."""
        config = SafetyConfig()
        assert config.mode == "execute"


class TestSafetyModeTransitions:
    """Test safety mode state transitions."""

    def test_execute_to_dry_run_transition(self):
        """Test transition from execute to dry_run mode.

        When high-risk operations are detected during execution,
        the system should escalate to dry_run mode.
        """
        # Start in execute mode
        config = SafetyConfig(mode="execute", risk_level="low")
        assert config.mode == "execute"

        # Simulate risk detection and escalation
        # In practice, this would be done by a RiskAssessor
        escalated_config = SafetyConfig(
            mode="dry_run",
            risk_level="high",
            require_approval_for_tools=config.require_approval_for_tools,
            max_tool_calls_per_execution=config.max_tool_calls_per_execution,
            max_execution_time_seconds=config.max_execution_time_seconds
        )

        assert escalated_config.mode == "dry_run"
        assert escalated_config.risk_level == "high"

    def test_dry_run_to_require_approval_transition(self):
        """Test transition from dry_run to require_approval mode.

        When safety violations are detected during dry_run,
        the system should escalate to require_approval mode.
        """
        # Start in dry_run mode
        config = SafetyConfig(mode="dry_run", risk_level="high")
        assert config.mode == "dry_run"

        # Simulate safety violation detection
        escalated_config = SafetyConfig(
            mode="require_approval",
            risk_level="high",
            require_approval_for_tools=["file_write", "database_modify"],
            max_tool_calls_per_execution=config.max_tool_calls_per_execution,
            max_execution_time_seconds=config.max_execution_time_seconds
        )

        assert escalated_config.mode == "require_approval"
        assert "file_write" in escalated_config.require_approval_for_tools

    def test_require_approval_to_execute_after_approval(self):
        """Test transition from require_approval back to execute.

        After human approval is granted, execution can proceed
        with the approved operations.
        """
        # Start in require_approval mode
        config = SafetyConfig(
            mode="require_approval",
            risk_level="high",
            require_approval_for_tools=["deployment", "database_modify"]
        )
        assert config.mode == "require_approval"

        # Simulate approval granted
        approved_config = SafetyConfig(
            mode="execute",
            risk_level="medium",  # Risk reduced after approval
            require_approval_for_tools=[],  # Clear approval requirements
            max_tool_calls_per_execution=config.max_tool_calls_per_execution,
            max_execution_time_seconds=config.max_execution_time_seconds
        )

        assert approved_config.mode == "execute"
        assert len(approved_config.require_approval_for_tools) == 0

    def test_execute_to_require_approval_direct(self):
        """Test direct transition from execute to require_approval.

        For critical operations, system may skip dry_run and go
        straight to require_approval.
        """
        # Start in execute mode
        config = SafetyConfig(mode="execute")

        # Critical operation detected
        critical_config = SafetyConfig(
            mode="require_approval",
            risk_level="high",
            require_approval_for_tools=["system_shutdown", "data_deletion"]
        )

        assert critical_config.mode == "require_approval"
        assert critical_config.risk_level == "high"


class TestSafetyModeContextPreservation:
    """Test that mode transitions preserve necessary context."""

    def test_transition_preserves_tool_limits(self):
        """Test that max_tool_calls is preserved across transitions."""
        original = SafetyConfig(
            mode="execute",
            max_tool_calls_per_execution=50
        )

        escalated = SafetyConfig(
            mode="dry_run",
            max_tool_calls_per_execution=original.max_tool_calls_per_execution
        )

        assert escalated.max_tool_calls_per_execution == 50

    def test_transition_preserves_time_limits(self):
        """Test that max_execution_time is preserved across transitions."""
        original = SafetyConfig(
            mode="execute",
            max_execution_time_seconds=600
        )

        escalated = SafetyConfig(
            mode="require_approval",
            max_execution_time_seconds=original.max_execution_time_seconds
        )

        assert escalated.max_execution_time_seconds == 600

    def test_transition_updates_risk_level(self):
        """Test that risk_level is updated appropriately."""
        low_risk = SafetyConfig(mode="execute", risk_level="low")
        assert low_risk.risk_level == "low"

        # Escalation should increase risk level
        high_risk = SafetyConfig(mode="dry_run", risk_level="high")
        assert high_risk.risk_level == "high"

        # Approval should reduce risk
        approved = SafetyConfig(mode="execute", risk_level="medium")
        assert approved.risk_level == "medium"

    def test_approval_tools_added_on_escalation(self):
        """Test that approval tool list grows during escalation."""
        # Start with some approval requirements
        config1 = SafetyConfig(
            mode="execute",
            require_approval_for_tools=["deployment"]
        )

        # Escalate with more tools requiring approval
        config2 = SafetyConfig(
            mode="require_approval",
            require_approval_for_tools=["deployment", "file_write", "database_modify"]
        )

        assert len(config2.require_approval_for_tools) > len(config1.require_approval_for_tools)
        assert "deployment" in config2.require_approval_for_tools
        assert "file_write" in config2.require_approval_for_tools


class TestSafetyModeEdgeCases:
    """Test edge cases in safety mode transitions."""

    def test_same_mode_transition_allowed(self):
        """Test that transitioning to same mode is allowed."""
        config1 = SafetyConfig(mode="execute")
        config2 = SafetyConfig(mode="execute", risk_level="low")

        # Both valid, no error
        assert config1.mode == "execute"
        assert config2.mode == "execute"

    def test_de_escalation_dry_run_to_execute(self):
        """Test de-escalation from dry_run to execute."""
        # Start in elevated mode
        config = SafetyConfig(mode="dry_run", risk_level="high")

        # Risk assessment shows safe to proceed
        de_escalated = SafetyConfig(
            mode="execute",
            risk_level="low"
        )

        assert de_escalated.mode == "execute"
        assert de_escalated.risk_level == "low"

    def test_mode_with_empty_approval_tools(self):
        """Test require_approval mode with empty tool list."""
        # This is valid - might be requiring approval for all tools
        # or approval list is managed elsewhere
        config = SafetyConfig(
            mode="require_approval",
            require_approval_for_tools=[]
        )

        assert config.mode == "require_approval"
        assert len(config.require_approval_for_tools) == 0

    def test_mode_with_max_approval_tools(self):
        """Test mode with many tools requiring approval."""
        tools = [f"tool_{i}" for i in range(100)]
        config = SafetyConfig(
            mode="require_approval",
            require_approval_for_tools=tools
        )

        assert len(config.require_approval_for_tools) == 100
