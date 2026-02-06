"""
Unit and integration tests for PerformanceAnalyzer.

Tests cover:
- Successful performance analysis
- Error handling (insufficient data, invalid inputs)
- Metric aggregation correctness
- Batch analysis of multiple agents
- Baseline calculation
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.observability.models import AgentExecution, StageExecution, WorkflowExecution
from src.self_improvement.data_models import AgentPerformanceProfile
from src.self_improvement.performance_analyzer import (
    PerformanceAnalyzer,
    PerformanceDataError,
)


@pytest.fixture
def db_engine():
    """Create in-memory database engine."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(db_engine):
    """Create database session for testing."""
    with Session(db_engine) as session:
        yield session


def create_test_execution(
    session: Session,
    agent_name: str,
    hours_ago: int,
    status: str = "completed",
    duration: float = 10.0,
    cost: float = 0.5,
    tokens: int = 100
) -> AgentExecution:
    """Helper to create test agent execution."""
    now = datetime.now(timezone.utc)

    # Create workflow and stage first (required for foreign keys)
    workflow = WorkflowExecution(
        id=f"workflow-{agent_name}-{hours_ago}",
        workflow_name="test_workflow",  # Fixed: use workflow_name not name
        status=status,
        workflow_config_snapshot={}
    )
    session.add(workflow)

    stage = StageExecution(
        id=f"stage-{agent_name}-{hours_ago}",
        workflow_execution_id=workflow.id,
        stage_name="test_stage",  # Fixed: use stage_name not name
        status=status,
        stage_config_snapshot={}
    )
    session.add(stage)

    execution = AgentExecution(
        id=f"{agent_name}-{hours_ago}",
        stage_execution_id=stage.id,
        agent_name=agent_name,
        status=status,
        agent_config_snapshot={},
        start_time=now - timedelta(hours=hours_ago),
        end_time=now - timedelta(hours=hours_ago) + timedelta(seconds=duration),
        duration_seconds=duration,
        estimated_cost_usd=cost,
        total_tokens=tokens
    )
    session.add(execution)
    return execution


class TestPerformanceAnalyzerInit:
    """Test PerformanceAnalyzer initialization."""

    def test_init_with_session(self, session):
        """Test analyzer initializes with session."""
        analyzer = PerformanceAnalyzer(session)
        assert analyzer.session is session


