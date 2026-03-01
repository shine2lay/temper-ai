"""Workflow planning configuration (R0.8)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlanningConfig(BaseModel):
    """Configuration for workflow planning pass."""

    enabled: bool = False
    provider: Literal["ollama", "vllm", "openai", "anthropic", "custom"] = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    api_key_ref: str | None = None
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)  # scanner: skip-magic
    max_tokens: int = Field(default=2048, gt=0)
