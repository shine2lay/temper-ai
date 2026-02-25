"""HTTP API routes for persistent agent management (M9)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from temper_ai.auth.api_key_auth import AuthContext, require_auth, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

_HTTP_NOT_FOUND = 404
_HTTP_BAD_REQUEST = 400
_HTTP_SERVER_ERROR = 500


def _agent_not_found_detail(name: str) -> str:
    """Build detail string for agent-not-found errors."""
    return f"Agent '{name}' not found"


class RegisterRequest(BaseModel):
    """Request body for registering an agent."""

    config_path: str
    metadata: dict | None = None


class MessageRequestAPI(BaseModel):
    """Request body for sending a message to an agent."""

    content: str
    context: dict | None = None
    max_tokens: int | None = None


def _get_service():
    """Lazy import AgentRegistryService."""
    from temper_ai.registry.service import AgentRegistryService

    return AgentRegistryService()


@router.get("")
def list_agents(status: str | None = None, ctx: AuthContext = Depends(require_auth)):
    """List all registered agents."""
    service = _get_service()
    agents = service.list_agents(status=status)
    return {"agents": [a.model_dump() for a in agents]}


@router.get("/{name}")
def get_agent(name: str, ctx: AuthContext = Depends(require_auth)):
    """Get agent details by name."""
    service = _get_service()
    agent = service.get_agent(name)
    if not agent:
        raise HTTPException(
            status_code=_HTTP_NOT_FOUND, detail=_agent_not_found_detail(name)
        )
    return agent.model_dump()


@router.post("/register")
def register_agent(
    request: RegisterRequest,
    ctx: AuthContext = Depends(require_role("owner", "editor")),
):
    """Register a new persistent agent."""
    service = _get_service()
    try:
        entry = service.register_agent(
            request.config_path,
            metadata=request.metadata,
        )
        return {"agent": entry.model_dump()}
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=_HTTP_BAD_REQUEST, detail=str(e)) from None


@router.delete("/{name}")
def unregister_agent(
    name: str, ctx: AuthContext = Depends(require_role("owner", "editor"))
):
    """Unregister an agent."""
    service = _get_service()
    success = service.unregister_agent(name)
    if not success:
        raise HTTPException(
            status_code=_HTTP_NOT_FOUND, detail=_agent_not_found_detail(name)
        )
    return {"deleted": True}


@router.post("/{name}/message")
def send_message(
    name: str,
    request: MessageRequestAPI,
    ctx: AuthContext = Depends(require_role("owner", "editor")),
):
    """Send a message to a registered agent (direct invocation)."""
    from temper_ai.registry._schemas import MessageRequest

    service = _get_service()
    agent = service.get_agent(name)
    if not agent:
        raise HTTPException(
            status_code=_HTTP_NOT_FOUND, detail=_agent_not_found_detail(name)
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
        raise HTTPException(status_code=_HTTP_SERVER_ERROR, detail=str(e)) from None
