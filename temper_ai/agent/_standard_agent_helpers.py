"""Helper free functions for StandardAgent to reduce class size."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from temper_ai.memory._schemas import MemoryScope
    from temper_ai.memory.service import MemoryService

logger = logging.getLogger(__name__)

_MEMORY_ERRORS = (ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError)
_PROCEDURAL_MEMORY_FAIL_MSG = "Procedural memory injection failed for agent %s: %s"


def _fetch_memory_text(
    svc: MemoryService,
    scope: MemoryScope,
    query: str,
    mem_cfg: Any,
) -> str:
    """Retrieve episodic + procedural memory text for a given scope.

    Returns an empty string if nothing is found or an error occurs.
    """
    shared_ns = getattr(mem_cfg, "shared_namespace", None)
    if shared_ns:
        shared_scope = svc.build_shared_scope(scope, shared_ns)
        memory_text = svc.retrieve_with_shared(
            scope,
            shared_scope,
            query,
            retrieval_k=mem_cfg.retrieval_k,
            relevance_threshold=mem_cfg.relevance_threshold,
            decay_factor=mem_cfg.decay_factor,
        )
    else:
        memory_text = svc.retrieve_context(
            scope,
            query,
            retrieval_k=mem_cfg.retrieval_k,
            relevance_threshold=mem_cfg.relevance_threshold,
            decay_factor=mem_cfg.decay_factor,
        )
    return memory_text or ""


def build_memory_scope(
    config: Any,
    agent_name: str,
    svc: MemoryService,
    context: Any | None = None,
) -> MemoryScope:
    """Build a MemoryScope from agent config and execution context."""
    mem_cfg = config.agent.memory
    workflow_name = ""
    if context and context.metadata:
        workflow_name = context.metadata.get("workflow_name", "")
    scope = svc.build_scope(
        tenant_id=mem_cfg.tenant_id,
        workflow_name=workflow_name,
        agent_name=agent_name,
        namespace=mem_cfg.memory_namespace,
    )
    if getattr(config.agent, "persistent", False):
        from temper_ai.memory._schemas import MemoryScope as _MemoryScope
        from temper_ai.registry.constants import PERSISTENT_NAMESPACE_PREFIX

        scope = _MemoryScope(
            tenant_id=scope.tenant_id,
            workflow_name="",
            agent_name=scope.agent_name,
            namespace=f"{PERSISTENT_NAMESPACE_PREFIX}{config.agent.name}",
            agent_id=getattr(config.agent, "agent_id", None),
        )
    return scope


def inject_memory_context(
    template: str,
    input_data: dict[str, Any],
    config: Any,
    agent_name: str,
    svc: MemoryService,
    scope: MemoryScope,
) -> str:
    """Inject relevant memories into the prompt template.

    Returns template unchanged on error.
    """
    from temper_ai.memory.constants import MEMORY_QUERY_MAX_CHARS

    parts = [str(v) for v in input_data.values() if isinstance(v, str)]
    query = " ".join(parts)[:MEMORY_QUERY_MAX_CHARS]

    try:
        mem_cfg = config.agent.memory
        memory_text = _fetch_memory_text(svc, scope, query, mem_cfg)
        if memory_text:
            template += "\n\n---\n\n" + memory_text

        try:
            procedural_text = _fetch_procedural_text(
                svc, scope, query, mem_cfg, agent_name
            )
            if procedural_text:
                template += "\n\n" + procedural_text
        except _MEMORY_ERRORS as exc:
            logger.warning(_PROCEDURAL_MEMORY_FAIL_MSG, agent_name, exc)
    except _MEMORY_ERRORS as exc:
        logger.warning("Memory injection failed for agent %s: %s", agent_name, exc)

    return template


def retrieve_memory_text(
    svc: MemoryService,
    scope: MemoryScope,
    mem_cfg: Any,
    query: str,
    agent_name: str,
) -> str:
    """Retrieve episodic and procedural memory text, returning combined string."""
    result = ""
    memory_text = _fetch_memory_text(svc, scope, query, mem_cfg)
    if memory_text:
        result += "\n\n---\n\n" + memory_text
    try:
        procedural_text = _fetch_procedural_text(svc, scope, query, mem_cfg, agent_name)
        if procedural_text:
            result += "\n\n" + procedural_text
    except _MEMORY_ERRORS as exc:
        logger.warning(_PROCEDURAL_MEMORY_FAIL_MSG, agent_name, exc)
    return result


def _fetch_procedural_text(
    svc: MemoryService,
    scope: MemoryScope,
    query: str,
    mem_cfg: Any,
    agent_name: str,
) -> str:
    """Retrieve procedural memory text, suppressing non-fatal errors."""
    try:
        procedural_text = svc.retrieve_procedural_context(
            scope,
            query,
            retrieval_k=mem_cfg.retrieval_k,
            relevance_threshold=mem_cfg.relevance_threshold,
        )
        return procedural_text or ""
    except (ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError) as exc:
        logger.warning(
            _PROCEDURAL_MEMORY_FAIL_MSG,
            agent_name,
            exc,
        )
        return ""
