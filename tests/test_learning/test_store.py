"""Tests for LearningStore."""

import pytest

from temper_ai.learning.models import (
    PATTERN_AGENT_PERFORMANCE,
    PATTERN_COST,
    STATUS_APPLIED,
    STATUS_PENDING,
    LearnedPattern,
    MiningRun,
    TuneRecommendation,
)
from temper_ai.learning.store import LearningStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture()
def store() -> LearningStore:
    return LearningStore(database_url=MEMORY_DB)


class TestPatternCRUD:
    """Tests for pattern save/get/list."""

    def test_save_and_get(self, store: LearningStore) -> None:
        p = LearnedPattern(
            id="p1",
            pattern_type=PATTERN_AGENT_PERFORMANCE,
            title="Slow agent",
            description="Agent X is consistently slow",
            evidence={"avg_duration": 120},
            confidence=0.9,
            impact_score=0.7,
        )
        store.save_pattern(p)
        got = store.get_pattern("p1")
        assert got is not None
        assert got.title == "Slow agent"
        assert got.confidence == 0.9

    def test_get_missing(self, store: LearningStore) -> None:
        assert store.get_pattern("nonexistent") is None

    def test_list_by_type(self, store: LearningStore) -> None:
        for i, pt in enumerate([PATTERN_AGENT_PERFORMANCE, PATTERN_COST]):
            store.save_pattern(
                LearnedPattern(
                    id=f"p{i}",
                    pattern_type=pt,
                    title=f"Pattern {i}",
                    description="desc",
                    evidence={},
                    confidence=0.8,
                    impact_score=0.5,
                )
            )
        result = store.list_patterns(pattern_type=PATTERN_COST)
        assert len(result) == 1
        assert result[0].pattern_type == PATTERN_COST

    def test_list_all(self, store: LearningStore) -> None:
        store.save_pattern(
            LearnedPattern(
                id="p1",
                pattern_type=PATTERN_AGENT_PERFORMANCE,
                title="T",
                description="D",
                evidence={},
                confidence=0.5,
                impact_score=0.5,
            )
        )
        assert len(store.list_patterns()) == 1


class TestMiningRunCRUD:
    """Tests for mining run persistence."""

    def test_save_and_list(self, store: LearningStore) -> None:
        run = MiningRun(id="r1", patterns_found=5, patterns_new=2)
        store.save_mining_run(run)
        runs = store.list_mining_runs()
        assert len(runs) == 1
        assert runs[0].patterns_found == 5


class TestRecommendationCRUD:
    """Tests for recommendation persistence."""

    def test_save_and_list(self, store: LearningStore) -> None:
        rec = TuneRecommendation(
            id="t1",
            pattern_id="p1",
            config_path="agents/a.yaml",
            field_path="agent.model",
            current_value="llama3",
            recommended_value="qwen3",
            rationale="Better",
        )
        store.save_recommendation(rec)
        recs = store.list_recommendations(status=STATUS_PENDING)
        assert len(recs) == 1

    def test_update_status(self, store: LearningStore) -> None:
        rec = TuneRecommendation(
            id="t1",
            pattern_id="p1",
            config_path="a.yaml",
            field_path="f",
            current_value="v1",
            recommended_value="v2",
            rationale="r",
        )
        store.save_recommendation(rec)
        assert store.update_recommendation_status("t1", STATUS_APPLIED)
        recs = store.list_recommendations(status=STATUS_APPLIED)
        assert len(recs) == 1

    def test_update_missing(self, store: LearningStore) -> None:
        assert not store.update_recommendation_status("nonexistent", STATUS_APPLIED)
