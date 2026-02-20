"""Agent performance tracking across executions (M9)."""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PERFORMANCE_NAMESPACE = "agent_performance"
FORMAT_TEMPLATE = (
    "Performance: {total} runs, {rate:.0%} success rate, "
    "avg {duration:.1f}s, avg {tokens:.0f} tokens/run"
)


@dataclass
class ExecutionMetrics:
    """Metrics from a single agent execution."""

    duration_seconds: float = 0.0
    success: bool = True
    tokens_used: int = 0
    tool_calls: int = 0
    error_message: Optional[str] = None


@dataclass
class PerformanceSummary:
    """Aggregated performance stats for an agent."""

    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    avg_duration_seconds: float = 0.0
    total_tokens_used: int = 0
    avg_tokens_per_execution: float = 0.0
    success_rate: float = 0.0


class AgentPerformanceTracker:
    """Track and aggregate agent execution performance.

    Uses in-memory storage (optionally backed by memory service).
    """

    def __init__(self, memory_service: Any = None) -> None:
        self._memory_service = memory_service
        self._records: Dict[str, List[ExecutionMetrics]] = {}

    def record_execution(
        self, agent_name: str, metrics: ExecutionMetrics
    ) -> None:
        """Record execution metrics for an agent."""
        if agent_name not in self._records:
            self._records[agent_name] = []
        self._records[agent_name].append(metrics)

    def get_summary(self, agent_name: str) -> PerformanceSummary:
        """Get aggregated performance summary for an agent."""
        records = self._records.get(agent_name, [])
        if not records:
            return PerformanceSummary()

        total = len(records)
        successes = sum(1 for r in records if r.success)
        total_duration = sum(r.duration_seconds for r in records)
        total_tokens = sum(r.tokens_used for r in records)

        return PerformanceSummary(
            total_executions=total,
            successful_executions=successes,
            failed_executions=total - successes,
            avg_duration_seconds=total_duration / total if total else 0.0,
            total_tokens_used=total_tokens,
            avg_tokens_per_execution=total_tokens / total if total else 0.0,
            success_rate=successes / total if total else 0.0,
        )

    def format_context(self, agent_name: str, max_chars: int = 500) -> str:
        """Format performance stats as context string for prompt injection."""
        summary = self.get_summary(agent_name)
        if summary.total_executions == 0:
            return ""

        text = FORMAT_TEMPLATE.format(
            total=summary.total_executions,
            rate=summary.success_rate,
            duration=summary.avg_duration_seconds,
            tokens=summary.avg_tokens_per_execution,
        )
        return text[:max_chars]
