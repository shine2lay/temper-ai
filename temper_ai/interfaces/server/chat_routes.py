"""Chat API routes — create sessions and exchange messages with registered agents."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from temper_ai.auth.api_key_auth import require_auth, require_role

logger = logging.getLogger(__name__)

# In-process session store: maps session_id -> session metadata.
# For production, replace with a persistent backend.
_SESSIONS: dict[str, dict[str, Any]] = {}


# ── Request / Response models ─────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    """POST /api/chat/sessions request body."""

    agent_name: str
    metadata: dict[str, Any] | None = None


class CreateSessionResponse(BaseModel):
    """POST /api/chat/sessions response body."""

    session_id: str
    agent_name: str
    status: str = "active"


class SendMessageRequest(BaseModel):
    """POST /api/chat/sessions/{session_id}/message request body."""

    content: str
    context: dict[str, Any] | None = None
    max_tokens: int | None = None


class SendMessageResponse(BaseModel):
    """POST /api/chat/sessions/{session_id}/message response body."""

    session_id: str
    content: str
    agent_name: str
    execution_id: str


# ── Endpoint handlers ─────────────────────────────────────────────────


def _handle_create_session(body: CreateSessionRequest) -> CreateSessionResponse:
    """Create a new chat session bound to a registered agent."""
    from temper_ai.registry.service import AgentRegistryService

    try:
        service = AgentRegistryService()
        entry = service.get_agent(body.agent_name)
    except Exception as e:
        logger.exception("Failed to look up agent '%s'", body.agent_name)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to look up agent"
        ) from e

    if entry is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND, detail=f"Agent not found: {body.agent_name}"
        )

    session_id = uuid.uuid4().hex
    _SESSIONS[session_id] = {
        "session_id": session_id,
        "agent_name": body.agent_name,
        "status": "active",
        "metadata": body.metadata or {},
    }
    logger.info("Created chat session %s for agent '%s'", session_id, body.agent_name)
    return CreateSessionResponse(session_id=session_id, agent_name=body.agent_name)


def _handle_send_message(
    session_id: str, body: SendMessageRequest
) -> SendMessageResponse:
    """Send a message to the agent bound to a chat session."""
    from temper_ai.registry._schemas import MessageRequest
    from temper_ai.registry.service import AgentRegistryService

    session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}"
        )
    if session.get("status") != "active":
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Session is not active (status: {session.get('status')})",
        )

    agent_name: str = session["agent_name"]
    try:
        service = AgentRegistryService()
        msg = MessageRequest(
            content=body.content, context=body.context, max_tokens=body.max_tokens
        )
        response = service.invoke(agent_name, msg)
    except KeyError as e:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        logger.exception(
            "Agent invocation failed for session %s (agent: %s)", session_id, agent_name
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Agent invocation failed"
        ) from e

    return SendMessageResponse(
        session_id=session_id,
        content=response.content,
        agent_name=response.agent_name,
        execution_id=response.execution_id,
    )


def _handle_delete_session(session_id: str) -> dict[str, Any]:
    """Delete (close) a chat session."""
    if session_id not in _SESSIONS:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND, detail=f"Session not found: {session_id}"
        )
    session = _SESSIONS.pop(session_id)
    logger.info(
        "Deleted chat session %s (agent: %s)", session_id, session.get("agent_name")
    )
    return {"session_id": session_id, "status": "deleted"}


# ── Router factory ────────────────────────────────────────────────────


def create_chat_router(auth_enabled: bool = False) -> APIRouter:
    """Create the chat sessions API router.

    Args:
        auth_enabled: When True, attach auth dependencies to protected routes.
    """
    router = APIRouter(prefix="/api/chat", tags=["chat"])
    read_deps = [Depends(require_auth)] if auth_enabled else []
    write_deps = [Depends(require_role("owner", "editor"))] if auth_enabled else []

    @router.post(
        "/sessions", response_model=CreateSessionResponse, dependencies=write_deps
    )
    def create_session(body: CreateSessionRequest = Body(...)) -> CreateSessionResponse:
        """Create a new chat session."""
        return _handle_create_session(body)

    @router.post(
        "/sessions/{session_id}/message",
        response_model=SendMessageResponse,
        dependencies=read_deps,
    )
    def send_message(
        session_id: str, body: SendMessageRequest = Body(...)
    ) -> SendMessageResponse:
        """Send a message in a chat session."""
        return _handle_send_message(session_id, body)

    @router.delete("/sessions/{session_id}", dependencies=write_deps)
    def delete_session(session_id: str) -> dict[str, Any]:
        """Delete a chat session by ID."""
        return _handle_delete_session(session_id)

    return router
