"""
Pydantic schemas for configuration validation.

Defines schemas for agents, stages, workflows, tools, and triggers.
All schemas validate against the YAML/JSON structure from TECHNICAL_SPECIFICATION.md.

Agent-related schemas (AgentConfig, InferenceConfig, etc.) are now
canonically defined in ``src.schemas.agent_config`` and re-exported here
for full backward compatibility.
"""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from src.constants.durations import (
    SECONDS_PER_5_MINUTES,
    SECONDS_PER_10_MINUTES,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    SECONDS_PER_WEEK,
)
from src.constants.limits import (
    DEFAULT_MIN_ITEMS,
    DEFAULT_QUEUE_SIZE,
    MEDIUM_ITEM_LIMIT,
    SMALL_ITEM_LIMIT,
    SMALL_QUEUE_SIZE,
)
from src.constants.probabilities import (
    PROB_CRITICAL,
    PROB_HIGH,
    PROB_MEDIUM,
    PROB_VERY_HIGH,
)
from src.constants.retries import DEFAULT_MAX_RETRIES, MIN_RETRY_ATTEMPTS

# ============================================
# AGENT CONFIGURATION SCHEMAS (re-exported from src.schemas.agent_config)
# ============================================
from src.schemas.agent_config import (  # noqa: E402, F401
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    MemoryConfig,
    MeritTrackingConfig,
    MetadataConfig,
    ObservabilityConfig,
    PromptConfig,
    RetryConfig,
    SafetyConfig,
    ToolReference,
)

# ============================================
# HELPER FUNCTIONS
# ============================================

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


# ============================================
# TOOL CONFIGURATION SCHEMAS
# ============================================

class SafetyCheck(BaseModel):
    """Safety check configuration."""
    name: str
    config: Dict[str, Any] = Field(default_factory=dict)


class RateLimits(BaseModel):
    """Rate limiting configuration."""
    max_calls_per_minute: int = Field(default=SMALL_QUEUE_SIZE, gt=0)
    max_calls_per_hour: int = Field(default=DEFAULT_QUEUE_SIZE, gt=0)
    max_concurrent_requests: int = Field(default=MEDIUM_ITEM_LIMIT, gt=0)
    cooldown_on_failure_seconds: int = Field(default=SECONDS_PER_MINUTE, ge=0)


class ToolErrorHandlingConfig(BaseModel):
    """Tool error handling configuration."""
    retry_on_status_codes: List[int] = Field(default_factory=list)
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0)
    backoff_strategy: str = "ExponentialBackoff"
    timeout_is_retry: bool = False


class ToolObservabilityConfig(BaseModel):
    """Tool observability configuration."""
    log_inputs: bool = True
    log_outputs: bool = True
    log_full_response: bool = False
    track_latency: bool = True
    track_success_rate: bool = True
    metrics: List[str] = Field(default_factory=list)


class ToolRequirements(BaseModel):
    """Tool requirements."""
    requires_network: bool = False
    requires_credentials: bool = False
    requires_sandbox: bool = False


class ToolConfigInner(BaseModel):
    """Inner tool configuration fields."""
    name: str
    description: str
    version: str = "1.0"
    category: Optional[str] = None
    implementation: str  # Python class path
    default_config: Dict[str, Any] = Field(default_factory=dict)
    safety_checks: List[Union[str, SafetyCheck]] = Field(default_factory=list)
    rate_limits: RateLimits = Field(default_factory=RateLimits)
    error_handling: ToolErrorHandlingConfig = Field(default_factory=ToolErrorHandlingConfig)
    observability: ToolObservabilityConfig = Field(default_factory=ToolObservabilityConfig)
    requirements: ToolRequirements = Field(default_factory=ToolRequirements)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)


class ToolConfig(BaseModel):
    """Tool configuration schema."""
    tool: ToolConfigInner


# ============================================
# STAGE CONFIGURATION SCHEMAS
# ============================================

