"""
Pydantic schemas for configuration validation.

Defines schemas for agents, stages, workflows, tools, and triggers.
All schemas validate against the YAML/JSON structure from TECHNICAL_SPECIFICATION.md.
"""
from typing import Optional, List, Dict, Any, Literal, Union
from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================
# AGENT CONFIGURATION SCHEMAS
# ============================================

class InferenceConfig(BaseModel):
    """LLM inference configuration."""
    provider: Literal["ollama", "vllm", "openai", "anthropic", "custom"]
    model: str
    base_url: Optional[str] = None
    api_key_ref: Optional[str] = Field(
        default=None,
        description="Secret reference: ${env:VAR_NAME}, ${vault:path}, or ${aws:secret-id}"
    )
    # DEPRECATED: api_key field is deprecated, use api_key_ref instead
    api_key: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="DEPRECATED: Use api_key_ref with ${env:VAR_NAME} instead"
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    timeout_seconds: int = Field(default=60, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_delay_seconds: int = Field(default=2, ge=0)

    @model_validator(mode='after')
    def migrate_api_key(self) -> 'InferenceConfig':
        """Migrate old api_key field to api_key_ref with deprecation warning."""
        import warnings

        # If old api_key is set but api_key_ref is not, migrate it
        if self.api_key is not None and self.api_key_ref is None:
            warnings.warn(
                "The 'api_key' field is deprecated and will be removed in a future version. "
                "Use 'api_key_ref' with ${env:VAR_NAME} instead. "
                "Example: api_key_ref: ${env:OPENAI_API_KEY}",
                DeprecationWarning,
                stacklevel=2
            )
            # Treat old api_key as literal value for backward compatibility
            self.api_key_ref = self.api_key
            # Clear old field to avoid confusion
            self.api_key = None

        return self


class SafetyConfig(BaseModel):
    """Safety configuration."""
    mode: Literal["execute", "dry_run", "require_approval"] = "execute"
    require_approval_for_tools: List[str] = Field(default_factory=list)
    max_tool_calls_per_execution: int = Field(default=20, gt=0)
    max_execution_time_seconds: int = Field(default=300, gt=0)
    risk_level: Literal["low", "medium", "high"] = "medium"


class MemoryConfig(BaseModel):
    """Memory configuration."""
    enabled: bool = False
    type: Optional[Literal["vector", "episodic", "procedural", "semantic"]] = None
    scope: Optional[Literal["session", "project", "cross_session", "permanent"]] = None

    # Vector memory config
    retrieval_k: int = Field(default=10, gt=0)
    relevance_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Episodic memory config
    max_episodes: int = Field(default=1000, gt=0)
    decay_factor: float = Field(default=0.95, ge=0.0, le=1.0)

    @model_validator(mode='after')
    def validate_enabled_memory(self) -> 'MemoryConfig':
        if self.enabled and (self.type is None or self.scope is None):
            raise ValueError("When memory is enabled, both type and scope must be specified")
        return self


class RetryConfig(BaseModel):
    """Retry strategy configuration."""
    initial_delay_seconds: int = Field(default=1, gt=0)
    max_delay_seconds: int = Field(default=30, gt=0)
    exponential_base: float = Field(default=2.0, gt=1.0)


class ErrorHandlingConfig(BaseModel):
    """Error handling configuration."""
    retry_strategy: str  # Module reference (e.g., "ExponentialBackoff")
    max_retries: int = Field(default=3, ge=0)
    fallback: str  # Module reference (e.g., "GracefulDegradation")
    escalate_to_human_after: int = Field(default=3, gt=0)
    retry_config: RetryConfig = Field(default_factory=RetryConfig)


class MeritTrackingConfig(BaseModel):
    """Merit tracking configuration."""
    enabled: bool = True
    track_decision_outcomes: bool = True
    domain_expertise: List[str] = Field(default_factory=list)
    decay_enabled: bool = True
    half_life_days: int = Field(default=90, gt=0)


class ObservabilityConfig(BaseModel):
    """Observability configuration."""
    log_inputs: bool = True
    log_outputs: bool = True
    log_reasoning: bool = True
    log_full_llm_responses: bool = False
    track_latency: bool = True
    track_token_usage: bool = True


class PromptConfig(BaseModel):
    """Prompt configuration."""
    template: Optional[str] = None  # Path to template file
    inline: Optional[str] = None  # Inline prompt string
    variables: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_prompt(self) -> 'PromptConfig':
        if self.template is None and self.inline is None:
            raise ValueError("Either template or inline must be specified")
        if self.template is not None and self.inline is not None:
            raise ValueError("Only one of template or inline can be specified")
        return self


class ToolReference(BaseModel):
    """Tool reference with optional overrides."""
    name: str
    config: Dict[str, Any] = Field(default_factory=dict)


class MetadataConfig(BaseModel):
    """Metadata configuration."""
    tags: List[str] = Field(default_factory=list)
    owner: Optional[str] = None
    created: Optional[str] = None
    last_modified: Optional[str] = None
    documentation_url: Optional[str] = None


class AgentConfigInner(BaseModel):
    """Inner agent configuration fields."""
    name: str
    description: str
    version: str = "1.0"
    type: str = "standard"  # Agent type: standard, debate, human, custom
    prompt: PromptConfig
    inference: InferenceConfig
    tools: List[Union[str, ToolReference]]
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    error_handling: ErrorHandlingConfig
    merit_tracking: MeritTrackingConfig = Field(default_factory=MeritTrackingConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)


class AgentConfig(BaseModel):
    """Agent configuration schema."""
    agent: AgentConfigInner
    schema_version: str = Field(
        default="1.0",
        description="Schema version for backward compatibility and migrations"
    )


# ============================================
# TOOL CONFIGURATION SCHEMAS
# ============================================

class SafetyCheck(BaseModel):
    """Safety check configuration."""
    name: str
    config: Dict[str, Any] = Field(default_factory=dict)


class RateLimits(BaseModel):
    """Rate limiting configuration."""
    max_calls_per_minute: int = Field(default=100, gt=0)
    max_calls_per_hour: int = Field(default=1000, gt=0)
    max_concurrent_requests: int = Field(default=10, gt=0)
    cooldown_on_failure_seconds: int = Field(default=60, ge=0)


class ToolErrorHandlingConfig(BaseModel):
    """Tool error handling configuration."""
    retry_on_status_codes: List[int] = Field(default_factory=list)
    max_retries: int = Field(default=3, ge=0)
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
    timeout_seconds: int = Field(default=600, gt=0)
    adaptive_config: Dict[str, Any] = Field(default_factory=dict)


class CollaborationConfig(BaseModel):
    """Collaboration configuration."""
    strategy: str  # Module reference
    max_rounds: int = Field(default=3, gt=0)
    convergence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    config: Dict[str, Any] = Field(default_factory=dict)


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
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Auto-resolve if winning decision has >= this weighted support"
    )
    escalation_threshold: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description="Escalate if no decision has >= this support"
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional strategy-specific configuration"
    )

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
            # Normalize if not already normalized
            if abs(total_weight - 1.0) > 0.01:
                # Weights don't sum to 1.0, they'll be normalized at runtime
                pass
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
    min_successful_agents: int = Field(default=1, gt=0)
    fallback_strategy: Optional[str] = None
    retry_failed_agents: bool = True
    max_agent_retries: int = Field(default=2, ge=0)


