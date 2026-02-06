"""
Tests for baseline storage and retrieval in PerformanceAnalyzer.
"""
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.self_improvement.data_models import AgentPerformanceProfile
from src.self_improvement.performance_analyzer import PerformanceAnalyzer


class TestBaselineStorage:
    """Test baseline storage and retrieval functionality."""

    @pytest.fixture
    def temp_baseline_dir(self):
        """Create a temporary directory for baseline storage."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        # Cleanup after test
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_profile(self):
        """Create a mock performance profile for testing."""
        window_end = datetime.now(timezone.utc)
        window_start = window_end - timedelta(days=30)

        return AgentPerformanceProfile(
            agent_name="test_agent",
            window_start=window_start,
            window_end=window_end,
            total_executions=100,
            metrics={
                "success_rate": {"mean": 0.95},
                "duration_seconds": {"mean": 42.5, "std": 8.5},
                "cost_usd": {"mean": 0.80, "std": 0.12},
            }
        )

    @pytest.fixture
    def analyzer(self, temp_baseline_dir):
        """Create analyzer with mock session and temp storage."""
        from unittest.mock import Mock
        mock_session = Mock()
        return PerformanceAnalyzer(
            session=mock_session,
            baseline_storage_path=temp_baseline_dir
        )

    def test_store_and_retrieve_baseline(self, analyzer, mock_profile):
        """Test storing and retrieving a baseline."""
        # Store baseline
        stored_profile = analyzer.store_baseline("test_agent", mock_profile)
        assert stored_profile.agent_name == "test_agent"
        assert stored_profile.profile_id is not None

        # Retrieve baseline
        retrieved_profile = analyzer.retrieve_baseline("test_agent")
        assert retrieved_profile is not None
        assert retrieved_profile.agent_name == "test_agent"
        assert retrieved_profile.total_executions == 100
        assert retrieved_profile.get_metric("success_rate", "mean") == 0.95

    def test_retrieve_nonexistent_baseline(self, analyzer):
        """Test retrieving a baseline that doesn't exist."""
        profile = analyzer.retrieve_baseline("nonexistent_agent")
        assert profile is None

    def test_delete_baseline(self, analyzer, mock_profile):
        """Test deleting a stored baseline."""
        # Store baseline
        analyzer.store_baseline("test_agent", mock_profile)

        # Verify it exists
        assert analyzer.retrieve_baseline("test_agent") is not None

        # Delete it
        result = analyzer.delete_baseline("test_agent")
        assert result is True

        # Verify it's gone
        assert analyzer.retrieve_baseline("test_agent") is None

    def test_delete_nonexistent_baseline(self, analyzer):
        """Test deleting a baseline that doesn't exist."""
        result = analyzer.delete_baseline("nonexistent_agent")
        assert result is False

    def test_list_baselines(self, analyzer, mock_profile):
        """Test listing all stored baselines."""
        # Initially empty
        assert analyzer.list_baselines() == []

        # Store a baseline (update agent name to match)
        mock_profile.agent_name = "agent1"
        analyzer.store_baseline("agent1", mock_profile)

        # Should show up in list
        baselines = analyzer.list_baselines()
        assert len(baselines) == 1
        assert "agent1" in baselines

        # Store another
        profile2 = AgentPerformanceProfile(
            agent_name="agent2",
            window_start=mock_profile.window_start,
            window_end=mock_profile.window_end,
            total_executions=50,
            metrics={"success_rate": {"mean": 0.85}}
        )
        analyzer.store_baseline("agent2", profile2)

        # Should show both
        baselines = analyzer.list_baselines()
        assert len(baselines) == 2
        assert "agent1" in baselines
        assert "agent2" in baselines
        # Should be sorted
        assert baselines == ["agent1", "agent2"]

    def test_get_baseline_uses_stored(self, analyzer, mock_profile):
        """Test that get_baseline() retrieves stored baseline."""
        # Store a baseline
        analyzer.store_baseline("test_agent", mock_profile)

        # get_baseline should retrieve the stored one
        baseline = analyzer.get_baseline("test_agent")
        assert baseline is not None
        assert baseline.agent_name == "test_agent"
        assert baseline.total_executions == 100

    def test_store_baseline_profile_id_generated(self, analyzer, mock_profile):
        """Test that profile_id is auto-generated if not present."""
        assert mock_profile.profile_id is None
        stored = analyzer.store_baseline("test_agent", mock_profile)
        assert stored.profile_id is not None

    def test_store_baseline_mismatched_agent_name(self, analyzer, mock_profile):
        """Test that storing with mismatched agent_name raises error."""
        with pytest.raises(ValueError, match="does not match"):
            analyzer.store_baseline("different_agent", mock_profile)

    def test_baseline_persistence(self, temp_baseline_dir, mock_profile):
        """Test that baselines persist across analyzer instances."""
        from unittest.mock import Mock

        # Create analyzer and store baseline
        mock_session1 = Mock()
        analyzer1 = PerformanceAnalyzer(
            session=mock_session1,
            baseline_storage_path=temp_baseline_dir
        )
        analyzer1.store_baseline("test_agent", mock_profile)

        # Create new analyzer instance with same storage path
        mock_session2 = Mock()
        analyzer2 = PerformanceAnalyzer(
            session=mock_session2,
            baseline_storage_path=temp_baseline_dir
        )

        # Should be able to retrieve baseline stored by first instance
        baseline = analyzer2.retrieve_baseline("test_agent")
        assert baseline is not None
        assert baseline.agent_name == "test_agent"
        assert baseline.total_executions == 100
