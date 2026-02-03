"""
Tests for ImprovementDetector.

Tests the orchestration of problem detection and strategy selection.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock
from pathlib import Path

from src.self_improvement.detection import (
    ImprovementDetector,
    ImprovementProposal,
    NoBaselineError,
    InsufficientDataError,
    PerformanceProblem,
    ProblemType,
    ProblemSeverity,
)
from src.self_improvement.data_models import AgentPerformanceProfile
from src.self_improvement.performance_comparison import PerformanceComparison, MetricChange
from src.self_improvement.strategies.strategy import ImprovementStrategy


class MockStrategy(ImprovementStrategy):
    """Mock strategy for testing."""

    def __init__(self, name: str, applicable_to: list):
        self._name = name
        self._applicable_to = applicable_to

    @property
    def name(self) -> str:
        return self._name

    def generate_variants(self, current_config, patterns):
        return []

    def is_applicable(self, problem_type: str) -> bool:
        return problem_type in self._applicable_to

    def estimate_impact(self, problem_data: dict) -> float:
        return 0.15


class TestImprovementDetector:
    """Test suite for ImprovementDetector."""

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        return Mock()

    @pytest.fixture
    def mock_analyzer(self, mock_session):
        """Create mock PerformanceAnalyzer."""
        analyzer = Mock()
        analyzer.session = mock_session
        analyzer.baseline_storage_path = Path(".baselines")
        analyzer.list_baselines = Mock(return_value=["test_agent"])
        return analyzer

    @pytest.fixture
    def mock_problem_detector(self):
        """Create mock ProblemDetector."""
        detector = Mock()
        detector.config = Mock()
        detector.config.quality_relative_threshold = 0.10
        detector.config.cost_relative_threshold = 0.30
        detector.config.speed_relative_threshold = 0.50
        return detector

    @pytest.fixture
    def mock_strategy_registry(self):
        """Create mock StrategyRegistry with test strategies."""
        registry = Mock()

        # Register mock strategies
        strategies = [
            MockStrategy("prompt_tuning", ["quality_low"]),
            MockStrategy("model_selection", ["quality_low", "cost_high"]),
            MockStrategy("caching", ["cost_high", "speed_low"]),
        ]

        registry.get_all_strategies = Mock(return_value=strategies)
        registry.list_strategy_names = Mock(return_value=[s.name for s in strategies])

        return registry

    @pytest.fixture
    def detector(self, mock_session, mock_problem_detector, mock_strategy_registry):
        """Create ImprovementDetector with mocked dependencies."""
        detector = ImprovementDetector(
            session=mock_session,
            problem_detector=mock_problem_detector,
            strategy_registry=mock_strategy_registry,
        )
        return detector

    def create_profile(
        self,
        agent_name: str = "test_agent",
        total_executions: int = 100,
        success_rate: float = 0.85,
    ) -> AgentPerformanceProfile:
        """Helper to create performance profile."""
        window_end = datetime.now(timezone.utc)
        window_start = window_end - timedelta(days=7)

        return AgentPerformanceProfile(
            agent_name=agent_name,
            window_start=window_start,
            window_end=window_end,
            total_executions=total_executions,
            metrics={
                "success_rate": {"mean": success_rate},
                "duration_seconds": {"mean": 10.0},
                "cost_usd": {"mean": 0.50},
            },
        )

    def create_problem(
        self,
        problem_type: ProblemType = ProblemType.QUALITY_LOW,
        severity: ProblemSeverity = ProblemSeverity.MEDIUM,
    ) -> PerformanceProblem:
        """Helper to create performance problem."""
        return PerformanceProblem(
            problem_type=problem_type,
            severity=severity,
            agent_name="test_agent",
            metric_name="success_rate",
            baseline_value=0.85,
            current_value=0.70,
            degradation_pct=-0.176,
            threshold_used=0.10,
        )

    def test_detect_improvements_success(self, detector):
        """Test successful improvement detection flow."""
        # Setup mocks
        baseline = self.create_profile(success_rate=0.85)
        current = self.create_profile(success_rate=0.70)
        problem = self.create_problem()

        detector.analyzer = Mock()
        detector.analyzer.get_baseline = Mock(return_value=baseline)
        detector.analyzer.analyze_agent_performance = Mock(return_value=current)

        detector.problem_detector.detect_problems = Mock(return_value=[problem])

        # Execute
        proposals = detector.detect_improvements("test_agent")

        # Verify
        assert len(proposals) > 0
        assert all(isinstance(p, ImprovementProposal) for p in proposals)
        assert proposals[0].agent_name == "test_agent"
        assert proposals[0].problem.problem_type == ProblemType.QUALITY_LOW

    def test_detect_improvements_no_baseline(self, detector):
        """Test error when no baseline exists."""
        # Setup mocks
        detector.analyzer = Mock()
        detector.analyzer.get_baseline = Mock(return_value=None)

        # Execute & Verify
        with pytest.raises(NoBaselineError, match="No baseline found"):
            detector.detect_improvements("test_agent")

    @pytest.mark.skip(reason="Exception class name conflict - to be fixed")
    def test_detect_improvements_insufficient_data(self, detector):
        """Test error when insufficient current data."""
        from src.self_improvement.performance_analyzer import InsufficientDataError as AnalyzerInsufficientDataError
        from src.self_improvement.detection.improvement_detector import InsufficientDataError as DetectorInsufficientDataError

        # Setup mocks
        baseline = self.create_profile()
        detector.analyzer = Mock()
        detector.analyzer.get_baseline = Mock(return_value=baseline)
        detector.analyzer.analyze_agent_performance = Mock(
            side_effect=AnalyzerInsufficientDataError("Insufficient data")
        )

        # Execute & Verify
        with pytest.raises(DetectorInsufficientDataError):
            detector.detect_improvements("test_agent")

    def test_detect_improvements_no_problems(self, detector):
        """Test when no problems are detected."""
        # Setup mocks
        baseline = self.create_profile(success_rate=0.85)
        current = self.create_profile(success_rate=0.86)  # Improved

        detector.analyzer = Mock()
        detector.analyzer.get_baseline = Mock(return_value=baseline)
        detector.analyzer.analyze_agent_performance = Mock(return_value=current)

        detector.problem_detector.detect_problems = Mock(return_value=[])

        # Execute
        proposals = detector.detect_improvements("test_agent")

        # Verify
        assert len(proposals) == 0

    def test_detect_improvements_no_strategies(self, detector):
        """Test when no strategies are applicable."""
        # Setup mocks
        baseline = self.create_profile(success_rate=0.85)
        current = self.create_profile(success_rate=0.70)
        problem = self.create_problem(problem_type=ProblemType.SPEED_LOW)  # No strategy for this

        detector.analyzer = Mock()
        detector.analyzer.get_baseline = Mock(return_value=baseline)
        detector.analyzer.analyze_agent_performance = Mock(return_value=current)

        detector.problem_detector.detect_problems = Mock(return_value=[problem])

        # Override registry to return only quality strategies
        detector.strategy_registry.get_all_strategies = Mock(
            return_value=[MockStrategy("prompt_tuning", ["quality_low"])]
        )

        # Execute
        proposals = detector.detect_improvements("test_agent")

        # Verify
        assert len(proposals) == 0

    def test_proposal_priority_mapping(self, detector):
        """Test that severity correctly maps to priority."""
        # Setup mocks
        baseline = self.create_profile()
        current = self.create_profile(success_rate=0.70)

        detector.analyzer = Mock()
        detector.analyzer.get_baseline = Mock(return_value=baseline)
        detector.analyzer.analyze_agent_performance = Mock(return_value=current)

        # Create problems with different severities
        problems = [
            self.create_problem(severity=ProblemSeverity.CRITICAL),
            self.create_problem(severity=ProblemSeverity.HIGH),
            self.create_problem(severity=ProblemSeverity.MEDIUM),
            self.create_problem(severity=ProblemSeverity.LOW),
        ]

        detector.problem_detector.detect_problems = Mock(return_value=problems)

        # Execute
        proposals = detector.detect_improvements("test_agent")

        # Verify priority mapping
        # Should be sorted by priority (0=CRITICAL first)
        assert proposals[0].priority == 0  # CRITICAL
        assert proposals[-1].priority == 3  # LOW (if there are strategies for all)

    def test_health_check(self, detector):
        """Test health check returns component status."""
        # Execute
        health = detector.health_check()

        # Verify
        assert "status" in health
        assert health["status"] == "healthy"
        assert "components" in health
        assert "performance_analyzer" in health["components"]
        assert "problem_detector" in health["components"]
        assert "strategy_registry" in health["components"]


class TestImprovementProposal:
    """Test suite for ImprovementProposal."""

    def create_profile(self) -> AgentPerformanceProfile:
        """Helper to create performance profile."""
        window_end = datetime.now(timezone.utc)
        window_start = window_end - timedelta(days=7)

        return AgentPerformanceProfile(
            agent_name="test_agent",
            window_start=window_start,
            window_end=window_end,
            total_executions=100,
            metrics={"success_rate": {"mean": 0.85}},
        )

    def create_problem(self) -> PerformanceProblem:
        """Helper to create performance problem."""
        return PerformanceProblem(
            problem_type=ProblemType.QUALITY_LOW,
            severity=ProblemSeverity.MEDIUM,
            agent_name="test_agent",
            metric_name="success_rate",
            baseline_value=0.85,
            current_value=0.70,
            degradation_pct=-0.176,
            threshold_used=0.10,
        )

    def test_create_proposal(self):
        """Test creating an improvement proposal."""
        baseline = self.create_profile()
        current = self.create_profile()
        problem = self.create_problem()

        proposal = ImprovementProposal(
            proposal_id=ImprovementProposal.generate_id(),
            agent_name="test_agent",
            problem=problem,
            strategy_name="prompt_tuning",
            estimated_impact=0.15,
            baseline_profile=baseline,
            current_profile=current,
            priority=2,
        )

        assert proposal.agent_name == "test_agent"
        assert proposal.strategy_name == "prompt_tuning"
        assert proposal.estimated_impact == 0.15
        assert proposal.priority == 2

    def test_proposal_validation(self):
        """Test proposal validation."""
        baseline = self.create_profile()
        current = self.create_profile()
        problem = self.create_problem()

        # Invalid estimated_impact
        with pytest.raises(ValueError, match="estimated_impact must be"):
            ImprovementProposal(
                proposal_id="test",
                agent_name="test_agent",
                problem=problem,
                strategy_name="test",
                estimated_impact=1.5,  # Invalid
                baseline_profile=baseline,
                current_profile=current,
            )

        # Invalid priority
        with pytest.raises(ValueError, match="priority must be"):
            ImprovementProposal(
                proposal_id="test",
                agent_name="test_agent",
                problem=problem,
                strategy_name="test",
                estimated_impact=0.5,
                baseline_profile=baseline,
                current_profile=current,
                priority=10,  # Invalid
            )

    def test_proposal_summary(self):
        """Test proposal summary generation."""
        baseline = self.create_profile()
        current = self.create_profile()
        problem = self.create_problem()

        proposal = ImprovementProposal(
            proposal_id="test",
            agent_name="test_agent",
            problem=problem,
            strategy_name="prompt_tuning",
            estimated_impact=0.15,
            baseline_profile=baseline,
            current_profile=current,
            priority=1,  # HIGH
        )

        summary = proposal.get_summary()
        assert "HIGH priority" in summary
        assert "prompt_tuning" in summary
        assert "test_agent" in summary
        assert "quality_low" in summary
        assert "15%" in summary

    def test_proposal_serialization(self):
        """Test proposal to_dict and from_dict."""
        baseline = self.create_profile()
        current = self.create_profile()
        problem = self.create_problem()

        original = ImprovementProposal(
            proposal_id="test-id",
            agent_name="test_agent",
            problem=problem,
            strategy_name="prompt_tuning",
            estimated_impact=0.15,
            baseline_profile=baseline,
            current_profile=current,
            priority=2,
        )

        # Serialize
        proposal_dict = original.to_dict()

        # Deserialize
        restored = ImprovementProposal.from_dict(proposal_dict)

        # Verify
        assert restored.proposal_id == original.proposal_id
        assert restored.agent_name == original.agent_name
        assert restored.strategy_name == original.strategy_name
        assert restored.estimated_impact == original.estimated_impact
        assert restored.priority == original.priority
