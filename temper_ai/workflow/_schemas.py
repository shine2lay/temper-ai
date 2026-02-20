"""Workflow configuration schemas."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from temper_ai.workflow.constants import DEFAULT_VERSION, ERROR_MSG_STAGE_PREFIX
from temper_ai.shared.constants.durations import SECONDS_PER_HOUR
from temper_ai.shared.constants.limits import SMALL_ITEM_LIMIT
from temper_ai.shared.constants.retries import MIN_RETRY_ATTEMPTS
from temper_ai.storage.schemas.agent_config import MetadataConfig


class WorkflowStageReference(BaseModel):
    """Reference to a stage in a workflow."""
    name: str
    stage_ref: Optional[str] = None
    config_path: Optional[str] = Field(
        default=None,
        json_schema_extra={"deprecated": True},
        description="Deprecated: use stage_ref instead",
    )
    depends_on: List[str] = Field(default_factory=list)
    optional: bool = False
    skip_if: Optional[str] = None
    conditional: bool = False
    condition: Optional[str] = None
    skip_to: Optional[str] = None
    loops_back_to: Optional[str] = None
    loop_condition: Optional[str] = None
    max_loops: int = Field(default=MIN_RETRY_ATTEMPTS, gt=0)

    @model_validator(mode='after')
    def resolve_stage_ref(self) -> 'WorkflowStageReference':
        """Resolve config_path alias to stage_ref with deprecation warning."""
        if self.config_path and not self.stage_ref:
            import warnings
            warnings.warn(
                "'config_path' is deprecated in WorkflowStageReference, use 'stage_ref'",
                DeprecationWarning,
                stacklevel=2,
            )
            self.stage_ref = self.config_path
        if not self.stage_ref:
            raise ValueError("stage_ref is required (or use deprecated config_path)")
        return self

    on_complete: Optional[Any] = Field(
        default=None,
        description="Event to emit on stage completion — lazy-validated to StageEventEmitConfig",
    )
    trigger: Optional[Any] = Field(
        default=None,
        description="Event trigger config — lazy-validated to StageTriggerConfig",
    )

    @model_validator(mode='after')
    def validate_conditional_config(self) -> 'WorkflowStageReference':
        """Validate conditional stage configuration.

        Rules:
        - condition and skip_if are mutually exclusive
        - loops_back_to must be a non-empty string if set
        """
        if self.condition and self.skip_if:
            raise ValueError(
                f"{ERROR_MSG_STAGE_PREFIX}{self.name}': 'condition' and 'skip_if' are mutually "
                "exclusive — use one or the other"
            )
        if self.loops_back_to is not None and not self.loops_back_to.strip():
            raise ValueError(
                f"{ERROR_MSG_STAGE_PREFIX}{self.name}': 'loops_back_to' must be a non-empty string"
            )
        return self

    @model_validator(mode="after")
    def validate_on_complete(self) -> "WorkflowStageReference":
        """Parse on_complete dict into StageEventEmitConfig if provided."""
        if self.on_complete is not None and isinstance(self.on_complete, dict):
            from temper_ai.events._schemas import StageEventEmitConfig
            self.on_complete = StageEventEmitConfig(**self.on_complete)
        return self

    @model_validator(mode="after")
    def validate_trigger(self) -> "WorkflowStageReference":
        """Parse trigger dict into StageTriggerConfig if provided."""
        if self.trigger is not None and isinstance(self.trigger, dict):
            from temper_ai.events._schemas import StageTriggerConfig
            self.trigger = StageTriggerConfig(**self.trigger)
        return self

    @model_validator(mode="after")
    def validate_trigger_depends_exclusive(self) -> "WorkflowStageReference":
        """Ensure trigger and depends_on are mutually exclusive."""
        if self.trigger is not None and self.depends_on:
            raise ValueError(
                "Stage cannot have both 'trigger' and 'depends_on' — "
                "event-triggered stages are DAG roots"
            )
        return self


class BudgetConfig(BaseModel):
    """Budget configuration."""
    max_cost_usd: Optional[float] = Field(default=None, ge=0)
    max_tokens: Optional[int] = Field(default=None, gt=0)
    action_on_exceed: Literal["halt", "continue", "notify"] = "halt"


class WorkflowRateLimitConfig(BaseModel):
    """Workflow-level rate limiting configuration (R0.9)."""
    enabled: bool = False
    max_rpm: int = Field(default=60, gt=0)
    block_on_limit: bool = True
    max_wait_seconds: float = Field(default=60.0, gt=0)


def _default_planning_config() -> "BaseModel":
    """Lazy factory to avoid workflow→planning import for fan-out."""
    from temper_ai.workflow.planning import PlanningConfig
    return PlanningConfig()


class WorkflowConfigOptions(BaseModel):
    """Workflow configuration options."""
    max_iterations: int = Field(default=SMALL_ITEM_LIMIT, gt=0)
    convergence_detection: bool = False
    timeout_seconds: int = Field(default=SECONDS_PER_HOUR, gt=0)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    tool_cache_enabled: bool = Field(
        default=False,
        description="Enable tool result caching for read-only tools",
    )
    rate_limit: WorkflowRateLimitConfig = Field(
        default_factory=WorkflowRateLimitConfig,
    )
    planning: Any = Field(default_factory=_default_planning_config)
    event_bus: Optional[Any] = Field(
        default=None,
        description="Event bus configuration — lazy-validated to EventBusConfig",
    )

    @field_validator('planning', mode='before')
    @classmethod
    def coerce_planning(cls, v: Any) -> Any:
        """Coerce dict to PlanningConfig at validation time."""
        if isinstance(v, dict):
            from temper_ai.workflow.planning import PlanningConfig
            return PlanningConfig(**v)
        return v

    @model_validator(mode="after")
    def validate_event_bus(self) -> "WorkflowConfigOptions":
        """Parse event_bus dict into EventBusConfig if provided."""
        if self.event_bus is not None and isinstance(self.event_bus, dict):
            from temper_ai.events._schemas import EventBusConfig
            self.event_bus = EventBusConfig(**self.event_bus)
        return self


class WorkflowSafetyConfig(BaseModel):
    """Workflow safety configuration."""
    composition_strategy: str = "MostRestrictive"
    global_mode: Literal["execute", "dry_run", "require_approval"] = "execute"
    approval_required_stages: List[str] = Field(default_factory=list)
    dry_run_stages: List[str] = Field(default_factory=list)
    custom_rules: List[Dict[str, Any]] = Field(default_factory=list)


from temper_ai.optimization._schemas import OptimizationConfig  # noqa: F401
from temper_ai.lifecycle._schemas import LifecycleConfig  # noqa: F401


def _default_autonomous_loop_config() -> "BaseModel":
    """Lazy factory to avoid workflow→autonomy import for fan-out."""
    from temper_ai.autonomy._schemas import AutonomousLoopConfig
    return AutonomousLoopConfig()


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
    version: str = DEFAULT_VERSION
    product_type: Optional[Literal[
        "web_app", "mobile_app", "api", "data_product",
        "data_pipeline", "cli_tool",
    ]] = None
    predecessor_injection: bool = Field(
        default=False,
        description=(
            "When true, stages without explicit inputs receive "
            "outputs from DAG predecessors only (not full state)."
        ),
    )
    stages: List[WorkflowStageReference]
    config: WorkflowConfigOptions = Field(default_factory=WorkflowConfigOptions)
    safety: WorkflowSafetyConfig = Field(default_factory=WorkflowSafetyConfig)
    optimization: Optional[OptimizationConfig] = None
    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
    autonomous_loop: Any = Field(default_factory=_default_autonomous_loop_config)
    observability: WorkflowObservabilityConfig = Field(default_factory=WorkflowObservabilityConfig)
    error_handling: WorkflowErrorHandlingConfig
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)

    @field_validator('autonomous_loop', mode='before')
    @classmethod
    def coerce_autonomous_loop(cls, v: Any) -> Any:
        """Coerce dict to AutonomousLoopConfig at validation time."""
        if isinstance(v, dict):
            from temper_ai.autonomy._schemas import AutonomousLoopConfig
            return AutonomousLoopConfig(**v)
        return v

    @field_validator('stages')
    @classmethod
    def validate_stages(cls, v: List['WorkflowStageReference']) -> List['WorkflowStageReference']:
        """Validate workflow stage configuration."""
        if not v:
            raise ValueError("At least one stage must be specified")
        return v

    @model_validator(mode='after')
    def validate_stage_dependencies(self) -> 'WorkflowConfigInner':
        """Validate all depends_on references point to existing stages."""
        stage_names = {s.name for s in self.stages}
        for stage in self.stages:
            for dep in stage.depends_on:
                if dep not in stage_names:
                    raise ValueError(
                        f"{ERROR_MSG_STAGE_PREFIX}{stage.name}' depends_on unknown stage '{dep}'"
                    )
        return self


class WorkflowConfig(BaseModel):
    """Workflow configuration schema."""
    workflow: WorkflowConfigInner
    schema_version: str = Field(
        default="1.0",
        description="Schema version for backward compatibility and migrations"
    )