class TestAnalyzeAgentPerformance:
    """Test analyze_agent_performance method."""

    def test_successful_analysis(self, session):
        """Test successful performance analysis with sufficient data."""
        # Create 50 executions
        for i in range(50):
            create_test_execution(
                session, "test_agent", hours_ago=i,
                duration=10.0 + i * 0.1, cost=0.5, tokens=100
            )
        session.commit()

        # Analyze
        analyzer = PerformanceAnalyzer(session)
        profile = analyzer.analyze_agent_performance("test_agent", window_hours=72)

        # Verify profile
        assert isinstance(profile, AgentPerformanceProfile)
        assert profile.agent_name == "test_agent"
        assert profile.total_executions >= 50
        assert profile.has_metric("success_rate")
        assert profile.has_metric("duration_seconds")
        assert profile.has_metric("cost_usd")
        assert profile.has_metric("total_tokens")

        # Verify success rate
        success_rate = profile.get_metric("success_rate", "mean")
        assert success_rate == 1.0  # All completed

        # Verify other metrics exist
        assert profile.get_metric("duration_seconds", "mean") is not None
        assert profile.get_metric("cost_usd", "mean") is not None
        assert profile.get_metric("total_tokens", "mean") is not None

    def test_insufficient_data_error(self, session):
        """Test error when too few executions."""
        # Create only 5 executions (less than default min_executions=10)
        for i in range(5):
            create_test_execution(session, "sparse_agent", hours_ago=i)
        session.commit()

        analyzer = PerformanceAnalyzer(session)

        with pytest.raises(PerformanceDataError) as exc_info:
            analyzer.analyze_agent_performance("sparse_agent", min_executions=10)

        assert "Insufficient data" in str(exc_info.value)
        assert "sparse_agent" in str(exc_info.value)
        assert "5 executions" in str(exc_info.value)

    def test_no_executions_error(self, session):
        """Test error when no executions exist."""
        analyzer = PerformanceAnalyzer(session)

        with pytest.raises(PerformanceDataError):
            analyzer.analyze_agent_performance("nonexistent_agent")

    def test_empty_agent_name_error(self, session):
        """Test error with empty agent name."""
        analyzer = PerformanceAnalyzer(session)

        with pytest.raises(ValueError, match="agent_name cannot be empty"):
            analyzer.analyze_agent_performance("")

        with pytest.raises(ValueError, match="agent_name cannot be empty"):
            analyzer.analyze_agent_performance("   ")

    def test_invalid_min_executions(self, session):
        """Test error with invalid min_executions."""
        analyzer = PerformanceAnalyzer(session)

        with pytest.raises(ValueError, match="min_executions must be >= 1"):
            analyzer.analyze_agent_performance("agent", min_executions=0)

        with pytest.raises(ValueError, match="min_executions must be >= 1"):
            analyzer.analyze_agent_performance("agent", min_executions=-5)

    def test_invalid_window_hours(self, session):
        """Test error with invalid window_hours."""
        analyzer = PerformanceAnalyzer(session)

        with pytest.raises(ValueError, match="window_hours must be >= 1"):
            analyzer.analyze_agent_performance("agent", window_hours=0)

    def test_invalid_time_window(self, session):
        """Test error when window_start >= window_end."""
        analyzer = PerformanceAnalyzer(session)
        now = datetime.now(timezone.utc)

        with pytest.raises(ValueError, match="window_start.*must be before window_end"):
            analyzer.analyze_agent_performance(
                "agent",
                window_start=now,
                window_end=now - timedelta(hours=1)
            )

    def test_success_rate_calculation(self, session):
        """Test success rate calculation with mixed status."""
        # Create 70 completed, 30 failed executions
        for i in range(70):
            create_test_execution(session, "mixed_agent", hours_ago=i, status="completed")
        for i in range(70, 100):
            create_test_execution(session, "mixed_agent", hours_ago=i, status="failed")
        session.commit()

        # Analyze without failed executions (default)
        analyzer = PerformanceAnalyzer(session)
        profile = analyzer.analyze_agent_performance("mixed_agent", window_hours=120)

        # Should only count completed executions
        assert profile.total_executions == 70
        assert profile.get_metric("success_rate", "mean") == 1.0

    def test_include_failed_executions(self, session):
        """Test including failed executions in analysis."""
        # Create 70 completed, 30 failed executions
        for i in range(70):
            create_test_execution(session, "mixed_agent", hours_ago=i, status="completed")
        for i in range(70, 100):
            create_test_execution(session, "mixed_agent", hours_ago=i, status="failed")
        session.commit()

        analyzer = PerformanceAnalyzer(session)
        profile = analyzer.analyze_agent_performance(
            "mixed_agent",
            window_hours=120,
            include_failed=True
        )

        # Should count all executions
        assert profile.total_executions == 100
        # Success rate should be 70/100 = 0.7
        assert profile.get_metric("success_rate", "mean") == 0.7

    def test_custom_time_window(self, session):
        """Test analysis with custom start/end times."""
        now = datetime.now(timezone.utc)

        # Create executions at different times
        for hours in [1, 2, 10, 20, 50]:
            create_test_execution(session, "time_agent", hours_ago=hours)
        session.commit()

        # Analyze only recent 5 hours
        analyzer = PerformanceAnalyzer(session)
        profile = analyzer.analyze_agent_performance(
            "time_agent",
            window_start=now - timedelta(hours=5),
            window_end=now,
            min_executions=1
        )

        # Should only count executions from last 5 hours (hours 1, 2)
        assert profile.total_executions == 2

    def test_metrics_aggregation(self, session):
        """Test that metrics are correctly aggregated."""
        # Create executions with varying metrics
        durations = [5.0, 10.0, 15.0, 20.0]
        costs = [0.1, 0.2, 0.3, 0.4]
        tokens = [50, 100, 150, 200]

        for i, (dur, cost, tok) in enumerate(zip(durations, costs, tokens)):
            create_test_execution(
                session, "metrics_agent", hours_ago=i,
                duration=dur, cost=cost, tokens=tok
            )
        session.commit()

        analyzer = PerformanceAnalyzer(session)
        profile = analyzer.analyze_agent_performance("metrics_agent", min_executions=4)

        # Verify averages
        avg_duration = profile.get_metric("duration_seconds", "mean")
        avg_cost = profile.get_metric("cost_usd", "mean")
        avg_tokens = profile.get_metric("total_tokens", "mean")

        assert avg_duration == pytest.approx(12.5)  # (5+10+15+20)/4
        assert avg_cost == pytest.approx(0.25)  # (0.1+0.2+0.3+0.4)/4
        assert avg_tokens == pytest.approx(125.0)  # (50+100+150+200)/4


