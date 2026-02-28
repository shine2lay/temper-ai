"""Tests for LearningDataService."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.learning.dashboard_service import (
    DEFAULT_PATTERN_LIMIT,
    DEFAULT_RUN_LIMIT,
    LearningDataService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pattern(
    id: str = "p1",
    pattern_type: str = "agent_performance",
    title: str = "Test Pattern",
    confidence: float = 0.9,
    impact_score: float = 0.7,
) -> MagicMock:
    p = MagicMock()
    p.id = id
    p.pattern_type = pattern_type
    p.title = title
    p.confidence = confidence
    p.impact_score = impact_score
    return p


def _make_run(
    id: str = "r1",
    status: str = "completed",
    patterns_found: int = 5,
    patterns_new: int = 2,
    novelty_score: float = 0.4,
    started_at: datetime | None = None,
) -> MagicMock:
    r = MagicMock()
    r.id = id
    r.status = status
    r.patterns_found = patterns_found
    r.patterns_new = patterns_new
    r.novelty_score = novelty_score
    r.started_at = started_at or datetime(2024, 6, 1, 12, 0, 0)
    return r


def _make_recommendation(
    id: str = "rec1",
    pattern_id: str = "p1",
    field_path: str = "llm.temperature",
    current_value: float = 0.7,
    recommended_value: float = 0.5,
    rationale: str = "Lower temp improves consistency",
) -> MagicMock:
    r = MagicMock()
    r.id = id
    r.pattern_id = pattern_id
    r.field_path = field_path
    r.current_value = current_value
    r.recommended_value = recommended_value
    r.rationale = rationale
    return r


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_store():
    store = MagicMock()
    store.list_patterns.return_value = []
    store.list_mining_runs.return_value = []
    store.list_recommendations.return_value = []
    return store


@pytest.fixture()
def mock_convergence():
    conv = MagicMock()
    conv.get_trend.return_value = {"slope": 0.01, "history": [0.8, 0.85, 0.9]}
    conv.is_converged.return_value = False
    return conv


@pytest.fixture()
def service(mock_store, mock_convergence):
    with patch(
        "temper_ai.learning.dashboard_service.ConvergenceDetector",
        return_value=mock_convergence,
    ):
        return LearningDataService(store=mock_store)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_default_pattern_limit_value(self):
        assert DEFAULT_PATTERN_LIMIT == 50

    def test_default_run_limit_value(self):
        assert DEFAULT_RUN_LIMIT == 20


# ---------------------------------------------------------------------------
# TestGetPatternSummary
# ---------------------------------------------------------------------------


class TestGetPatternSummary:
    def test_empty_store_returns_zero_total(self, service, mock_store):
        mock_store.list_patterns.return_value = []
        result = service.get_pattern_summary()
        assert result["total"] == 0
        assert result["counts_by_type"] == {}
        assert result["top_patterns"] == []

    def test_counts_by_type_aggregates_correctly(self, service, mock_store):
        patterns = [
            _make_pattern(id="p1", pattern_type="agent_performance"),
            _make_pattern(id="p2", pattern_type="agent_performance"),
            _make_pattern(id="p3", pattern_type="cost"),
        ]
        mock_store.list_patterns.return_value = patterns
        result = service.get_pattern_summary()
        assert result["counts_by_type"]["agent_performance"] == 2
        assert result["counts_by_type"]["cost"] == 1

    def test_total_matches_pattern_count(self, service, mock_store):
        patterns = [_make_pattern(id=f"p{i}") for i in range(7)]
        mock_store.list_patterns.return_value = patterns
        result = service.get_pattern_summary()
        assert result["total"] == 7

    def test_top_patterns_limited_to_ten(self, service, mock_store):
        patterns = [_make_pattern(id=f"p{i}") for i in range(15)]
        mock_store.list_patterns.return_value = patterns
        result = service.get_pattern_summary()
        assert len(result["top_patterns"]) == 10

    def test_top_pattern_has_required_fields(self, service, mock_store):
        p = _make_pattern(
            id="p1", title="My Pattern", confidence=0.95, impact_score=0.8
        )
        mock_store.list_patterns.return_value = [p]
        result = service.get_pattern_summary()
        top = result["top_patterns"][0]
        assert top["id"] == "p1"
        assert top["type"] == "agent_performance"
        assert top["title"] == "My Pattern"
        assert top["confidence"] == 0.95
        assert top["impact"] == 0.8

    def test_calls_list_patterns_with_correct_args(self, service, mock_store):
        service.get_pattern_summary()
        mock_store.list_patterns.assert_called_once_with(
            status=None, limit=DEFAULT_PATTERN_LIMIT
        )


# ---------------------------------------------------------------------------
# TestGetMiningHistory
# ---------------------------------------------------------------------------


class TestGetMiningHistory:
    def test_empty_returns_empty_list(self, service, mock_store):
        mock_store.list_mining_runs.return_value = []
        assert service.get_mining_history() == []

    def test_run_dict_has_required_fields(self, service, mock_store):
        run = _make_run(
            id="r1",
            status="completed",
            patterns_found=5,
            patterns_new=2,
            novelty_score=0.4,
        )
        mock_store.list_mining_runs.return_value = [run]
        result = service.get_mining_history()
        assert len(result) == 1
        entry = result[0]
        assert entry["id"] == "r1"
        assert entry["status"] == "completed"
        assert entry["patterns_found"] == 5
        assert entry["patterns_new"] == 2
        assert entry["novelty_score"] == 0.4

    def test_started_at_isoformat_in_result(self, service, mock_store):
        run = _make_run(started_at=datetime(2024, 3, 15, 8, 30, 0))
        mock_store.list_mining_runs.return_value = [run]
        result = service.get_mining_history()
        assert "2024-03-15" in result[0]["started_at"]

    def test_none_started_at_is_null(self, service, mock_store):
        run = _make_run()
        run.started_at = None
        mock_store.list_mining_runs.return_value = [run]
        result = service.get_mining_history()
        assert result[0]["started_at"] is None

    def test_calls_list_mining_runs_with_limit(self, service, mock_store):
        service.get_mining_history()
        mock_store.list_mining_runs.assert_called_once_with(limit=DEFAULT_RUN_LIMIT)

    def test_multiple_runs_preserved_in_order(self, service, mock_store):
        runs = [_make_run(id=f"r{i}") for i in range(3)]
        mock_store.list_mining_runs.return_value = runs
        result = service.get_mining_history()
        assert [r["id"] for r in result] == ["r0", "r1", "r2"]


# ---------------------------------------------------------------------------
# TestGetConvergenceData
# ---------------------------------------------------------------------------


class TestGetConvergenceData:
    def test_returns_trend_with_converged_key(self, service, mock_convergence):
        result = service.get_convergence_data()
        assert "converged" in result

    def test_converged_false_when_not_converged(self, service, mock_convergence):
        mock_convergence.is_converged.return_value = False
        result = service.get_convergence_data()
        assert result["converged"] is False

    def test_converged_true_when_converged(self, service, mock_convergence):
        mock_convergence.is_converged.return_value = True
        result = service.get_convergence_data()
        assert result["converged"] is True

    def test_passes_through_trend_data(self, service, mock_convergence):
        mock_convergence.get_trend.return_value = {"slope": 0.02, "history": [1, 2, 3]}
        result = service.get_convergence_data()
        assert result["slope"] == 0.02
        assert result["history"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# TestGetRecommendations
# ---------------------------------------------------------------------------


class TestGetRecommendations:
    def test_empty_returns_empty_list(self, service, mock_store):
        mock_store.list_recommendations.return_value = []
        assert service.get_recommendations() == []

    def test_recommendation_dict_has_required_fields(self, service, mock_store):
        rec = _make_recommendation(
            id="rec1",
            pattern_id="p1",
            field_path="llm.temperature",
            current_value=0.7,
            recommended_value=0.5,
            rationale="Lower temp improves consistency",
        )
        mock_store.list_recommendations.return_value = [rec]
        result = service.get_recommendations()
        assert len(result) == 1
        entry = result[0]
        assert entry["id"] == "rec1"
        assert entry["pattern_id"] == "p1"
        assert entry["field_path"] == "llm.temperature"
        assert entry["current_value"] == 0.7
        assert entry["recommended_value"] == 0.5
        assert entry["rationale"] == "Lower temp improves consistency"

    def test_calls_list_recommendations_with_pending_status(self, service, mock_store):
        service.get_recommendations()
        mock_store.list_recommendations.assert_called_once_with(status="pending")

    def test_multiple_recommendations_preserved(self, service, mock_store):
        recs = [_make_recommendation(id=f"rec{i}") for i in range(4)]
        mock_store.list_recommendations.return_value = recs
        result = service.get_recommendations()
        assert len(result) == 4
        assert result[0]["id"] == "rec0"
        assert result[3]["id"] == "rec3"
