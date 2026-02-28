"""Pydantic schemas for self-modifying lifecycle configuration."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from temper_ai.lifecycle.constants import DEFAULT_COMPLEXITY, MIN_PRIORITY


class ProjectSize(StrEnum):
    """Project size classification."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class RiskLevel(StrEnum):
    """Project risk level classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProjectCharacteristics(BaseModel):
    """Characteristics of a project used for lifecycle adaptation."""

    size: ProjectSize = ProjectSize.MEDIUM
    product_type: str | None = None
    risk_level: RiskLevel = RiskLevel.MEDIUM
    estimated_complexity: float = Field(default=DEFAULT_COMPLEXITY, ge=0.0, le=1.0)
    is_prototype: bool = False
    tags: list[str] = Field(default_factory=list)


class AdaptationAction(StrEnum):
    """Types of adaptation that can be applied to a workflow stage."""

    SKIP = "skip"
    ADD = "add"
    REORDER = "reorder"
    MODIFY = "modify"


class AdaptationRule(BaseModel):
    """A single adaptation rule that modifies workflow structure."""

    name: str
    action: AdaptationAction
    stage_name: str
    condition: str  # Jinja2: "{{ size == 'small' }}"

    # ADD action fields
    stage_ref: str | None = None
    insert_after: str | None = None
    insert_before: str | None = None

    # REORDER action fields
    move_after: str | None = None
    move_before: str | None = None

    # MODIFY action fields
    modifications: dict[str, Any] = Field(default_factory=dict)

    rationale: str = ""
    priority: int = Field(default=MIN_PRIORITY, ge=0)


class LifecycleProfile(BaseModel):
    """A named set of adaptation rules applied based on project characteristics."""

    name: str
    description: str = ""
    version: str = "1.0"
    product_types: list[str] = Field(default_factory=list)
    rules: list[AdaptationRule] = Field(default_factory=list)
    enabled: bool = True
    source: str = "manual"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    min_autonomy_level: int = 0
    requires_approval: bool = True


class LifecycleConfig(BaseModel):
    """Lifecycle configuration embedded in WorkflowConfigInner."""

    enabled: bool = False
    profile: str | None = None
    auto_classify: bool = True
    experiment_id: str | None = None


class AdaptationRecord(BaseModel):
    """Record of a lifecycle adaptation applied to a workflow."""

    workflow_id: str
    profile_name: str
    characteristics: ProjectCharacteristics
    rules_applied: list[str] = Field(default_factory=list)
    stages_original: list[str] = Field(default_factory=list)
    stages_adapted: list[str] = Field(default_factory=list)
    experiment_id: str | None = None
    experiment_variant: str | None = None


class StageMetrics(BaseModel):
    """Historical metrics for a workflow stage."""

    stage_name: str
    avg_duration: float = 0.0
    success_rate: float = 1.0
    run_count: int = 0
    avg_token_usage: float = 0.0


class WorkflowMetrics(BaseModel):
    """Historical metrics for a workflow."""

    workflow_name: str
    avg_duration: float = 0.0
    success_rate: float = 1.0
    run_count: int = 0


class DegradationReport(BaseModel):
    """Report of quality degradation detected for a profile."""

    profile_name: str
    baseline_success_rate: float
    adapted_success_rate: float
    degradation_pct: float
    sample_size: int
    recommendation: str = "disable"
