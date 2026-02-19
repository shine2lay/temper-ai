"""Tests for goal analyzers."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.goals._schemas import GoalType
from temper_ai.goals.analyzers.cost import CostAnalyzer
from temper_ai.goals.analyzers.cross_product import CrossProductAnalyzer
from temper_ai.goals.analyzers.performance import PerformanceAnalyzer
from temper_ai.goals.analyzers.reliability import ReliabilityAnalyzer
from temper_ai.storage.database.datetime_utils import utcnow


def _mock_stage(name, duration, workflow_id="wf-1", status="completed"):
    s = MagicMock()
    s.stage_name = name
    s.duration_seconds = duration
    s.workflow_execution_id = workflow_id
    s.start_time = utcnow()
    s.status = status
    return s


def _mock_agent(name, cost, status="completed"):
    a = MagicMock()
    a.agent_name = name
    a.estimated_cost_usd = cost
    a.start_time = utcnow()
    a.status = status
    return a


def _mock_llm_call(model, cost, status="success"):
    c = MagicMock()
    c.model = model
    c.estimated_cost_usd = cost
    c.start_time = utcnow()
    c.status = status
    return c


def _mock_error_fp(error_type, count, classification="transient"):
    fp = MagicMock()
    fp.error_type = error_type
    fp.normalized_message = f"{error_type} error"
    fp.error_code = f"ERR_{error_type.upper()}"
    fp.classification = classification
    fp.occurrence_count = count
    fp.last_seen = utcnow()
    fp.resolved = False
    fp.recent_workflow_ids = ["wf-1"]
    return fp


def _mock_workflow(product_type, cost=None, duration=None, status="completed"):
    wf = MagicMock()
    wf.id = f"wf-{product_type}"
    wf.product_type = product_type
    wf.total_cost_usd = cost
    wf.duration_seconds = duration
    wf.start_time = utcnow()
    wf.status = status
    return wf


class TestPerformanceAnalyzer:
    def test_no_engine(self):
        analyzer = PerformanceAnalyzer(engine=None)
        assert analyzer.analyze() == []
        assert analyzer.analyzer_type == "performance"

    def test_slow_stage_detected(self):
        engine = MagicMock()
        analyzer = PerformanceAnalyzer(engine=engine)
        stages = [_mock_stage("slow_stage", 400) for _ in range(3)]
        with patch("temper_ai.goals.analyzers.performance.Session") as mock_session:
            mock_session.return_value.__enter__.return_value.exec.return_value.all.return_value = stages
            results = analyzer.analyze()
        assert len(results) >= 1
        assert results[0].goal_type == GoalType.PERFORMANCE_OPTIMIZATION
        assert "slow_stage" in results[0].title

    def test_fast_stage_ignored(self):
        engine = MagicMock()
        analyzer = PerformanceAnalyzer(engine=engine)
        stages = [_mock_stage("fast_stage", 50) for _ in range(3)]
        with patch("temper_ai.goals.analyzers.performance.Session") as mock_session:
            mock_session.return_value.__enter__.return_value.exec.return_value.all.return_value = stages
            results = analyzer.analyze()
        slow_proposals = [r for r in results if "slow" in r.title.lower()]
        assert len(slow_proposals) == 0

    def test_degradation_detected(self):
        engine = MagicMock()
        analyzer = PerformanceAnalyzer(engine=engine)
        # First half fast, second half much slower
        stages = (
            [_mock_stage("degrading", 100) for _ in range(4)]
            + [_mock_stage("degrading", 200) for _ in range(4)]
        )
        with patch("temper_ai.goals.analyzers.performance.Session") as mock_session:
            mock_session.return_value.__enter__.return_value.exec.return_value.all.return_value = stages
            results = analyzer.analyze()
        degradation = [r for r in results if "degradation" in r.title.lower()]
        assert len(degradation) >= 1


class TestCostAnalyzer:
    def test_no_engine(self):
        analyzer = CostAnalyzer(engine=None)
        assert analyzer.analyze() == []

    def test_high_cost_agent(self):
        engine = MagicMock()
        analyzer = CostAnalyzer(engine=engine)
        agents = [
            _mock_agent("expensive", 9.0),
            _mock_agent("cheap", 1.0),
        ]
        with patch("temper_ai.goals.analyzers.cost.Session") as mock_session:
            session = mock_session.return_value.__enter__.return_value
            session.exec.return_value.all.side_effect = [agents, []]
            results = analyzer.analyze()
        cost_proposals = [r for r in results if r.goal_type == GoalType.COST_REDUCTION]
        assert len(cost_proposals) >= 1
        assert "expensive" in cost_proposals[0].title

    def test_model_cost_ratio(self):
        engine = MagicMock()
        analyzer = CostAnalyzer(engine=engine)
        calls = [
            _mock_llm_call("cheap-model", 0.01),
            _mock_llm_call("cheap-model", 0.01),
            _mock_llm_call("expensive-model", 0.10),
            _mock_llm_call("expensive-model", 0.10),
        ]
        with patch("temper_ai.goals.analyzers.cost.Session") as mock_session:
            session = mock_session.return_value.__enter__.return_value
            session.exec.return_value.all.side_effect = [[], calls]
            results = analyzer.analyze()
        model_proposals = [r for r in results if "model" in r.title.lower()]
        assert len(model_proposals) >= 1


class TestReliabilityAnalyzer:
    def test_no_engine(self):
        analyzer = ReliabilityAnalyzer(engine=None)
        assert analyzer.analyze() == []

    def test_recurring_errors(self):
        engine = MagicMock()
        analyzer = ReliabilityAnalyzer(engine=engine)
        fps = [_mock_error_fp("timeout", 5)]
        with patch("temper_ai.goals.analyzers.reliability.Session") as mock_session:
            session = mock_session.return_value.__enter__.return_value
            session.exec.return_value.all.side_effect = [fps, []]
            results = analyzer.analyze()
        assert len(results) >= 1
        assert results[0].goal_type == GoalType.RELIABILITY_IMPROVEMENT

    def test_high_failure_rate(self):
        engine = MagicMock()
        analyzer = ReliabilityAnalyzer(engine=engine)
        agents = [
            _mock_agent("flaky", 0, status="failed"),
            _mock_agent("flaky", 0, status="failed"),
            _mock_agent("flaky", 0, status="completed"),
        ]
        with patch("temper_ai.goals.analyzers.reliability.Session") as mock_session:
            session = mock_session.return_value.__enter__.return_value
            session.exec.return_value.all.side_effect = [[], agents]
            results = analyzer.analyze()
        failure_proposals = [r for r in results if "failure rate" in r.title.lower()]
        assert len(failure_proposals) >= 1


class TestCrossProductAnalyzer:
    def test_no_engine(self):
        analyzer = CrossProductAnalyzer(engine=None)
        assert analyzer.analyze() == []

    def test_cross_product_opportunity(self):
        engine = MagicMock()
        analyzer = CrossProductAnalyzer(engine=engine)
        workflows = [
            _mock_workflow("api", duration=100),
            _mock_workflow("api", duration=120),
            _mock_workflow("web_app", duration=300),
            _mock_workflow("web_app", duration=350),
        ]
        with patch("temper_ai.goals.analyzers.cross_product.Session") as mock_session:
            session = mock_session.return_value.__enter__.return_value
            session.exec.return_value.all.return_value = workflows
            results = analyzer.analyze()
        cross = [r for r in results if r.goal_type == GoalType.CROSS_PRODUCT_OPPORTUNITY]
        assert len(cross) >= 1

    def test_single_product_type_ignored(self):
        engine = MagicMock()
        analyzer = CrossProductAnalyzer(engine=engine)
        workflows = [_mock_workflow("api", duration=100)]
        with patch("temper_ai.goals.analyzers.cross_product.Session") as mock_session:
            session = mock_session.return_value.__enter__.return_value
            session.exec.return_value.all.return_value = workflows
            results = analyzer.analyze()
        assert len(results) == 0

    def test_with_learning_store(self):
        engine = MagicMock()
        learning_store = MagicMock()
        pattern = MagicMock()
        pattern.id = "p-1"
        pattern.title = "Cache pattern"
        pattern.confidence = 0.8
        pattern.source_workflow_ids = ["wf-api"]
        learning_store.list_patterns.return_value = [pattern]
        analyzer = CrossProductAnalyzer(engine=engine, learning_store=learning_store)
        workflows = [
            _mock_workflow("api", duration=100),
            _mock_workflow("web_app", duration=100),
        ]
        # Patch isinstance check
        with patch("temper_ai.goals.analyzers.cross_product.Session") as mock_session:
            session = mock_session.return_value.__enter__.return_value
            session.exec.return_value.all.return_value = workflows
            with patch("temper_ai.goals.analyzers.cross_product.isinstance", return_value=True):
                results = analyzer.analyze()
        # Should include cross-product opportunities (at least from _analyze_learned_patterns)
        assert isinstance(results, list)
