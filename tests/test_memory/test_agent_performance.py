"""Tests for AgentPerformanceTracker (M9)."""

from temper_ai.memory.agent_performance import (
    AgentPerformanceTracker,
    ExecutionMetrics,
    PerformanceSummary,
)


class TestExecutionMetrics:
    def test_defaults(self):
        m = ExecutionMetrics()
        assert m.duration_seconds == 0.0
        assert m.success is True
        assert m.tokens_used == 0
        assert m.tool_calls == 0
        assert m.error_message is None

    def test_custom_values(self):
        m = ExecutionMetrics(
            duration_seconds=1.5,
            success=False,
            tokens_used=100,
            tool_calls=3,
            error_message="oops",
        )
        assert m.duration_seconds == 1.5
        assert m.success is False
        assert m.tokens_used == 100
        assert m.error_message == "oops"


class TestPerformanceSummary:
    def test_defaults(self):
        s = PerformanceSummary()
        assert s.total_executions == 0
        assert s.successful_executions == 0
        assert s.failed_executions == 0
        assert s.avg_duration_seconds == 0.0
        assert s.total_tokens_used == 0
        assert s.avg_tokens_per_execution == 0.0
        assert s.success_rate == 0.0


class TestAgentPerformanceTracker:
    def test_record_execution_stores_metrics(self):
        tracker = AgentPerformanceTracker()
        m = ExecutionMetrics(duration_seconds=1.0)
        tracker.record_execution("agent_a", m)
        assert "agent_a" in tracker._records
        assert len(tracker._records["agent_a"]) == 1

    def test_get_summary_no_records_returns_empty(self):
        tracker = AgentPerformanceTracker()
        summary = tracker.get_summary("nonexistent")
        assert isinstance(summary, PerformanceSummary)
        assert summary.total_executions == 0

    def test_get_summary_computes_totals(self):
        tracker = AgentPerformanceTracker()
        tracker.record_execution(
            "agent_a", ExecutionMetrics(duration_seconds=2.0, tokens_used=100)
        )
        tracker.record_execution(
            "agent_a", ExecutionMetrics(duration_seconds=4.0, tokens_used=200)
        )
        summary = tracker.get_summary("agent_a")
        assert summary.total_executions == 2
        assert summary.avg_duration_seconds == 3.0
        assert summary.total_tokens_used == 300
        assert summary.avg_tokens_per_execution == 150.0

    def test_get_summary_mixed_success_failure(self):
        tracker = AgentPerformanceTracker()
        tracker.record_execution("agent_a", ExecutionMetrics(success=True))
        tracker.record_execution("agent_a", ExecutionMetrics(success=False))
        summary = tracker.get_summary("agent_a")
        assert summary.successful_executions == 1
        assert summary.failed_executions == 1
        assert summary.success_rate == 0.5

    def test_get_summary_all_success(self):
        tracker = AgentPerformanceTracker()
        for _ in range(3):
            tracker.record_execution("agent_a", ExecutionMetrics(success=True))
        summary = tracker.get_summary("agent_a")
        assert summary.success_rate == 1.0

    def test_format_context_no_records_returns_empty(self):
        tracker = AgentPerformanceTracker()
        result = tracker.format_context("agent_a")
        assert result == ""

    def test_format_context_with_records(self):
        tracker = AgentPerformanceTracker()
        tracker.record_execution(
            "agent_a", ExecutionMetrics(duration_seconds=2.0, tokens_used=100)
        )
        result = tracker.format_context("agent_a")
        assert "1 runs" in result
        assert "100% success rate" in result

    def test_format_context_respects_max_chars(self):
        tracker = AgentPerformanceTracker()
        tracker.record_execution(
            "agent_a", ExecutionMetrics(duration_seconds=2.0, tokens_used=100)
        )
        result = tracker.format_context("agent_a", max_chars=5)
        assert len(result) <= 5

    def test_multiple_agents_tracked_independently(self):
        tracker = AgentPerformanceTracker()
        tracker.record_execution("agent_a", ExecutionMetrics(success=True))
        tracker.record_execution("agent_b", ExecutionMetrics(success=False))
        summary_a = tracker.get_summary("agent_a")
        summary_b = tracker.get_summary("agent_b")
        assert summary_a.success_rate == 1.0
        assert summary_b.success_rate == 0.0

    def test_init_without_memory_service(self):
        tracker = AgentPerformanceTracker()
        assert tracker._memory_service is None
