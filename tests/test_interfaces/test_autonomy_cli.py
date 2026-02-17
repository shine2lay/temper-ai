"""Tests for autonomy CLI commands."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from src.interfaces.cli.autonomy_commands import autonomy_group
from src.safety.autonomy.emergency_stop import reset_emergency_state
from src.safety.autonomy.models import AutonomyState, AutonomyTransition, BudgetRecord
from src.safety.autonomy.store import AutonomyStore


@pytest.fixture(autouse=True)
def _reset_stop() -> None:
    """Reset emergency stop state before each test."""
    reset_emergency_state()


def _make_store() -> AutonomyStore:
    return AutonomyStore(database_url="sqlite:///:memory:")


class TestStatusCommand:
    """Tests for 'maf autonomy status'."""

    def test_no_states(self) -> None:
        """Shows message when no states exist."""
        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = _make_store()
            result = runner.invoke(autonomy_group, ["status"])
        assert result.exit_code == 0
        assert "No autonomy states" in result.output

    def test_shows_states(self) -> None:
        """Shows agent states in table."""
        store = _make_store()
        store.save_state(AutonomyState(
            id="as-1", agent_name="researcher", domain="analysis", current_level=1,
        ))

        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = store
            result = runner.invoke(autonomy_group, ["status"])
        assert result.exit_code == 0
        assert "researcher" in result.output

    def test_filter_by_agent(self) -> None:
        """Filters states by agent name."""
        store = _make_store()
        store.save_state(AutonomyState(id="as-1", agent_name="a", domain="d"))
        store.save_state(AutonomyState(id="as-2", agent_name="b", domain="d"))

        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = store
            result = runner.invoke(autonomy_group, ["status", "--agent", "a"])
        assert result.exit_code == 0
        assert "a" in result.output


class TestEscalateCommand:
    """Tests for 'maf autonomy escalate'."""

    def test_escalation(self) -> None:
        """Escalates agent level."""
        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = _make_store()
            result = runner.invoke(
                autonomy_group, ["escalate", "--agent", "agent-a"],
            )
        assert result.exit_code == 0
        assert "Escalated" in result.output

    def test_no_escalation(self) -> None:
        """Shows message when no escalation occurs."""
        store = _make_store()
        # Set max_level to SUPERVISED by escalating twice with max_level=RISK_GATED
        # Actually the easiest is to set it up so escalation fails
        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock_store:
            mock_store.return_value = store
            # First escalation succeeds
            runner.invoke(autonomy_group, ["escalate", "--agent", "a"])
            # Second may be blocked by cooldown
            result = runner.invoke(autonomy_group, ["escalate", "--agent", "a"])
        assert result.exit_code == 0
        assert "No escalation" in result.output


class TestDeescalateCommand:
    """Tests for 'maf autonomy deescalate'."""

    def test_no_deescalate_at_supervised(self) -> None:
        """Shows message when already at SUPERVISED."""
        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = _make_store()
            result = runner.invoke(
                autonomy_group, ["deescalate", "--agent", "agent-a"],
            )
        assert result.exit_code == 0
        assert "No de-escalation" in result.output


class TestEmergencyStopCommand:
    """Tests for emergency stop CLI commands."""

    def test_activate(self) -> None:
        """Activates emergency stop."""
        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = _make_store()
            with patch("src.interfaces.cli.autonomy_commands.reset_emergency_state", create=True):
                result = runner.invoke(
                    autonomy_group, ["emergency-stop", "--reason", "test stop"],
                )
        assert result.exit_code == 0
        assert "EMERGENCY STOP ACTIVATED" in result.output

    def test_resume_not_active(self) -> None:
        """Shows message when stop not active."""
        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = _make_store()
            result = runner.invoke(
                autonomy_group, ["resume", "--reason", "all clear"],
            )
        assert result.exit_code == 0
        assert "not active" in result.output


class TestBudgetCommand:
    """Tests for 'maf autonomy budget'."""

    def test_no_budgets(self) -> None:
        """Shows message when no budgets exist."""
        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = _make_store()
            result = runner.invoke(autonomy_group, ["budget"])
        assert result.exit_code == 0
        assert "No budget" in result.output

    def test_scope_budget(self) -> None:
        """Shows budget for specific scope."""
        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = _make_store()
            result = runner.invoke(
                autonomy_group, ["budget", "--scope", "agent-a"],
            )
        assert result.exit_code == 0
        assert "Budget" in result.output


class TestHistoryCommand:
    """Tests for 'maf autonomy history'."""

    def test_no_transitions(self) -> None:
        """Shows message when no transitions exist."""
        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = _make_store()
            result = runner.invoke(autonomy_group, ["history"])
        assert result.exit_code == 0
        assert "No transitions" in result.output

    def test_shows_transitions(self) -> None:
        """Shows transition history."""
        store = _make_store()
        store.save_transition(AutonomyTransition(
            id="at-1", agent_name="a", domain="d",
            from_level=0, to_level=1, reason="test", trigger="manual",
        ))

        runner = CliRunner()
        with patch("src.interfaces.cli.autonomy_commands._get_store") as mock:
            mock.return_value = store
            result = runner.invoke(autonomy_group, ["history"])
        assert result.exit_code == 0
        assert "manual" in result.output
