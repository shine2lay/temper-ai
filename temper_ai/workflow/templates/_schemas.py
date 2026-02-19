"""Template manifest and configuration schemas."""

from typing import List, Literal

from pydantic import BaseModel, Field

from temper_ai.shared.constants.probabilities import PROB_HIGH
from temper_ai.shared.constants.retries import DEFAULT_MAX_RETRIES

# Shared type for all product types
ProductTypeLiteral = Literal[
    "web_app",
    "mobile_app",
    "api",
    "data_product",
    "data_pipeline",
    "cli_tool",
]


class TemplateQualityGates(BaseModel):
    """Quality gate defaults for a product template."""

    enabled: bool = True
    min_confidence: float = Field(default=PROB_HIGH, ge=0.0, le=1.0)
    require_citations: bool = True
    on_failure: Literal["retry_stage", "escalate", "proceed_with_warning"] = (
        "retry_stage"
    )
    max_retries: int = Field(default=DEFAULT_MAX_RETRIES, ge=0)
    custom_checks: List[str] = Field(default_factory=list)


class TemplateDefaultInference(BaseModel):
    """Default inference settings for template agents."""

    provider: str = "vllm"
    model: str = "qwen3-next"
    base_url: str = "http://localhost:8000"


class TemplateManifest(BaseModel):
    """Manifest schema for a product template."""

    product_type: ProductTypeLiteral
    name: str
    description: str
    version: str = "1.0"
    required_inputs: List[str] = Field(default_factory=list)
    optional_inputs: List[str] = Field(default_factory=list)
    quality_gates: TemplateQualityGates = Field(
        default_factory=TemplateQualityGates,
    )
    stages: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    default_inference: TemplateDefaultInference = Field(
        default_factory=TemplateDefaultInference,
    )