class StageExecutionConfig(BaseModel):
    """Stage execution configuration."""
    agent_mode: Literal["parallel", "sequential", "adaptive"] = "parallel"
    timeout_seconds: int = Field(default=SECONDS_PER_10_MINUTES, gt=0)
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
    version: str = "1.0"
    agents: List[str]
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    execution: StageExecutionConfig = Field(default_factory=StageExecutionConfig)
    collaboration: Optional[CollaborationConfig] = None
    conflict_resolution: Optional[ConflictResolutionConfig] = None
    safety: StageSafetyConfig = Field(default_factory=StageSafetyConfig)
    error_handling: StageErrorHandlingConfig = Field(default_factory=StageErrorHandlingConfig)
    quality_gates: QualityGatesConfig = Field(default_factory=QualityGatesConfig)
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


# ============================================
# WORKFLOW CONFIGURATION SCHEMAS
# ============================================

class WorkflowStageReference(BaseModel):
    """Reference to a stage in a workflow."""
    name: str
    stage_ref: str
    depends_on: List[str] = Field(default_factory=list)
    optional: bool = False
    skip_if: Optional[str] = None
    conditional: bool = False
    condition: Optional[str] = None
    loops_back_to: Optional[str] = None
    max_loops: int = Field(default=MIN_RETRY_ATTEMPTS, gt=0)


class BudgetConfig(BaseModel):
    """Budget configuration."""
    max_cost_usd: Optional[float] = Field(default=None, ge=0)
    max_tokens: Optional[int] = Field(default=None, gt=0)
    action_on_exceed: Literal["halt", "continue", "notify"] = "halt"


class WorkflowConfigOptions(BaseModel):
    """Workflow configuration options."""
    max_iterations: int = Field(default=SMALL_ITEM_LIMIT, gt=0)
    convergence_detection: bool = False
    timeout_seconds: int = Field(default=SECONDS_PER_HOUR, gt=0)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)


class WorkflowSafetyConfig(BaseModel):
    """Workflow safety configuration."""
    composition_strategy: str = "MostRestrictive"
    global_mode: Literal["execute", "dry_run", "require_approval"] = "execute"
    approval_required_stages: List[str] = Field(default_factory=list)
    dry_run_stages: List[str] = Field(default_factory=list)
    custom_rules: List[Dict[str, Any]] = Field(default_factory=list)


class OptimizationConfig(BaseModel):
    """Optimization configuration."""
    current_phase: Literal["growth", "retention", "efficiency", "quality"] = "growth"
    primary_metric: str
    secondary_metrics: List[str] = Field(default_factory=list)
    thresholds: Dict[str, Dict[str, float]] = Field(default_factory=dict)


class WorkflowObservabilityConfig(BaseModel):
    """Workflow observability configuration."""
    console_mode: Literal["minimal", "standard", "verbose"] = "standard"
    trace_everything: bool = True
    export_format: List[str] = Field(default=["json", "sqlite"])
    generate_dag_visualization: bool = True
    waterfall_in_console: bool = True
    alert_on: List[str] = Field(default_factory=list)


class WorkflowErrorHandlingConfig(BaseModel):
    """Workflow error handling configuration."""
    on_stage_failure: Literal["halt", "skip", "retry"] = "halt"
    max_stage_retries: int = Field(default=MIN_RETRY_ATTEMPTS + 1, ge=0)
    escalation_policy: str  # Module reference
    enable_rollback: bool = True
    rollback_on: List[str] = Field(default_factory=list)


class WorkflowConfigInner(BaseModel):
    """Inner workflow configuration fields."""
    name: str
    description: str
    version: str = "1.0"
    product_type: Optional[Literal["web_app", "mobile_app", "api", "data_product"]] = None
    stages: List[WorkflowStageReference]
    config: WorkflowConfigOptions = Field(default_factory=WorkflowConfigOptions)
    safety: WorkflowSafetyConfig = Field(default_factory=WorkflowSafetyConfig)
    optimization: Optional[OptimizationConfig] = None
    observability: WorkflowObservabilityConfig = Field(default_factory=WorkflowObservabilityConfig)
    error_handling: WorkflowErrorHandlingConfig
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)

    @field_validator('stages')
    @classmethod
    def validate_stages(cls, v: List['WorkflowStageReference']) -> List['WorkflowStageReference']:
        """Validate workflow stage configuration."""
        if not v:
            raise ValueError("At least one stage must be specified")
        return v


