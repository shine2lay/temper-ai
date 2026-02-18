"""Workflow configuration schemas."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.workflow.constants import DEFAULT_VERSION, ERROR_MSG_STAGE_PREFIX
from src.shared.constants.durations import SECONDS_PER_HOUR
from src.shared.constants.limits import SMALL_ITEM_LIMIT
from src.shared.constants.retries import MIN_RETRY_ATTEMPTS
from src.storage.schemas.agent_config import MetadataConfig


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


from src.improvement._schemas import OptimizationConfig  # noqa: F401
from src.lifecycle._schemas import LifecycleConfig  # noqa: F401


def _default_autonomous_loop_config() -> "BaseModel":
    """Lazy factory to avoid workflow→autonomy import for fan-out."""
    from src.autonomy._schemas import AutonomousLoopConfig
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
            from src.autonomy._schemas import AutonomousLoopConfig
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
