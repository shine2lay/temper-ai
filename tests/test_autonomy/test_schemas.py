"""Tests for autonomous loop schemas."""

import pytest

from temper_ai.autonomy._schemas import (
    AutonomousLoopConfig,
    PostExecutionReport,
    WorkflowRunContext,
)


class TestAutonomousLoopConfig:
    """Tests for AutonomousLoopConfig schema."""

    def test_defaults(self) -> None:
        config = AutonomousLoopConfig()
        assert config.enabled is False
        assert config.learning_enabled is True
        assert config.goals_enabled is True
        assert config.portfolio_enabled is True

    def test_enabled(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        assert config.enabled is True

    def test_selective_disable(self) -> None:
        config = AutonomousLoopConfig(
            enabled=True, learning_enabled=False, goals_enabled=True
        )
        assert config.enabled is True
        assert config.learning_enabled is False
        assert config.goals_enabled is True

    def test_from_dict(self) -> None:
        data = {"enabled": True, "portfolio_enabled": False}
        config = AutonomousLoopConfig(**data)
        assert config.enabled is True
        assert config.portfolio_enabled is False

    def test_empty_dict_gives_defaults(self) -> None:
        config = AutonomousLoopConfig(**{})
        assert config.enabled is False


class TestWorkflowRunContext:
    """Tests for WorkflowRunContext schema."""

    def test_required_fields(self) -> None:
        ctx = WorkflowRunContext(
            workflow_id="wf-123", workflow_name="test_wf"
        )
        assert ctx.workflow_id == "wf-123"
        assert ctx.workflow_name == "test_wf"
        assert ctx.product_type is None
        assert ctx.result == {}
        assert ctx.duration_seconds == 0.0
        assert ctx.status == "unknown"
        assert ctx.cost_usd == 0.0
        assert ctx.total_tokens == 0

    def test_full_context(self) -> None:
        ctx = WorkflowRunContext(
            workflow_id="wf-456",
            workflow_name="prod_wf",
            product_type="api",
            result={"key": "value"},
            duration_seconds=12.5,
            status="completed",
            cost_usd=0.05,
            total_tokens=1500,
        )
        assert ctx.product_type == "api"
        assert ctx.result == {"key": "value"}
        assert ctx.duration_seconds == 12.5
        assert ctx.cost_usd == 0.05

    def test_missing_required_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            WorkflowRunContext()  # type: ignore[call-arg]


class TestPostExecutionReport:
    """Tests for PostExecutionReport schema."""

    def test_empty_report(self) -> None:
        report = PostExecutionReport()
        assert report.learning_result is None
        assert report.goals_result is None
        assert report.portfolio_result is None
        assert report.errors == []
        assert report.duration_ms == 0.0

    def test_with_results(self) -> None:
        report = PostExecutionReport(
            learning_result={"patterns_found": 3},
            goals_result={"proposals_generated": 1},
            portfolio_result={"scorecards": 2},
            duration_ms=150.5,
        )
        assert report.learning_result["patterns_found"] == 3
        assert report.goals_result["proposals_generated"] == 1
        assert report.portfolio_result["scorecards"] == 2
        assert report.duration_ms == 150.5

    def test_with_errors(self) -> None:
        report = PostExecutionReport(
            errors=["Learning subsystem error: connection refused"]
        )
        assert len(report.errors) == 1
        assert "Learning" in report.errors[0]
