"""Memory API endpoints for agent memory management.

Provides endpoints for listing, adding, searching, and clearing memories.
"""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from temper_ai.auth.api_key_auth import require_auth, require_role

logger = logging.getLogger(__name__)


# ── Request / Response models ─────────────────────────────────────────


class AddMemoryRequest(BaseModel):
    """POST /api/memory request body."""

    content: str
    memory_type: str = "episodic"  # episodic | procedural | cross_session
    tenant_id: str = "default"
    workflow_name: str = ""
    agent_name: str = ""
    namespace: str | None = None
    metadata: dict[str, Any] | None = None


class SearchMemoryRequest(BaseModel):
    """POST /api/memory/search request body."""

    query: str
    tenant_id: str = "default"
    workflow_name: str = ""
    agent_name: str = ""
    namespace: str | None = None
    limit: int = 10
    threshold: float = 0.0
    memory_type: str | None = None


# ── Router factory ────────────────────────────────────────────────────


def _handle_list_memories(
    tenant_id: str,
    workflow_name: str,
    agent_name: str,
    namespace: str | None,
    memory_type: str | None,
) -> dict[str, Any]:
    """List all memories for a given scope."""
    from temper_ai.memory.service import MemoryService

    svc = MemoryService()
    scope = svc.build_scope(
        tenant_id=tenant_id,
        workflow_name=workflow_name,
        agent_name=agent_name,
        namespace=namespace,
    )
    try:
        entries = svc.list_memories(scope, memory_type=memory_type)
        serializable = [
            e.model_dump() if hasattr(e, "model_dump") else vars(e) for e in entries
        ]
        return {"memories": serializable, "total": len(serializable)}
    except Exception as e:
        logger.exception("Failed to list memories")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list memories"
        ) from e


def _handle_add_memory(body: AddMemoryRequest) -> dict[str, Any]:
    """Add a memory entry."""
    from temper_ai.memory.service import MemoryService

    svc = MemoryService()
    scope = svc.build_scope(
        tenant_id=body.tenant_id,
        workflow_name=body.workflow_name,
        agent_name=body.agent_name,
        namespace=body.namespace,
    )
    try:
        if body.memory_type == "procedural":
            memory_id = svc.store_procedural(scope, body.content, body.metadata)
        elif body.memory_type == "cross_session":
            memory_id = svc.store_cross_session(scope, body.content, body.metadata)
        else:
            memory_id = svc.store_episodic(scope, body.content, body.metadata)
        return {
            "memory_id": memory_id,
            "status": "stored",
            "memory_type": body.memory_type,
        }
    except Exception as e:
        logger.exception("Failed to add memory")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add memory"
        ) from e


def _handle_search_memories(body: SearchMemoryRequest) -> dict[str, Any]:
    """Search memories by query within a scope."""
    from temper_ai.memory.service import MemoryService

    svc = MemoryService()
    scope = svc.build_scope(
        tenant_id=body.tenant_id,
        workflow_name=body.workflow_name,
        agent_name=body.agent_name,
        namespace=body.namespace,
    )
    try:
        entries = svc.search(
            scope=scope,
            query=body.query,
            limit=body.limit,
            threshold=body.threshold,
            memory_type=body.memory_type,
        )
        serializable = [
            e.model_dump() if hasattr(e, "model_dump") else vars(e) for e in entries
        ]
        return {
            "results": serializable,
            "total": len(serializable),
            "query": body.query,
        }
    except Exception as e:
        logger.exception("Failed to search memories")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search memories",
        ) from e


def _handle_clear_memories(
    tenant_id: str,
    workflow_name: str,
    agent_name: str,
    namespace: str | None,
) -> dict[str, Any]:
    """Clear all memories for a given scope."""
    from temper_ai.memory.service import MemoryService

    svc = MemoryService()
    scope = svc.build_scope(
        tenant_id=tenant_id,
        workflow_name=workflow_name,
        agent_name=agent_name,
        namespace=namespace,
    )
    try:
        count = svc.clear_memories(scope)
        return {"deleted": count, "status": "cleared"}
    except Exception as e:
        logger.exception("Failed to clear memories")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear memories",
        ) from e


def create_memory_router(auth_enabled: bool = False) -> APIRouter:
    """Create the memory API router."""
    router = APIRouter(prefix="/api/memory")
    read_deps = [Depends(require_auth)] if auth_enabled else []
    write_deps = [Depends(require_role("owner", "editor"))] if auth_enabled else []

    @router.get("", dependencies=read_deps)
    def list_memories(
        tenant_id: str = Query("default"),
        workflow_name: str = Query(""),
        agent_name: str = Query(""),
        namespace: str | None = Query(None),
        memory_type: str | None = Query(None),
    ) -> dict[str, Any]:
        """List stored memories with optional filters."""
        return _handle_list_memories(
            tenant_id, workflow_name, agent_name, namespace, memory_type
        )

    @router.post("", dependencies=write_deps)
    def add_memory(body: AddMemoryRequest = Body(...)) -> dict[str, Any]:
        """Add a new memory entry."""
        return _handle_add_memory(body)

    @router.post("/search", dependencies=read_deps)
    def search_memories(body: SearchMemoryRequest = Body(...)) -> dict[str, Any]:
        """Search memories by query text."""
        return _handle_search_memories(body)

    @router.delete("", dependencies=write_deps)
    def clear_memories(
        tenant_id: str = Query("default"),
        workflow_name: str = Query(""),
        agent_name: str = Query(""),
        namespace: str | None = Query(None),
    ) -> dict[str, Any]:
        """Clear all memories for an agent."""
        return _handle_clear_memories(tenant_id, workflow_name, agent_name, namespace)

    return router
