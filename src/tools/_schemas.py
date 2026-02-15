"""Tool configuration schemas."""
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from src.workflow.constants import DEFAULT_VERSION
from src.shared.constants.durations import SECONDS_PER_MINUTE
from src.shared.constants.limits import (
    DEFAULT_QUEUE_SIZE,
    MEDIUM_ITEM_LIMIT,
    SMALL_QUEUE_SIZE,
)
from src.shared.constants.retries import DEFAULT_MAX_RETRIES
from src.storage.schemas.agent_config import MetadataConfig


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
    version: str = DEFAULT_VERSION
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
