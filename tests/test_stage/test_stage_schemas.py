"""Tests for temper_ai/stage/_schemas.py.

Covers:
- _validate_strategy_string helper
- StageExecutionConfig, CollaborationConfig, ConflictResolutionConfig
- ConvergenceConfig, StageSafetyConfig, StageErrorHandlingConfig
- QualityGatesConfig, StageConfigInner, StageConfig
"""

import pytest
from pydantic import ValidationError

from temper_ai.stage._schemas import (
    DEFAULT_CONVERGENCE_MAX_ITERATIONS,
    MAX_CONVERGENCE_ITERATIONS,
    MIN_CONVERGENCE_ITERATIONS,
    CollaborationConfig,
    ConflictResolutionConfig,
    ConvergenceConfig,
    QualityGatesConfig,
    StageConfig,
    StageConfigInner,
    StageErrorHandlingConfig,
    StageExecutionConfig,
    StageSafetyConfig,
    _validate_strategy_string,
)


class TestValidateStrategyString:
    """Tests for _validate_strategy_string helper."""

    def test_valid_string(self):
        assert _validate_strategy_string("my_strategy") == "my_strategy"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _validate_strategy_string("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _validate_strategy_string("   ")


class TestStageExecutionConfig:
    """Tests for StageExecutionConfig defaults and constraints."""

    def test_defaults(self):
        config = StageExecutionConfig()
        assert config.agent_mode == "parallel"
        assert config.timeout_seconds > 0
        assert config.adaptive_config == {}

    def test_sequential_mode(self):
        config = StageExecutionConfig(agent_mode="sequential")
        assert config.agent_mode == "sequential"

    def test_adaptive_mode(self):
        config = StageExecutionConfig(agent_mode="adaptive")
        assert config.agent_mode == "adaptive"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValidationError):
            StageExecutionConfig(agent_mode="invalid")

    def test_timeout_zero_raises(self):
        with pytest.raises(ValidationError):
            StageExecutionConfig(timeout_seconds=0)


class TestCollaborationConfig:
    """Tests for CollaborationConfig."""

    def test_minimal_valid(self):
        config = CollaborationConfig(strategy="highest_confidence")
        assert config.strategy == "highest_confidence"
        assert config.max_rounds > 0

    def test_empty_strategy_raises(self):
        with pytest.raises(ValidationError):
            CollaborationConfig(strategy="")

    def test_convergence_threshold_bounds(self):
        config = CollaborationConfig(strategy="s", convergence_threshold=0.0)
        assert config.convergence_threshold == 0.0
        config = CollaborationConfig(strategy="s", convergence_threshold=1.0)
        assert config.convergence_threshold == 1.0

    def test_convergence_threshold_out_of_bounds(self):
        with pytest.raises(ValidationError):
            CollaborationConfig(strategy="s", convergence_threshold=1.1)

    def test_dialogue_fields(self):
        config = CollaborationConfig(
            strategy="debate",
            dialogue_mode=True,
            roles={"a1": "proposer", "a2": "critic"},
        )
        assert config.dialogue_mode is True
        assert config.roles == {"a1": "proposer", "a2": "critic"}


class TestConflictResolutionConfig:
    """Tests for ConflictResolutionConfig validators."""

    def test_minimal_valid(self):
        config = ConflictResolutionConfig(strategy="highest_confidence")
        assert config.strategy == "highest_confidence"

    def test_empty_strategy_raises(self):
        with pytest.raises(ValidationError):
            ConflictResolutionConfig(strategy="")

    def test_escalation_gt_auto_resolve_raises(self):
        """escalation_threshold must be <= auto_resolve_threshold."""
        with pytest.raises(ValidationError, match="escalation_threshold"):
            ConflictResolutionConfig(
                strategy="s",
                auto_resolve_threshold=0.5,
                escalation_threshold=0.8,
            )

    def test_equal_thresholds_valid(self):
        config = ConflictResolutionConfig(
            strategy="s",
            auto_resolve_threshold=0.7,
            escalation_threshold=0.7,
        )
        assert config.escalation_threshold == config.auto_resolve_threshold

    def test_negative_metric_weight_raises(self):
        with pytest.raises(ValidationError, match="negative"):
            ConflictResolutionConfig(
                strategy="s",
                metric_weights={"confidence": -0.5},
            )

    def test_zero_sum_weights_raises(self):
        with pytest.raises(ValidationError, match="positive"):
            ConflictResolutionConfig(
                strategy="s",
                metric_weights={"a": 0.0, "b": 0.0},
            )

    def test_valid_metric_weights(self):
        config = ConflictResolutionConfig(
            strategy="s",
            metric_weights={"domain_merit": 0.7, "overall_merit": 0.3},
        )
        assert config.metric_weights["domain_merit"] == 0.7


