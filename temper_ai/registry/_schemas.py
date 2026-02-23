"""Pydantic schemas for the agent registry module."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from temper_ai.registry.constants import STATUS_REGISTERED


class PersistenceConfig(BaseModel):
    """Configuration for agent persistence behaviour."""

    enabled: bool = True


class AgentRegistryEntry(BaseModel):
    """A registered agent entry in the registry."""

    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    agent_type: str = "standard"
    config_path: str | None = None
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    memory_namespace: str = ""
    status: str = STATUS_REGISTERED
    total_invocations: int = 0
    registered_at: datetime
    last_active_at: datetime | None = None
    metadata_json: dict[str, Any] | None = None


class MessageRequest(BaseModel):
    """A message sent to a registered agent."""

    content: str
    context: dict[str, Any] | None = None
    max_tokens: int | None = None


class MessageResponse(BaseModel):
    """Response from a registered agent invocation."""

    content: str
    agent_name: str
    execution_id: str
    tokens_used: int | None = None