class TestGetBaseline:
    """Test get_baseline method."""

    def test_baseline_with_sufficient_data(self, session):
        """Test baseline calculation with sufficient data."""
        # Create 100 executions over 30 days
        for i in range(100):
            hours_ago = i * 7  # Spread over ~30 days
            create_test_execution(session, "baseline_agent", hours_ago=hours_ago)
        session.commit()

        analyzer = PerformanceAnalyzer(session)
        baseline = analyzer.get_baseline("baseline_agent", window_days=30)

        assert baseline is not None
        assert baseline.agent_name == "baseline_agent"
        assert baseline.total_executions >= 50  # Default min for baseline

    def test_baseline_with_insufficient_data(self, session):
        """Test baseline returns None with insufficient data."""
        # Create only 10 executions (less than baseline min of 50)
        for i in range(10):
            create_test_execution(session, "sparse_agent", hours_ago=i * 24)
        session.commit()

        analyzer = PerformanceAnalyzer(session)
        baseline = analyzer.get_baseline("sparse_agent", window_days=30)

        assert baseline is None


class TestAnalyzeAllAgents:
    """Test analyze_all_agents method."""

    def test_analyze_multiple_agents(self, session):
        """Test batch analysis of multiple agents."""
        # Create executions for 3 agents
        for agent in ["agent1", "agent2", "agent3"]:
            for i in range(20):
                create_test_execution(session, agent, hours_ago=i)
        session.commit()

        analyzer = PerformanceAnalyzer(session)
        profiles = analyzer.analyze_all_agents(window_hours=24, min_executions=10)

        # Verify all agents analyzed
        assert len(profiles) == 3
        agent_names = {p.agent_name for p in profiles}
        assert agent_names == {"agent1", "agent2", "agent3"}

        # Verify each profile
        for profile in profiles:
            assert profile.total_executions >= 10
            assert profile.has_metric("success_rate")

    def test_analyze_skips_insufficient_data(self, session):
        """Test that agents with insufficient data are skipped."""
        # agent1: 20 executions (sufficient)
        for i in range(20):
            create_test_execution(session, "agent1", hours_ago=i)

        # agent2: 5 executions (insufficient)
        for i in range(5):
            create_test_execution(session, "agent2", hours_ago=i)

        session.commit()

        analyzer = PerformanceAnalyzer(session)
        profiles = analyzer.analyze_all_agents(min_executions=10)

        # Only agent1 should be included
        assert len(profiles) == 1
        assert profiles[0].agent_name == "agent1"

    def test_analyze_all_empty_result(self, session):
        """Test analyze_all_agents with no agents."""
        analyzer = PerformanceAnalyzer(session)
        profiles = analyzer.analyze_all_agents()

        assert profiles == []


