"""Stage configuration and runtime state schemas."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from temper_ai.shared.constants.execution import DEFAULT_VERSION
from temper_ai.shared.constants.durations import SECONDS_PER_30_MINUTES
from temper_ai.shared.constants.limits import DEFAULT_MIN_ITEMS, SMALL_ITEM_LIMIT
from temper_ai.shared.constants.probabilities import (
    PROB_CRITICAL,
    PROB_HIGH,
    PROB_MEDIUM,
    PROB_NEAR_CERTAIN,
    PROB_VERY_HIGH,
)
from temper_ai.shared.constants.retries import DEFAULT_MAX_RETRIES, MIN_RETRY_ATTEMPTS
from temper_ai.shared.constants.convergence import (
    DEFAULT_CONVERGENCE_MAX_ITERATIONS,
    MAX_CONVERGENCE_ITERATIONS,
    MIN_CONVERGENCE_ITERATIONS,
)
from temper_ai.storage.schemas.agent_config import MetadataConfig


# ── Helper ──

def _validate_strategy_string(v: str) -> str:
    """Validate strategy is non-empty string.

    Args:
        v: Strategy string value

    Returns:
        Validated strategy string

    Raises:
        ValueError: If strategy is empty or whitespace-only
    """
    if not v or not v.strip():
        raise ValueError("strategy must be a non-empty string")
    return v


# ── Stage Configuration ──

class StageExecutionConfig(BaseModel):
    """Stage execution configuration."""
    agent_mode: Literal["parallel", "sequential", "adaptive"] = "parallel"
    timeout_seconds: int = Field(default=SECONDS_PER_30_MINUTES, gt=0)
    adaptive_config: Dict[str, Any] = Field(default_factory=dict)


class CollaborationConfig(BaseModel):
    """Collaboration configuration."""
    strategy: str  # Module reference
    max_rounds: int = Field(default=DEFAULT_MAX_RETRIES, gt=0)
    convergence_threshold: float = Field(default=PROB_VERY_HIGH, ge=0.0, le=1.0)
    config: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('strategy')
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        """Validate strategy is non-empty."""
        return _validate_strategy_string(v)

    # Dialogue-specific fields (Phase 1: Dialogue Orchestrator)
    # All fields optional for backward compatibility
    max_dialogue_rounds: Optional[int] = Field(
        default=DEFAULT_MAX_RETRIES,
        gt=0,
        description="Maximum number of dialogue rounds"
    )
    round_budget_usd: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Cost budget per dialogue session (USD)"
    )
    dialogue_mode: bool = Field(
        default=False,
        description="Enable multi-round dialogue (requires DialogueOrchestrator)"
    )
    roles: Optional[Dict[str, str]] = Field(
        default=None,
        description="Agent role assignments (e.g., {'agent1': 'proposer', 'agent2': 'critic'})"
    )
    context_window_rounds: Optional[int] = Field(
        default=MIN_RETRY_ATTEMPTS + 1,
        gt=0,
        description="Number of recent rounds to keep in full context"
    )


class ConflictResolutionConfig(BaseModel):
    """Conflict resolution configuration.

    Defines how conflicts between agents are resolved when they disagree.

    Attributes:
        strategy: Resolution strategy name (e.g., "highest_confidence",
                 "merit_weighted", "random_tiebreaker")
        metrics: List of merit metrics to consider for merit-weighted resolution
                (e.g., ["domain_merit", "overall_merit", "recent_performance"])
        metric_weights: Custom weights for each metric (defaults to equal if not specified)
        auto_resolve_threshold: Threshold for automatic resolution without escalation (0-1)
                               If weighted support >= threshold, auto-resolve
        escalation_threshold: Threshold below which to escalate to human (0-1)
                             If no decision has >= threshold support, escalate
        config: Additional strategy-specific configuration

    Example:
        >>> config = ConflictResolutionConfig(
        ...     strategy="merit_weighted",
        ...     metrics=["domain_merit", "overall_merit"],
        ...     metric_weights={"domain_merit": 0.7, "overall_merit": 0.3},
        ...     auto_resolve_threshold=0.85,
        ...     escalation_threshold=0.50
        ... )
    """
    strategy: str  # Module reference (e.g., "HighestConfidenceResolver")
    metrics: List[str] = Field(
        default_factory=lambda: ["confidence"],
        description="Metrics to consider for resolution (for merit-weighted)"
    )
    metric_weights: Dict[str, float] = Field(
        default_factory=dict,
        description="Custom weights for metrics (defaults to equal weights)"
    )
    auto_resolve_threshold: float = Field(
        default=PROB_CRITICAL,
        ge=0.0,
        le=1.0,
        description="Auto-resolve if winning decision has >= this weighted support"
    )
    escalation_threshold: float = Field(
        default=PROB_MEDIUM,
        ge=0.0,
        le=1.0,
        description="Escalate if no decision has >= this support"
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional strategy-specific configuration"
    )

    @field_validator('strategy')
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        """Validate strategy is non-empty."""
        return _validate_strategy_string(v)

    @model_validator(mode='after')
    def validate_thresholds(self) -> 'ConflictResolutionConfig':
        """Ensure escalation_threshold <= auto_resolve_threshold."""
        if self.escalation_threshold > self.auto_resolve_threshold:
            raise ValueError(
                f"escalation_threshold ({self.escalation_threshold}) must be <= "
                f"auto_resolve_threshold ({self.auto_resolve_threshold})"
            )
        return self

    @model_validator(mode='after')
    def validate_metric_weights(self) -> 'ConflictResolutionConfig':
        """Validate metric weights are non-negative and sum to reasonable range."""
        if self.metric_weights:
            # Check for negative weights
            for metric, weight in self.metric_weights.items():
                if weight < 0:
                    raise ValueError(
                        f"metric_weights['{metric}'] = {weight} is negative. "
                        f"All weights must be >= 0"
                    )

            # Check total weight is positive
            total_weight = sum(self.metric_weights.values())
            if total_weight <= 0:
                raise ValueError("Sum of metric_weights must be positive")
            # Weights don't sum to 1.0, they'll be normalized at runtime
            # (no action needed at validation time)
        return self


class ConvergenceConfig(BaseModel):
    """Configuration for convergence-based stage re-execution."""

    enabled: bool = False
    max_iterations: int = Field(
        default=DEFAULT_CONVERGENCE_MAX_ITERATIONS,
        ge=MIN_CONVERGENCE_ITERATIONS,
        le=MAX_CONVERGENCE_ITERATIONS,
    )
    similarity_threshold: float = Field(
        default=PROB_NEAR_CERTAIN,
        ge=0.0,
        le=1.0,
    )
    method: Literal["exact_hash", "semantic"] = "exact_hash"


class StageSafetyConfig(BaseModel):
    """Stage safety configuration."""
    mode: Literal["execute", "dry_run", "require_approval"] = "execute"
    dry_run_first: bool = False
    require_approval: bool = False
    approval_required_when: List[Dict[str, Any]] = Field(default_factory=list)


class StageErrorHandlingConfig(BaseModel):
    """Stage error handling configuration."""
    on_agent_failure: Literal["halt_stage", "retry_agent", "skip_agent", "continue_with_remaining"] = "continue_with_remaining"
    min_successful_agents: int = Field(default=DEFAULT_MIN_ITEMS, gt=0)
    fallback_strategy: Optional[str] = None
    retry_failed_agents: bool = True
    max_agent_retries: int = Field(default=MIN_RETRY_ATTEMPTS + 1, ge=0)


class QualityGatesConfig(BaseModel):
    """Quality gates configuration."""
    enabled: bool = False  # Disabled by default for backward compatibility
    min_confidence: float = Field(default=PROB_HIGH, ge=0.0, le=1.0)
    min_findings: int = Field(default=SMALL_ITEM_LIMIT, ge=0)
    require_citations: bool = True
    on_failure: Literal["retry_stage", "escalate", "proceed_with_warning"] = "retry_stage"
    max_retries: int = Field(default=MIN_RETRY_ATTEMPTS + 1, ge=0)


class StageConfigInner(BaseModel):
    """Inner stage configuration fields."""
    name: str
    description: str
    version: str = DEFAULT_VERSION
    agents: List[str]
    inputs: Optional[Dict[str, Any]] = None
    outputs: Dict[str, Any] = Field(default_factory=dict)
    execution: StageExecutionConfig = Field(default_factory=StageExecutionConfig)
    collaboration: Optional[CollaborationConfig] = None
    conflict_resolution: Optional[ConflictResolutionConfig] = None
    safety: StageSafetyConfig = Field(default_factory=StageSafetyConfig)
    error_handling: StageErrorHandlingConfig = Field(default_factory=StageErrorHandlingConfig)
    quality_gates: QualityGatesConfig = Field(default_factory=QualityGatesConfig)
    convergence: Optional[ConvergenceConfig] = None
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)

    @field_validator('agents')
    @classmethod
    def validate_agents(cls, v: List[str]) -> List[str]:
        """Validate agent configuration list."""
        if not v:
            raise ValueError("At least one agent must be specified")
        return v


class StageConfig(BaseModel):
    """Stage configuration schema."""
    stage: StageConfigInner
    schema_version: str = Field(
        default="1.0",
        description="Schema version for backward compatibility and migrations"
    )


# ── Runtime State Models (M3) ──

class AgentMetrics(BaseModel):
    """Metrics for a single agent execution."""
    tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    tool_calls: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)


class AggregateMetrics(BaseModel):
    """Aggregate metrics across all agents in a stage."""
    total_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    total_duration_seconds: float = Field(default=0.0, ge=0.0)
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    num_agents: int = Field(default=0, ge=0)
    num_successful: int = Field(default=0, ge=0)
    num_failed: int = Field(default=0, ge=0)


class MultiAgentStageState(BaseModel):
    """State tracking for multi-agent stage execution (M3)."""
    agent_outputs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    agent_statuses: Dict[str, Literal["success", "failed"]] = Field(default_factory=dict)
    agent_metrics: Dict[str, AgentMetrics] = Field(default_factory=dict)
    aggregate_metrics: AggregateMetrics = Field(default_factory=AggregateMetrics)
    errors: Dict[str, str] = Field(default_factory=dict)
    min_successful_agents: int = Field(default=1, gt=0)
