"""Targeted tests for uncovered paths in lifecycle/history.py.

Covers lines: 37-43, 61-67, 99-108, 145-147
"""

from unittest.mock import patch

from temper_ai.lifecycle._schemas import StageMetrics, WorkflowMetrics
from temper_ai.lifecycle.history import HistoryAnalyzer

# ── Lines 37-43: get_stage_metrics exception path ─────────────────────────


class TestGetStageMetricsExceptionHandling:
    """Covers lines 37-43: exception in _query_stage_metrics is caught."""

    def test_query_stage_metrics_exception_returns_empty(self):
        """Lines 38-43: _query_stage_metrics raises → returns {} with warning."""
        analyzer = HistoryAnalyzer(db_url="sqlite:///:memory:")

        with patch.object(
            analyzer,
            "_query_stage_metrics",
            side_effect=RuntimeError("query failed"),
        ):
            result = analyzer.get_stage_metrics("test_workflow")

        assert result == {}

    def test_get_stage_metrics_logs_warning_on_exception(self):
        """Lines 38-43: warning logged on exception with workflow name."""
        analyzer = HistoryAnalyzer(db_url="sqlite:///:memory:")

        with patch.object(
            analyzer,
            "_query_stage_metrics",
            side_effect=RuntimeError("query failed"),
        ):
            with patch("temper_ai.lifecycle.history.logger") as mock_logger:
                analyzer.get_stage_metrics("my_workflow")
                mock_logger.warning.assert_called_once()
                args = mock_logger.warning.call_args[0]
                assert "my_workflow" in str(args)

    def test_get_stage_metrics_custom_lookback_on_exception(self):
        """Lines 37-43: exception path with custom lookback_hours param."""
        analyzer = HistoryAnalyzer(db_url="sqlite:///:memory:")

        with patch.object(
            analyzer,
            "_query_stage_metrics",
            side_effect=Exception("connection refused"),
        ):
            result = analyzer.get_stage_metrics("wf", lookback_hours=48)

        assert result == {}


# ── Lines 61-67: get_workflow_metrics exception path ──────────────────────


class TestGetWorkflowMetricsExceptionHandling:
    """Covers lines 61-67: exception in _query_workflow_metrics is caught."""

    def test_query_workflow_metrics_exception_returns_default(self):
        """Lines 62-67: _query_workflow_metrics raises → returns default WorkflowMetrics."""
        analyzer = HistoryAnalyzer(db_url="sqlite:///:memory:")

        with patch.object(
            analyzer,
            "_query_workflow_metrics",
            side_effect=RuntimeError("query failed"),
        ):
            result = analyzer.get_workflow_metrics("test_workflow")

        assert isinstance(result, WorkflowMetrics)
        assert result.workflow_name == "test_workflow"
        assert result.run_count == 0
        assert result.success_rate == 1.0

    def test_get_workflow_metrics_logs_warning_on_exception(self):
        """Lines 62-67: warning logged on exception."""
        analyzer = HistoryAnalyzer(db_url="sqlite:///:memory:")

        with patch.object(
            analyzer,
            "_query_workflow_metrics",
            side_effect=RuntimeError("db error"),
        ):
            with patch("temper_ai.lifecycle.history.logger") as mock_logger:
                analyzer.get_workflow_metrics("flow_123")
                mock_logger.warning.assert_called_once()
                args = mock_logger.warning.call_args[0]
                assert "flow_123" in str(args)

    def test_get_workflow_metrics_custom_lookback_on_exception(self):
        """Lines 61-67: custom lookback_hours still returns default on exception."""
        analyzer = HistoryAnalyzer(db_url="sqlite:///:memory:")

        with patch.object(
            analyzer,
            "_query_workflow_metrics",
            side_effect=Exception("timeout"),
        ):
            result = analyzer.get_workflow_metrics("wf", lookback_hours=24)

        assert result.workflow_name == "wf"
        assert result.run_count == 0


# ── Lines 99-108: _query_stage_metrics with real data ─────────────────────


