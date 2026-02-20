"""Tests for history analyzer."""

import pytest

from temper_ai.lifecycle._schemas import StageMetrics, WorkflowMetrics
from temper_ai.lifecycle.history import HistoryAnalyzer


class TestHistoryAnalyzer:
    """Tests for HistoryAnalyzer."""

    def test_no_db_url_returns_empty_stage_metrics(self):
        analyzer = HistoryAnalyzer(db_url=None)
        result = analyzer.get_stage_metrics("test_workflow")
        assert result == {}

    def test_no_db_url_returns_default_workflow_metrics(self):
        analyzer = HistoryAnalyzer(db_url=None)
        result = analyzer.get_workflow_metrics("test_workflow")
        assert result.workflow_name == "test_workflow"
        assert result.run_count == 0
        assert result.success_rate == 1.0

    def test_invalid_db_returns_empty(self):
        analyzer = HistoryAnalyzer(db_url="sqlite:///nonexistent.db")
        result = analyzer.get_stage_metrics("test")
        assert result == {}

    def test_invalid_db_returns_default_workflow(self):
        analyzer = HistoryAnalyzer(db_url="sqlite:///nonexistent.db")
        result = analyzer.get_workflow_metrics("test")
        assert result.workflow_name == "test"

    def test_stage_metrics_with_in_memory_db(self):
        """In-memory DB has no tables, should return empty gracefully."""
        analyzer = HistoryAnalyzer(db_url="sqlite:///:memory:")
        result = analyzer.get_stage_metrics("test")
        assert result == {}

    def test_workflow_metrics_with_in_memory_db(self):
        analyzer = HistoryAnalyzer(db_url="sqlite:///:memory:")
        result = analyzer.get_workflow_metrics("test")
        assert isinstance(result, WorkflowMetrics)
        assert result.run_count == 0

    def test_lookback_parameter(self):
        analyzer = HistoryAnalyzer(db_url=None)
        result = analyzer.get_stage_metrics("test", lookback_hours=1)
        assert result == {}

    def test_custom_lookback_workflow(self):
        analyzer = HistoryAnalyzer(db_url=None)
        result = analyzer.get_workflow_metrics("test", lookback_hours=1)
        assert result.run_count == 0
