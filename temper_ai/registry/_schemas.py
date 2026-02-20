"""Pydantic schemas for the agent registry module."""
from datetime import datetime
from typing import Any, Dict, Optional

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
    config_path: Optional[str] = None
    config_snapshot: Dict[str, Any] = Field(default_factory=dict)
    memory_namespace: str = ""
    status: str = STATUS_REGISTERED
    total_invocations: int = 0
    registered_at: datetime
    last_active_at: Optional[datetime] = None
    metadata_json: Optional[Dict[str, Any]] = None


class MessageRequest(BaseModel):
    """A message sent to a registered agent."""

    content: str
    context: Optional[Dict[str, Any]] = None
    max_tokens: Optional[int] = None


class MessageResponse(BaseModel):
    """Response from a registered agent invocation."""

    content: str
    agent_name: str
    execution_id: str
    tokens_used: Optional[int] = None
