"""Agent configuration schemas.

Canonical definitions for agent-related Pydantic models that are shared
between ``src.agents`` and ``src.compiler``.  These were originally
defined in ``src.compiler.schemas`` and are re-exported there for
backward compatibility.

Defines schemas for agent configuration including inference, safety,
memory, prompt, tool references, and observability settings.
"""
from typing import Any, ClassVar, Dict, FrozenSet, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from src.agents.constants import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    MAX_EXECUTION_TIME_SECONDS,
    MAX_PROMPT_LENGTH,
    MAX_TOOL_CALLS_PER_EXECUTION,
)
from src.constants.durations import (
    DAYS_90,
    SECONDS_PER_MINUTE,
)
from src.constants.limits import (
    DEFAULT_QUEUE_SIZE,
    MEDIUM_ITEM_LIMIT,
    MAX_TEXT_LENGTH,
)
from src.constants.probabilities import PROB_HIGH
from src.constants.retries import (
    DEFAULT_MAX_RETRIES,
    SHORT_BACKOFF_SECONDS,
)


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
    temperature: float = Field(default=DEFAULT_TEMPERATURE, ge=0.0, le=2.0)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, gt=0)
    top_p: float = Field(default=DEFAULT_TOP_P, ge=0.0, le=1.0)
    timeout_seconds: int = Field(default=SECONDS_PER_MINUTE, gt=0)
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0)
    retry_delay_seconds: int = Field(default=int(SHORT_BACKOFF_SECONDS), ge=0)

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
    max_tool_calls_per_execution: int = Field(default=MAX_TOOL_CALLS_PER_EXECUTION, gt=0)
    max_execution_time_seconds: int = Field(default=MAX_EXECUTION_TIME_SECONDS, gt=0)
    max_prompt_length: int = Field(default=MAX_PROMPT_LENGTH, gt=0)
    max_tool_result_size: int = Field(default=MAX_TEXT_LENGTH, gt=0)
    risk_level: Literal["low", "medium", "high"] = "medium"


class MemoryConfig(BaseModel):
    """Memory configuration."""
    enabled: bool = False
    type: Optional[Literal["vector", "episodic", "procedural", "semantic"]] = None
    scope: Optional[Literal["session", "project", "cross_session", "permanent"]] = None

    # Vector memory config
    retrieval_k: int = Field(default=MEDIUM_ITEM_LIMIT, gt=0)
    relevance_threshold: float = Field(default=PROB_HIGH, ge=0.0, le=1.0)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Episodic memory config
    max_episodes: int = Field(default=DEFAULT_QUEUE_SIZE, gt=0)
    decay_factor: float = Field(default=0.95, ge=0.0, le=1.0)

    @model_validator(mode='after')
    def validate_enabled_memory(self) -> 'MemoryConfig':
        """Validate that type and scope are set when memory is enabled."""
        if self.enabled and (self.type is None or self.scope is None):
            raise ValueError("When memory is enabled, both type and scope must be specified")
        return self


class RetryConfig(BaseModel):
    """Retry strategy configuration."""
    initial_delay_seconds: int = Field(default=1, gt=0)
    max_delay_seconds: int = Field(default=SECONDS_PER_MINUTE // 2, gt=0)
    exponential_base: float = Field(default=2.0, gt=1.0)


class ErrorHandlingConfig(BaseModel):
    """Error handling configuration."""

    VALID_RETRY_STRATEGIES: ClassVar[FrozenSet[str]] = frozenset({
        "ExponentialBackoff",
        "LinearBackoff",
        "FixedDelay",
    })
    VALID_FALLBACKS: ClassVar[FrozenSet[str]] = frozenset({
        "GracefulDegradation",
        "ReturnDefault",
        "RaiseError",
        "LogAndContinue",
    })

    retry_strategy: str = Field(
        default="ExponentialBackoff",
        description="Module reference (e.g., 'ExponentialBackoff')"
    )
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0)
    fallback: str = Field(
        default="GracefulDegradation",
        description="Module reference (e.g., 'GracefulDegradation')"
    )
    escalate_to_human_after: int = Field(default=DEFAULT_MAX_RETRIES, gt=0)
    retry_config: RetryConfig = Field(default_factory=RetryConfig)

    @field_validator("retry_strategy")
    @classmethod
    def validate_retry_strategy(cls, v: str) -> str:
        """Validate retry_strategy is a valid strategy name."""
        if v not in cls.VALID_RETRY_STRATEGIES:
            raise ValueError(
                f"Invalid retry_strategy '{v}'. "
                f"Must be one of: {sorted(cls.VALID_RETRY_STRATEGIES)}"
            )
        return v

    @field_validator("fallback")
    @classmethod
    def validate_fallback(cls, v: str) -> str:
        """Validate fallback is a valid fallback name."""
        if v not in cls.VALID_FALLBACKS:
            raise ValueError(
                f"Invalid fallback '{v}'. "
                f"Must be one of: {sorted(cls.VALID_FALLBACKS)}"
            )
        return v


class MeritTrackingConfig(BaseModel):
    """Merit tracking configuration."""
    enabled: bool = True
    track_decision_outcomes: bool = True
    domain_expertise: List[str] = Field(default_factory=list)
    decay_enabled: bool = True
    half_life_days: int = Field(default=DAYS_90, gt=0)


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
        """Validate that exactly one of template or inline is specified."""
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
    tools: Optional[List[Union[str, ToolReference]]] = None
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
