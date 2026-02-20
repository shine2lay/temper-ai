"""HTTP API routes for persistent agent management (M9)."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

_HTTP_NOT_FOUND = 404
_HTTP_BAD_REQUEST = 400
_HTTP_SERVER_ERROR = 500


class RegisterRequest(BaseModel):
    """Request body for registering an agent."""

    config_path: str
    metadata: Optional[dict] = None


class MessageRequestAPI(BaseModel):
    """Request body for sending a message to an agent."""

    content: str
    context: Optional[dict] = None
    max_tokens: Optional[int] = None


def _get_service():
    """Lazy import AgentRegistryService."""
    from temper_ai.registry.service import AgentRegistryService

    return AgentRegistryService()


@router.get("")
def list_agents(status: Optional[str] = None):
    """List all registered agents."""
    service = _get_service()
    agents = service.list_agents(status=status)
    return {"agents": [a.model_dump() for a in agents]}


@router.get("/{name}")
def get_agent(name: str):
    """Get agent details by name."""
    service = _get_service()
    agent = service.get_agent(name)
    if not agent:
        raise HTTPException(
            status_code=_HTTP_NOT_FOUND, detail=f"Agent '{name}' not found"
        )
    return agent.model_dump()


@router.post("/register")
def register_agent(request: RegisterRequest):
    """Register a new persistent agent."""
    service = _get_service()
    try:
        entry = service.register_agent(
            request.config_path, metadata=request.metadata,
        )
        return {"agent": entry.model_dump()}
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=_HTTP_BAD_REQUEST, detail=str(e))


@router.delete("/{name}")
def unregister_agent(name: str):
    """Unregister an agent."""
    service = _get_service()
    success = service.unregister_agent(name)
    if not success:
        raise HTTPException(
            status_code=_HTTP_NOT_FOUND, detail=f"Agent '{name}' not found"
        )
    return {"deleted": True}


@router.post("/{name}/message")
def send_message(name: str, request: MessageRequestAPI):
    """Send a message to a registered agent (direct invocation)."""
    from temper_ai.registry._schemas import MessageRequest

    service = _get_service()
    agent = service.get_agent(name)
    if not agent:
        raise HTTPException(
            status_code=_HTTP_NOT_FOUND, detail=f"Agent '{name}' not found"
        )

    try:
        msg = MessageRequest(
            content=request.content,
            context=request.context,
            max_tokens=request.max_tokens,
        )
        response = service.invoke(name, msg)
        return response.model_dump()
    except (RuntimeError, ValueError, KeyError) as e:
        raise HTTPException(status_code=_HTTP_SERVER_ERROR, detail=str(e))
