"""Tests for AnalysisOrchestrator."""

from unittest.mock import MagicMock

import pytest

from src.goals.analysis_orchestrator import AnalysisOrchestrator
from src.goals.store import GoalStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture
def store():
    return GoalStore(database_url=MEMORY_DB)


class TestAnalysisOrchestrator:
    def test_run_analysis_success(self, store):
        orch = AnalysisOrchestrator(store=store)
        run = orch.run_analysis()
        assert run.status == "completed"
        assert run.proposals_generated == 0
        assert run.id.startswith("ar-")

    def test_run_analysis_records_run(self, store):
        orch = AnalysisOrchestrator(store=store)
        orch.run_analysis()
        runs = store.list_analysis_runs()
        assert len(runs) == 1

    def test_run_with_failing_analyzer(self, store):
        bad_analyzer = MagicMock()
        bad_analyzer.analyzer_type = "bad"
        bad_analyzer.analyze.side_effect = RuntimeError("crash")
        orch = AnalysisOrchestrator(store=store, analyzers=[bad_analyzer])
        run = orch.run_analysis()
        # Proposer catches per-analyzer errors, so orchestrator still succeeds
        assert run.status == "completed"

    def test_lookback_passed_through(self, store):
        analyzer = MagicMock()
        analyzer.analyzer_type = "test"
        analyzer.analyze.return_value = []
        orch = AnalysisOrchestrator(store=store, analyzers=[analyzer])
        orch.run_analysis(lookback_hours=72)
        analyzer.analyze.assert_called_once_with(lookback_hours=72)

    def test_completed_at_set(self, store):
        orch = AnalysisOrchestrator(store=store)
        run = orch.run_analysis()
        assert run.completed_at is not None