class WorkflowConfig(BaseModel):
    """Workflow configuration schema."""
    workflow: WorkflowConfigInner
    schema_version: str = Field(
        default="1.0",
        description="Schema version for backward compatibility and migrations"
    )


# ============================================
# RUNTIME STATE MODELS (M3)
# ============================================

class AgentMetrics(BaseModel):
    """Metrics for a single agent execution.

    Tracks resource usage and performance metrics for observability
    and cost analysis.

    Attributes:
        tokens: Total tokens consumed (prompt + completion)
        cost_usd: Estimated cost in USD
        duration_seconds: Execution duration in seconds
        tool_calls: Number of tool calls made
        retries: Number of retries if agent failed initially
    """
    tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    tool_calls: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)


class AggregateMetrics(BaseModel):
    """Aggregate metrics across all agents in a stage.

    Provides rollup of resource usage for the entire stage execution.

    Attributes:
        total_tokens: Sum of tokens across all agents
        total_cost_usd: Sum of costs across all agents
        total_duration_seconds: Max duration (parallel) or sum (sequential)
        avg_confidence: Average confidence across successful agents
        num_agents: Total number of agents executed
        num_successful: Number of agents that succeeded
        num_failed: Number of agents that failed
    """
    total_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    total_duration_seconds: float = Field(default=0.0, ge=0.0)
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    num_agents: int = Field(default=0, ge=0)
    num_successful: int = Field(default=0, ge=0)
    num_failed: int = Field(default=0, ge=0)


class MultiAgentStageState(BaseModel):
    """State tracking for multi-agent stage execution (M3).

    This model defines the structure for tracking individual agent
    outputs, execution status, and metrics during parallel execution.
    Used for observability, debugging, and cost analysis.

    Attributes:
        agent_outputs: Dict mapping agent_name to output data
        agent_statuses: Dict mapping agent_name to status ("success"/"failed")
        agent_metrics: Dict mapping agent_name to AgentMetrics
        aggregate_metrics: Rollup metrics for the entire stage
        errors: Dict mapping agent_name to error message (if failed)
        min_successful_agents: Minimum agents required for stage success

    Example:
        >>> state = MultiAgentStageState(
        ...     agent_outputs={
        ...         "researcher": {"output": "findings...", "confidence": 0.9},
        ...         "analyst": {"output": "analysis...", "confidence": 0.85}
        ...     },
        ...     agent_statuses={
        ...         "researcher": "success",
        ...         "analyst": "success"
        ...     },
        ...     agent_metrics={
        ...         "researcher": AgentMetrics(tokens=1500, cost_usd=0.03, duration_seconds=5.2),
        ...         "analyst": AgentMetrics(tokens=2000, cost_usd=0.04, duration_seconds=6.1)
        ...     },
        ...     aggregate_metrics=AggregateMetrics(
        ...         total_tokens=3500,
        ...         total_cost_usd=0.07,
        ...         total_duration_seconds=6.1,  # Max of parallel executions
        ...         num_agents=2,
        ...         num_successful=2
        ...     )
        ... )
    """
    agent_outputs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    agent_statuses: Dict[str, Literal["success", "failed"]] = Field(default_factory=dict)
    agent_metrics: Dict[str, AgentMetrics] = Field(default_factory=dict)
    aggregate_metrics: AggregateMetrics = Field(default_factory=AggregateMetrics)
    errors: Dict[str, str] = Field(default_factory=dict)
    min_successful_agents: int = Field(default=1, gt=0)


# ============================================
# TRIGGER CONFIGURATION SCHEMAS
# ============================================

class EventSourceConfig(BaseModel):
    """Event source configuration."""
    type: Literal["message_queue", "webhook", "database_poll", "file_watch"]
    connection: Optional[str] = None
    queue_name: Optional[str] = None
    consumer_group: Optional[str] = None
    max_connections: int = Field(default=MEDIUM_ITEM_LIMIT, gt=0)
    reconnect_delay_seconds: int = Field(default=SMALL_ITEM_LIMIT, gt=0)