class TestPerformanceAnalyzerIntegration:
    """Integration tests with realistic scenarios."""

    def test_weekly_performance_analysis(self, session):
        """Test typical weekly performance analysis workflow."""
        # Simulate 7 days of executions
        for day in range(7):
            for hour in range(24):
                hours_ago = day * 24 + hour
                create_test_execution(
                    session, "production_agent",
                    hours_ago=hours_ago,
                    duration=5.0 + (hour % 10) * 0.5,  # Varying duration
                    cost=0.1 + (hour % 5) * 0.05  # Varying cost
                )
        session.commit()

        # Analyze
        analyzer = PerformanceAnalyzer(session)
        profile = analyzer.analyze_agent_performance(
            "production_agent",
            window_hours=168  # 7 days
        )

        # Verify weekly profile
        assert profile.total_executions == 168
        assert profile.get_metric("success_rate", "mean") == 1.0
        assert 5.0 <= profile.get_metric("duration_seconds", "mean") <= 10.0
        assert 0.1 <= profile.get_metric("cost_usd", "mean") <= 0.3

    def test_comparison_workflow(self, session):
        """Test current vs baseline comparison workflow."""
        # Create baseline data (31-60 days ago, slower performance)
        for i in range(100):
            hours_ago = 744 + i * 5  # 31-60 days ago (spread out)
            create_test_execution(
                session, "improving_agent",
                hours_ago=hours_ago,
                duration=20.0  # Slower
            )

        # Create recent data (last 7 days, faster performance)
        for i in range(100):
            hours_ago = i  # Last 100 hours (~4 days)
            create_test_execution(
                session, "improving_agent",
                hours_ago=hours_ago,
                duration=10.0  # Faster
            )

        session.commit()

        # Get baseline (30 days ending 7 days ago) and current (last 7 days)
        analyzer = PerformanceAnalyzer(session)

        # Baseline: 31-60 days ago (should have slower duration=20.0)
        now = datetime.now(timezone.utc)
        baseline = analyzer.analyze_agent_performance(
            "improving_agent",
            window_start=now - timedelta(days=60),
            window_end=now - timedelta(days=31),
            min_executions=50
        )

        # Current: last 7 days (should have faster duration=10.0)
        current = analyzer.analyze_agent_performance(
            "improving_agent",
            window_hours=168,
            min_executions=50
        )

        # Verify improvement
        assert baseline is not None
        assert current is not None
        assert current.get_metric("duration_seconds", "mean") < baseline.get_metric("duration_seconds", "mean")


