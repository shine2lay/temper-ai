"""Recommendation engine — converts patterns to actionable config changes."""

import uuid

from temper_ai.learning.models import (
    PATTERN_AGENT_PERFORMANCE,
    PATTERN_COLLABORATION,
    PATTERN_COST,
    PATTERN_FAILURE,
    PATTERN_MODEL_EFFECTIVENESS,
    STATUS_ACTIVE,
    LearnedPattern,
    TuneRecommendation,
)
from temper_ai.learning.store import LearningStore

DEFAULT_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_PATTERN_LIMIT = 100
_CONFIG_PATH_AGENTS = "agents/"
_CONFIG_PATH_STAGES = "stages/"


class RecommendationEngine:
    """Converts learned patterns to actionable config-change recommendations."""

    def __init__(self, store: LearningStore) -> None:
        self.store = store

    def generate_recommendations(
        self, min_confidence: float = DEFAULT_CONFIDENCE_THRESHOLD
    ) -> list[TuneRecommendation]:
        """Generate recommendations from active patterns above confidence threshold."""
        patterns = self.store.list_patterns(
            status=STATUS_ACTIVE, limit=DEFAULT_PATTERN_LIMIT
        )
        recs: list[TuneRecommendation] = []
        for p in patterns:
            if p.confidence < min_confidence:
                continue
            recs.extend(_pattern_to_recommendations(p))
        for rec in recs:
            self.store.save_recommendation(rec)
        return recs


def _pattern_to_recommendations(pattern: LearnedPattern) -> list[TuneRecommendation]:
    """Map a pattern to zero or more config-change recommendations."""
    handlers = {
        PATTERN_MODEL_EFFECTIVENESS: _recommend_model_change,
        PATTERN_AGENT_PERFORMANCE: _recommend_agent_tuning,
        PATTERN_COST: _recommend_cost_reduction,
        PATTERN_FAILURE: _recommend_error_handling,
        PATTERN_COLLABORATION: _recommend_debate_tuning,
    }
    handler = handlers.get(pattern.pattern_type)
    if handler is None:
        return []
    return handler(pattern)


def _recommend_model_change(p: LearnedPattern) -> list[TuneRecommendation]:
    """Recommend model switch for model_effectiveness patterns."""
    if "High error" not in p.title:
        return []
    model = p.evidence.get(
        "model", p.title.split(": ")[-1] if ": " in p.title else "unknown"
    )
    return [
        TuneRecommendation(
            id=uuid.uuid4().hex,
            pattern_id=p.id,
            config_path=_CONFIG_PATH_AGENTS,
            field_path="agent.model",
            current_value=model,
            recommended_value="(alternative model)",
            rationale=p.description,
        )
    ]


def _recommend_agent_tuning(p: LearnedPattern) -> list[TuneRecommendation]:
    """Recommend timeout/retry changes for agent performance patterns."""
    if "Slow" in p.title:
        return [
            TuneRecommendation(
                id=uuid.uuid4().hex,
                pattern_id=p.id,
                config_path=_CONFIG_PATH_AGENTS,
                field_path="agent.timeout",
                current_value="600",
                recommended_value="1200",
                rationale=p.description,
            )
        ]
    return []


def _recommend_cost_reduction(p: LearnedPattern) -> list[TuneRecommendation]:
    """Recommend cost-saving changes."""
    return [
        TuneRecommendation(
            id=uuid.uuid4().hex,
            pattern_id=p.id,
            config_path=_CONFIG_PATH_AGENTS,
            field_path="agent.max_tokens",
            current_value="4096",
            recommended_value="2048",
            rationale=p.description,
        )
    ]


def _recommend_error_handling(p: LearnedPattern) -> list[TuneRecommendation]:
    """Recommend error handling improvements."""
    classification = p.evidence.get("classification", "unknown")
    if classification == "transient":
        return [
            TuneRecommendation(
                id=uuid.uuid4().hex,
                pattern_id=p.id,
                config_path=_CONFIG_PATH_AGENTS,
                field_path="agent.max_retries",
                current_value="1",
                recommended_value="3",
                rationale=p.description,
            )
        ]
    return []


def _recommend_debate_tuning(p: LearnedPattern) -> list[TuneRecommendation]:
    """Recommend debate round reduction."""
    if "Unresolved" in p.title or "Slow consensus" in p.title:
        return [
            TuneRecommendation(
                id=uuid.uuid4().hex,
                pattern_id=p.id,
                config_path=_CONFIG_PATH_STAGES,
                field_path="stage.max_debate_rounds",
                current_value="5",
                recommended_value="3",
                rationale=p.description,
            )
        ]
    return []
