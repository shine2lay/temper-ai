# Task Specification: code-high-m5-performance-analyzer

## Problem Statement

M5 needs to monitor agent performance over time to detect when optimization is needed. The analyzer must efficiently aggregate metrics from potentially thousands of executions using SQL (not Python loops) to remain performant.

## Acceptance Criteria

- Class `PerformanceAnalyzer` in `src/self_improvement/analysis/performance_analyzer.py`
- Method `analyze_agent_performance(agent_name: str, window_hours: int = 168) -> AgentPerformanceProfile`:
  - Queries database with SQL for efficient aggregation
  - Aggregates: mean, std, p95 for all metrics
  - Returns AgentPerformanceProfile dataclass
- Method `get_baseline(agent_name: str, window_days: int = 30) -> AgentPerformanceProfile`:
  - Retrieves historical baseline for comparison
  - Uses same aggregation logic
- Stores performance profiles in database for trend analysis
- No Python loops for aggregation - all SQL
- Handles missing data gracefully (agents with 0 executions)

## Implementation Details

```python
class PerformanceAnalyzer:
    def __init__(self, db):
        self.db = db

    def analyze_agent_performance(
        self,
        agent_name: str,
        window_hours: int = 168
    ) -> AgentPerformanceProfile:
        """
        Query DB for all metrics using SQL.
        Aggregate: mean, std, p95 for all metrics.
        """
        cutoff = utcnow() - timedelta(hours=window_hours)

        # Query built-in metrics (from agent_executions)
        builtin_query = """
        SELECT
            COUNT(*) as total_executions,
            AVG(CASE WHEN status = 'completed' THEN 1.0 ELSE 0.0 END) as success_rate,
            AVG(total_cost_usd) as avg_cost_usd,
            AVG(duration_seconds) as avg_duration_seconds
        FROM agent_executions
        WHERE agent_name = :agent_name AND created_at >= :cutoff
        """

        # Query custom metrics (from custom_metrics table)
        custom_query = """
        SELECT
            cm.metric_name,
            AVG(cm.metric_value) as mean,
            STDDEV(cm.metric_value) as std
        FROM custom_metrics cm
        JOIN agent_executions ae ON cm.workflow_execution_id = ae.id
        WHERE ae.agent_name = :agent_name AND ae.created_at >= :cutoff
        GROUP BY cm.metric_name
        """

        # Combine and return profile
        # ...

    def get_baseline(
        self,
        agent_name: str,
        window_days: int = 30
    ) -> AgentPerformanceProfile:
        """Retrieve historical baseline."""
        # Similar to analyze_agent_performance but for older time window
        # ...
```

## Test Strategy

1. Unit tests with mock database
2. Test with 0 executions (should handle gracefully)
3. Test with 100 executions (verify SQL aggregation)
4. Verify baseline retrieval works
5. Performance test: 10,000 executions should analyze in <1 second

## Dependencies

- code-med-m5-performance-profile-model
- test-med-m5-phase1-validation (need executions in DB to analyze)

## Estimated Effort

4-6 hours (SQL queries, aggregation logic, testing)