class EventFilterCondition(BaseModel):
    """Event filter condition."""
    field: str
    operator: Literal["in", "eq", "ne", "gt", "lt", "gte", "lte", "contains"]
    values: Optional[List[Any]] = None
    value: Optional[Any] = None


class EventFilter(BaseModel):
    """Event filter configuration."""
    event_type: str
    conditions: List[EventFilterCondition] = Field(default_factory=list)


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration."""
    max_parallel_executions: int = Field(default=SMALL_ITEM_LIMIT, gt=0)
    queue_when_busy: bool = True
    max_queue_size: int = Field(default=SMALL_QUEUE_SIZE, gt=0)
    deduplicate: bool = True
    dedup_window_seconds: int = Field(default=SECONDS_PER_5_MINUTES, gt=0)
    dedup_key: Optional[str] = None


class TriggerRetryConfig(BaseModel):
    """Retry configuration for triggers."""
    enabled: bool = True
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0)
    retry_delay_seconds: int = Field(default=SECONDS_PER_MINUTE, gt=0)
    exponential_backoff: bool = True


class TriggerMetadata(BaseModel):
    """Trigger metadata."""
    owner: Optional[str] = None
    alert_on_failure: bool = True
    alert_channels: List[str] = Field(default_factory=list)
    notify_on_completion: bool = False
    notification_channels: List[str] = Field(default_factory=list)


class EventTriggerInner(BaseModel):
    """Inner event trigger configuration."""
    name: str
    description: str
    type: Literal["EventTrigger"]
    source: EventSourceConfig
    filter: EventFilter
    workflow: str
    workflow_inputs: Dict[str, Any] = Field(default_factory=dict)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    retry: TriggerRetryConfig = Field(default_factory=TriggerRetryConfig)
    metadata: TriggerMetadata = Field(default_factory=TriggerMetadata)


class CronTriggerInner(BaseModel):
    """Inner cron trigger configuration."""
    name: str
    description: str
    type: Literal["CronTrigger"]
    schedule: str  # Cron format
    timezone: str = "UTC"
    skip_on_holiday: bool = True
    skip_if_recent_execution: bool = True
    min_hours_between_runs: int = Field(default=SECONDS_PER_WEEK // SECONDS_PER_HOUR, gt=0)
    workflow: str
    workflow_inputs: Dict[str, Any] = Field(default_factory=dict)
    metadata: TriggerMetadata = Field(default_factory=TriggerMetadata)


class MetricConfig(BaseModel):
    """Metric configuration for threshold triggers."""
    source: Literal["prometheus", "datadog", "custom", "database"]
    query: str
    evaluation_interval_seconds: int = Field(default=SECONDS_PER_MINUTE, gt=0)


class CompoundCondition(BaseModel):
    """Compound condition for threshold triggers."""
    metric: str
    operator: str
    value: float


class CompoundConditions(BaseModel):
    """Compound conditions configuration."""
    operator: Literal["AND", "OR"]
    conditions: List[CompoundCondition]


class ThresholdTriggerInner(BaseModel):
    """Inner threshold trigger configuration."""
    name: str
    description: str
    type: Literal["ThresholdTrigger"]
    metric: MetricConfig
    condition: Literal["greater_than", "less_than", "equals"]
    threshold: float
    duration_minutes: int = Field(default=MEDIUM_ITEM_LIMIT, gt=0)
    compound_conditions: Optional[CompoundConditions] = None
    workflow: str
    workflow_inputs: Dict[str, Any] = Field(default_factory=dict)
    metadata: TriggerMetadata = Field(default_factory=TriggerMetadata)


class EventTrigger(BaseModel):
    """Event trigger configuration schema."""
    trigger: EventTriggerInner


class CronTrigger(BaseModel):
    """Cron trigger configuration schema."""
    trigger: CronTriggerInner


class ThresholdTrigger(BaseModel):
    """Threshold trigger configuration schema."""
    trigger: ThresholdTriggerInner


# ============================================
# UNION TYPE FOR ALL TRIGGER TYPES
# ============================================

TriggerConfig = Union[EventTrigger, CronTrigger, ThresholdTrigger]