class QualityGatesConfig(BaseModel):
    """Quality gates configuration."""
    enabled: bool = False  # Disabled by default for backward compatibility
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    min_findings: int = Field(default=5, ge=0)
    require_citations: bool = True
    on_failure: Literal["retry_stage", "escalate", "proceed_with_warning"] = "retry_stage"
    max_retries: int = Field(default=2, ge=0)


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
    max_loops: int = Field(default=1, gt=0)


class BudgetConfig(BaseModel):
    """Budget configuration."""
    max_cost_usd: Optional[float] = Field(default=None, ge=0)
    max_tokens: Optional[int] = Field(default=None, gt=0)
    action_on_exceed: Literal["halt", "continue", "notify"] = "halt"


class WorkflowConfigOptions(BaseModel):
    """Workflow configuration options."""
    max_iterations: int = Field(default=5, gt=0)
    convergence_detection: bool = False
    timeout_seconds: int = Field(default=3600, gt=0)
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
    max_stage_retries: int = Field(default=2, ge=0)
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
    max_connections: int = Field(default=10, gt=0)
    reconnect_delay_seconds: int = Field(default=5, gt=0)


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
    max_parallel_executions: int = Field(default=5, gt=0)
    queue_when_busy: bool = True
    max_queue_size: int = Field(default=100, gt=0)
    deduplicate: bool = True
    dedup_window_seconds: int = Field(default=300, gt=0)
    dedup_key: Optional[str] = None


class TriggerRetryConfig(BaseModel):
    """Retry configuration for triggers."""
    enabled: bool = True
    max_retries: int = Field(default=3, ge=0)
    retry_delay_seconds: int = Field(default=60, gt=0)
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
    min_hours_between_runs: int = Field(default=168, gt=0)
    workflow: str
    workflow_inputs: Dict[str, Any] = Field(default_factory=dict)
    metadata: TriggerMetadata = Field(default_factory=TriggerMetadata)


class MetricConfig(BaseModel):
    """Metric configuration for threshold triggers."""
    source: Literal["prometheus", "datadog", "custom", "database"]
    query: str
    evaluation_interval_seconds: int = Field(default=60, gt=0)


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
    duration_minutes: int = Field(default=10, gt=0)
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
