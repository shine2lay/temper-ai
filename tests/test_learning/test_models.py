"""Tests for learning models."""

from temper_ai.learning.models import (
    ALL_PATTERN_TYPES,
    PATTERN_AGENT_PERFORMANCE,
    STATUS_ACTIVE,
    STATUS_PENDING,
    STATUS_RUNNING,
    LearnedPattern,
    MiningRun,
    TuneRecommendation,
)


class TestLearnedPattern:
    """Tests for LearnedPattern model."""

    def test_defaults(self) -> None:
        p = LearnedPattern(
            id="p1",
            pattern_type=PATTERN_AGENT_PERFORMANCE,
            title="Slow agent",
            description="Agent X is slow",
            evidence={"runs": 5},
            confidence=0.85,
            impact_score=0.6,
        )
        assert p.status == STATUS_ACTIVE
        assert p.source_workflow_ids == []
        assert p.recommendation is None
        assert p.created_at is not None

    def test_pattern_type_values(self) -> None:
        assert len(ALL_PATTERN_TYPES) == 5  # noqa
        assert PATTERN_AGENT_PERFORMANCE in ALL_PATTERN_TYPES


class TestMiningRun:
    """Tests for MiningRun model."""

    def test_defaults(self) -> None:
        run = MiningRun(id="r1")
        assert run.status == STATUS_RUNNING
        assert run.patterns_found == 0
        assert run.patterns_new == 0
        assert run.novelty_score == 0.0
        assert run.miner_stats == {}


class TestTuneRecommendation:
    """Tests for TuneRecommendation model."""

    def test_defaults(self) -> None:
        rec = TuneRecommendation(
            id="t1",
            pattern_id="p1",
            config_path="agents/researcher.yaml",
            field_path="agent.model",
            current_value="llama3",
            recommended_value="qwen3",
            rationale="Better performance",
        )
        assert rec.status == STATUS_PENDING
        assert rec.created_at is not None