class TestPathTraversalProtection:
    """Test path traversal prevention in baseline storage methods."""

    def test_valid_agent_names_accepted(self, session, tmp_path):
        """Test that valid agent names pass validation."""
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path)
        valid_names = [
            "agent1",
            "myAgent",
            "code_review_agent",
            "test-agent-v2",
            "A",
            "a" * 64,  # Max length
        ]
        for name in valid_names:
            path = analyzer._validate_baseline_path(name)
            assert path.name == f"{name}_baseline.json"

    def test_path_traversal_payloads_rejected(self, session, tmp_path):
        """Test that path traversal payloads are rejected."""
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path)
        traversal_payloads = [
            "../../etc/passwd",
            "../../../tmp/evil",
            "..\\..\\windows\\system32",
            "./../../backdoor",
            "agent/../../../secret",
            "/etc/passwd",
            "agent/../../etc/shadow",
        ]
        for payload in traversal_payloads:
            with pytest.raises(ValueError):
                analyzer._validate_baseline_path(payload)

    def test_invalid_agent_name_formats(self, session, tmp_path):
        """Test that invalid formats are rejected."""
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path)
        invalid_names = [
            "",               # empty
            "1agent",         # starts with number
            "-agent",         # starts with hyphen
            "_agent",         # starts with underscore
            ".hidden",        # starts with dot
            "agent name",     # contains space
            "agent@host",     # special character
            "agent;rm -rf",   # injection attempt
            "a" * 65,         # too long (65 chars)
        ]
        for name in invalid_names:
            with pytest.raises(ValueError):
                analyzer._validate_baseline_path(name)

    def test_non_string_agent_name_rejected(self, session, tmp_path):
        """Test that non-string agent names are rejected."""
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path)
        for bad_input in [None, 123, [], {}]:
            with pytest.raises(ValueError, match="Invalid agent name"):
                analyzer._validate_baseline_path(bad_input)

    def test_store_baseline_validates_name(self, session, tmp_path):
        """Test that store_baseline rejects traversal payloads."""
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path)
        profile = AgentPerformanceProfile(
            agent_name="../../etc/passwd",
            window_start=datetime.now(timezone.utc) - timedelta(hours=1),
            window_end=datetime.now(timezone.utc),
            total_executions=10,
            metrics={"success_rate": {"mean": 1.0}},
        )
        with pytest.raises(ValueError):
            analyzer.store_baseline("../../etc/passwd", profile)

    def test_retrieve_baseline_validates_name(self, session, tmp_path):
        """Test that retrieve_baseline rejects traversal payloads."""
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path)
        with pytest.raises(ValueError):
            analyzer.retrieve_baseline("../../etc/passwd")

    def test_delete_baseline_validates_name(self, session, tmp_path):
        """Test that delete_baseline rejects traversal payloads."""
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path)
        with pytest.raises(ValueError):
            analyzer.delete_baseline("../../etc/passwd")

    def test_list_baselines_filters_invalid_names(self, session, tmp_path):
        """Test that list_baselines only returns valid agent names."""
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path)

        # Create files with valid and invalid names
        (tmp_path / "validAgent_baseline.json").write_text("{}")
        (tmp_path / "another-valid_baseline.json").write_text("{}")
        (tmp_path / "../../evil_baseline.json").write_text("{}")  # Won't actually traverse
        (tmp_path / "1invalid_baseline.json").write_text("{}")

        baselines = analyzer.list_baselines()
        assert "validAgent" in baselines
        assert "another-valid" in baselines
        # Invalid names should be filtered out
        assert "1invalid" not in baselines

    def test_symlink_rejected(self, session, tmp_path):
        """Test that symlinked baseline files are rejected."""
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path)

        # Create a symlink inside the baseline directory
        target = tmp_path / "real_file.json"
        target.write_text("{}")
        symlink = tmp_path / "evilAgent_baseline.json"
        symlink.symlink_to(target)

        with pytest.raises(ValueError, match="symlink detected"):
            analyzer._validate_baseline_path("evilAgent")

    def test_unicode_path_separators_rejected(self, session, tmp_path):
        """Test that Unicode path separators and lookalikes are rejected."""
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path)
        unicode_payloads = [
            "agent\uff0fetc",          # Full-width solidus U+FF0F
            "agent\u2215etc",          # Division slash U+2215
            "agent\u2044etc",          # Fraction slash U+2044
            "agent\u00f7etc",          # Division sign
            "agent\u0000etc",          # Null byte
            "agent\nname",             # Newline
            "agent\ttab",              # Tab
        ]
        for payload in unicode_payloads:
            with pytest.raises(ValueError):
                analyzer._validate_baseline_path(payload)

    def test_storage_path_symlink_rejected(self, session, tmp_path):
        """Test that symlinked storage directory is rejected."""
        real_dir = tmp_path / "real_baselines"
        real_dir.mkdir()
        symlink_dir = tmp_path / "symlinked_baselines"
        symlink_dir.symlink_to(real_dir)

        with pytest.raises(ValueError, match="must not be a symlink"):
            PerformanceAnalyzer(session, baseline_storage_path=symlink_dir)

    def test_baseline_storage_path_resolved(self, session, tmp_path):
        """Test that baseline_storage_path is resolved on init."""
        # Use a relative-looking path
        analyzer = PerformanceAnalyzer(session, baseline_storage_path=tmp_path / "sub" / ".." / "actual")
        expected = (tmp_path / "sub" / ".." / "actual").resolve()
        assert analyzer.baseline_storage_path == expected
