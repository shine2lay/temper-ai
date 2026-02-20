"""Schemas for the post-execution autonomous loop."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from temper_ai.autonomy.constants import (
    DEFAULT_AUTO_APPLY_MIN_CONFIDENCE,
    DEFAULT_MAX_AUTO_APPLY_PER_RUN,
)


class AutonomousLoopConfig(BaseModel):
    """Configuration for the post-execution autonomous loop.

    Opt-in by default (enabled=False). Each subsystem can be
    individually toggled.
    """

    enabled: bool = False
    learning_enabled: bool = True
    goals_enabled: bool = True
    portfolio_enabled: bool = True

    # Feedback application (opt-in)
    auto_apply_learning: bool = False
    auto_apply_goals: bool = False
    auto_apply_min_confidence: float = DEFAULT_AUTO_APPLY_MIN_CONFIDENCE
    max_auto_apply_per_run: int = DEFAULT_MAX_AUTO_APPLY_PER_RUN

    # Prompt optimization (opt-in)
    prompt_optimization_enabled: bool = False


class WorkflowRunContext(BaseModel):
    """Context passed to the orchestrator after a workflow run."""

    workflow_id: str
    workflow_name: str
    product_type: Optional[str] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float = 0.0
    status: str = "unknown"
    cost_usd: float = 0.0
    total_tokens: int = 0


class PostExecutionReport(BaseModel):
    """Report produced by the autonomous loop after post-execution analysis."""

    learning_result: Optional[Dict[str, Any]] = None
    goals_result: Optional[Dict[str, Any]] = None
    portfolio_result: Optional[Dict[str, Any]] = None
    feedback_result: Optional[Dict[str, Any]] = None
    memory_sync_result: Optional[Dict[str, Any]] = None
    optimization_result: Optional[Dict[str, Any]] = None
    errors: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0