class TestConvergenceConfig:
    """Tests for ConvergenceConfig."""

    def test_defaults(self):
        config = ConvergenceConfig()
        assert config.enabled is False
        assert config.max_iterations == DEFAULT_CONVERGENCE_MAX_ITERATIONS
        assert config.method == "exact_hash"

    def test_max_iterations_bounds(self):
        config = ConvergenceConfig(max_iterations=MIN_CONVERGENCE_ITERATIONS)
        assert config.max_iterations == MIN_CONVERGENCE_ITERATIONS
        config = ConvergenceConfig(max_iterations=MAX_CONVERGENCE_ITERATIONS)
        assert config.max_iterations == MAX_CONVERGENCE_ITERATIONS

    def test_below_min_iterations_raises(self):
        with pytest.raises(ValidationError):
            ConvergenceConfig(max_iterations=1)

    def test_above_max_iterations_raises(self):
        with pytest.raises(ValidationError):
            ConvergenceConfig(max_iterations=MAX_CONVERGENCE_ITERATIONS + 1)

    def test_similarity_threshold_bounds(self):
        ConvergenceConfig(similarity_threshold=0.0)
        ConvergenceConfig(similarity_threshold=1.0)

    def test_method_literal(self):
        config = ConvergenceConfig(method="semantic")
        assert config.method == "semantic"


class TestStageSafetyConfig:
    """Tests for StageSafetyConfig."""

    def test_defaults(self):
        config = StageSafetyConfig()
        assert config.mode == "execute"
        assert config.dry_run_first is False
        assert config.require_approval is False

    def test_mode_literals(self):
        for mode in ["execute", "dry_run", "require_approval"]:
            config = StageSafetyConfig(mode=mode)
            assert config.mode == mode

    def test_invalid_mode_raises(self):
        with pytest.raises(ValidationError):
            StageSafetyConfig(mode="invalid")


class TestStageErrorHandlingConfig:
    """Tests for StageErrorHandlingConfig."""

    def test_defaults(self):
        config = StageErrorHandlingConfig()
        assert config.on_agent_failure == "continue_with_remaining"
        assert config.retry_failed_agents is True

    def test_agent_failure_literals(self):
        for policy in [
            "halt_stage",
            "retry_agent",
            "skip_agent",
            "continue_with_remaining",
        ]:
            config = StageErrorHandlingConfig(on_agent_failure=policy)
            assert config.on_agent_failure == policy

    def test_min_successful_agents_zero_raises(self):
        with pytest.raises(ValidationError):
            StageErrorHandlingConfig(min_successful_agents=0)


class TestQualityGatesConfig:
    """Tests for QualityGatesConfig."""

    def test_defaults(self):
        config = QualityGatesConfig()
        assert config.enabled is False
        assert config.require_citations is True

    def test_on_failure_literals(self):
        for action in ["retry_stage", "escalate", "proceed_with_warning"]:
            config = QualityGatesConfig(on_failure=action)
            assert config.on_failure == action

    def test_min_confidence_bounds(self):
        QualityGatesConfig(min_confidence=0.0)
        QualityGatesConfig(min_confidence=1.0)
        with pytest.raises(ValidationError):
            QualityGatesConfig(min_confidence=1.1)


class TestStageConfigInner:
    """Tests for StageConfigInner."""

    def test_minimal_valid(self):
        config = StageConfigInner(
            name="test_stage",
            description="A test stage",
            agents=["agent1"],
        )
        assert config.name == "test_stage"
        assert len(config.agents) == 1

    def test_empty_agents_raises(self):
        with pytest.raises(ValidationError, match="At least one agent"):
            StageConfigInner(
                name="test",
                description="test",
                agents=[],
            )

    def test_defaults(self):
        config = StageConfigInner(
            name="s",
            description="d",
            agents=["a1"],
        )
        assert config.execution.agent_mode == "parallel"
        assert config.collaboration is None
        assert config.convergence is None


class TestStageConfig:
    """Tests for StageConfig wrapper."""

    def test_wraps_inner(self):
        config = StageConfig(
            stage=StageConfigInner(
                name="s",
                description="d",
                agents=["a1"],
            )
        )
        assert config.stage.name == "s"
        assert config.schema_version == "1.0"
