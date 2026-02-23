"""Tests for RecommendationEngine."""

import pytest

from temper_ai.learning.models import (
    PATTERN_AGENT_PERFORMANCE,
    PATTERN_COLLABORATION,
    PATTERN_COST,
    PATTERN_FAILURE,
    PATTERN_MODEL_EFFECTIVENESS,
    LearnedPattern,
)
from temper_ai.learning.recommender import RecommendationEngine
from temper_ai.learning.store import LearningStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture()
def store() -> LearningStore:
    return LearningStore(database_url=MEMORY_DB)


def _save_pattern(
    store: LearningStore, ptype: str, title: str, confidence: float = 0.9
) -> str:
    p = LearnedPattern(
        id=f"p-{title}",
        pattern_type=ptype,
        title=title,
        description=f"Description of {title}",
        evidence={"classification": "transient"},
        confidence=confidence,
        impact_score=0.5,
    )
    store.save_pattern(p)
    return p.id


class TestRecommendationEngine:
    def test_model_effectiveness_recommendation(self, store: LearningStore) -> None:
        _save_pattern(store, PATTERN_MODEL_EFFECTIVENESS, "High error rate: gpt-4")
        engine = RecommendationEngine(store)
        recs = engine.generate_recommendations()
        assert len(recs) >= 1
        assert recs[0].field_path == "agent.model"

    def test_agent_performance_slow(self, store: LearningStore) -> None:
        _save_pattern(store, PATTERN_AGENT_PERFORMANCE, "Slow agent: researcher")
        recs = RecommendationEngine(store).generate_recommendations()
        assert len(recs) == 1
        assert recs[0].field_path == "agent.timeout"

    def test_cost_recommendation(self, store: LearningStore) -> None:
        _save_pattern(store, PATTERN_COST, "Cost-dominant agent: abc123")
        recs = RecommendationEngine(store).generate_recommendations()
        assert len(recs) == 1
        assert recs[0].field_path == "agent.max_tokens"

    def test_failure_recommendation_transient(self, store: LearningStore) -> None:
        _save_pattern(store, PATTERN_FAILURE, "Recurring error: Timeout")
        recs = RecommendationEngine(store).generate_recommendations()
        assert len(recs) == 1
        assert recs[0].field_path == "agent.max_retries"

    def test_collaboration_recommendation(self, store: LearningStore) -> None:
        _save_pattern(store, PATTERN_COLLABORATION, "Unresolved debate: stage-1")
        recs = RecommendationEngine(store).generate_recommendations()
        assert len(recs) == 1
        assert "debate" in recs[0].field_path

    def test_confidence_filter(self, store: LearningStore) -> None:
        _save_pattern(store, PATTERN_COST, "Low confidence", confidence=0.3)
        recs = RecommendationEngine(store).generate_recommendations(min_confidence=0.7)
        assert len(recs) == 0

    def test_persists_recommendations(self, store: LearningStore) -> None:
        _save_pattern(store, PATTERN_COST, "Cost-dominant agent: xyz")
        RecommendationEngine(store).generate_recommendations()
        recs = store.list_recommendations(status="pending")
        assert len(recs) == 1