class TestQueryStageMetricsWithRealDB:
    """Covers lines 99-108: stage metrics query when rows exist in DB."""

    def _create_stage_executions_table(self, engine):
        """Create a stage_executions table and insert test data."""
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS stage_executions ("
                    "  stage_name TEXT, "
                    "  workflow_name TEXT, "
                    "  status TEXT, "
                    "  duration_seconds REAL, "
                    "  started_at TEXT"
                    ")"
                )
            )
            # Insert test rows
            conn.execute(
                text(
                    "INSERT INTO stage_executions VALUES "
                    "('design', 'my_wf', 'completed', 10.0, datetime('now')), "
                    "('design', 'my_wf', 'completed', 20.0, datetime('now')), "
                    "('design', 'my_wf', 'failed', 5.0, datetime('now')), "
                    "('impl', 'my_wf', 'completed', 30.0, datetime('now'))"
                )
            )
            conn.commit()

    def test_query_returns_stage_metrics_from_rows(self, tmp_path):
        """Lines 99-108: rows returned → StageMetrics built correctly."""
        db_path = str(tmp_path / "test_obs.db")
        db_url = f"sqlite:///{db_path}"

        from sqlalchemy import create_engine

        engine = create_engine(db_url)
        self._create_stage_executions_table(engine)

        analyzer = HistoryAnalyzer(db_url=db_url)
        result = analyzer.get_stage_metrics("my_wf")

        assert "design" in result
        assert "impl" in result

        design_metrics = result["design"]
        assert design_metrics.stage_name == "design"
        assert design_metrics.run_count == 3
        # success rate: 2/3 completed
        assert abs(design_metrics.success_rate - (2 / 3)) < 0.01
        # avg duration: (10 + 20 + 5) / 3
        assert abs(design_metrics.avg_duration - 35.0 / 3) < 0.01

    def test_query_stage_metrics_is_stagemetrics_objects(self, tmp_path):
        """Lines 102-107: each row produces a StageMetrics instance."""
        db_path = str(tmp_path / "test_obs2.db")
        db_url = f"sqlite:///{db_path}"

        from sqlalchemy import create_engine

        engine = create_engine(db_url)
        self._create_stage_executions_table(engine)

        analyzer = HistoryAnalyzer(db_url=db_url)
        result = analyzer.get_stage_metrics("my_wf")

        for name, metrics in result.items():
            assert isinstance(metrics, StageMetrics)
            assert metrics.stage_name == name
            assert metrics.run_count >= 0
            assert 0.0 <= metrics.success_rate <= 1.0

    def test_query_stage_metrics_empty_table_returns_empty_dict(self, tmp_path):
        """Lines 99-108: empty result set → returns empty dict."""
        db_path = str(tmp_path / "test_obs3.db")
        db_url = f"sqlite:///{db_path}"

        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE stage_executions ("
                    "  stage_name TEXT, workflow_name TEXT, "
                    "  status TEXT, duration_seconds REAL, started_at TEXT"
                    ")"
                )
            )
            conn.commit()

        analyzer = HistoryAnalyzer(db_url=db_url)
        result = analyzer.get_stage_metrics("empty_wf")
        assert result == {}


# ── Lines 145-147: _query_workflow_metrics with real data ─────────────────


class TestQueryWorkflowMetricsWithRealDB:
    """Covers lines 145-147: workflow metrics rows returned from DB."""

    def _create_workflow_executions_table(self, engine, rows=None):
        """Create workflow_executions table with test data."""
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS workflow_executions ("
                    "  workflow_name TEXT, "
                    "  status TEXT, "
                    "  duration_seconds REAL, "
                    "  started_at TEXT"
                    ")"
                )
            )
            if rows:
                for row in rows:
                    conn.execute(
                        text(
                            "INSERT INTO workflow_executions VALUES "
                            "(:wf, :status, :dur, datetime('now'))"
                        ).bindparams(**row)
                    )
            conn.commit()

    def test_query_returns_workflow_metrics_from_rows(self, tmp_path):
        """Lines 145-152: aggregate row returned → WorkflowMetrics populated."""
        db_path = str(tmp_path / "test_wf_obs.db")
        db_url = f"sqlite:///{db_path}"

        from sqlalchemy import create_engine

        engine = create_engine(db_url)
        self._create_workflow_executions_table(
            engine,
            rows=[
                {"wf": "my_wf", "status": "completed", "dur": 100.0},
                {"wf": "my_wf", "status": "completed", "dur": 200.0},
                {"wf": "my_wf", "status": "failed", "dur": 50.0},
            ],
        )

        analyzer = HistoryAnalyzer(db_url=db_url)
        result = analyzer.get_workflow_metrics("my_wf")

        assert isinstance(result, WorkflowMetrics)
        assert result.workflow_name == "my_wf"
        assert result.run_count == 3
        # success rate: 2 completed / 3 total
        assert abs(result.success_rate - (2.0 / 3.0)) < 0.01
        # avg_duration: (100 + 200 + 50) / 3
        assert abs(result.avg_duration - (350.0 / 3.0)) < 0.01

    def test_workflow_metrics_run_count_zero_returns_default(self, tmp_path):
        """Lines 145-147: empty table → run_count=0 branch → default returned."""
        db_path = str(tmp_path / "test_wf_obs2.db")
        db_url = f"sqlite:///{db_path}"

        from sqlalchemy import create_engine

        engine = create_engine(db_url)
        self._create_workflow_executions_table(engine, rows=[])

        analyzer = HistoryAnalyzer(db_url=db_url)
        result = analyzer.get_workflow_metrics("empty_wf")

        # Empty table → rows[0][2] is None or 0 → default returned
        assert result.workflow_name == "empty_wf"
        assert result.run_count == 0

    def test_workflow_metrics_other_workflow_not_returned(self, tmp_path):
        """Lines 145-152: query filters by workflow_name correctly."""
        db_path = str(tmp_path / "test_wf_obs3.db")
        db_url = f"sqlite:///{db_path}"

        from sqlalchemy import create_engine

        engine = create_engine(db_url)
        self._create_workflow_executions_table(
            engine,
            rows=[
                {"wf": "other_wf", "status": "completed", "dur": 100.0},
            ],
        )

        analyzer = HistoryAnalyzer(db_url=db_url)
        result = analyzer.get_workflow_metrics("my_wf")

        # No data for my_wf → default
        assert result.workflow_name == "my_wf"
        assert result.run_count == 0
