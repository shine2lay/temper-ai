"""Cross-agent knowledge sharing via published memory namespaces (M9)."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

PUBLISHED_KNOWLEDGE_NAMESPACE = "published_knowledge"
MAX_CONTENT_LENGTH = 10000
MEMORY_TYPE_PUBLISHED = "published"

_DEFAULT_RETRIEVAL_K = 5
_DEFAULT_RELEVANCE_THRESHOLD = 0.7
_DEFAULT_MAX_CONTEXT_CHARS = 2000


def _build_published_scope(agent_name: str) -> Any:
    """Build MemoryScope for an agent's published knowledge namespace."""
    from temper_ai.memory._schemas import MemoryScope

    return MemoryScope(
        namespace=f"{PUBLISHED_KNOWLEDGE_NAMESPACE}__{agent_name}",
        agent_name=agent_name,
    )


def publish_knowledge(
    agent_name: str,
    content: str,
    memory_service: Any,
    metadata: dict[str, Any] | None = None,
    memory_type: str = MEMORY_TYPE_PUBLISHED,
) -> str | None:
    """Publish knowledge from an agent to a shared namespace.

    Returns the memory entry ID or None on failure.
    Truncates content if it exceeds MAX_CONTENT_LENGTH.
    """
    from temper_ai.memory._schemas import MemoryEntry

    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH]

    scope = _build_published_scope(agent_name)
    entry = MemoryEntry(
        content=content,
        memory_type=memory_type,
        metadata=metadata or {},
    )
    try:
        entry_id = memory_service.store_episodic(scope, entry.content, entry.metadata)
        return entry_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to publish knowledge for agent %s: %s", agent_name, exc)
        return None


def retrieve_subscribed_knowledge(
    subscribe_to: list[str],
    query: str,
    memory_service: Any,
    retrieval_k: int = _DEFAULT_RETRIEVAL_K,
    relevance_threshold: float = _DEFAULT_RELEVANCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Retrieve knowledge from subscribed agents' namespaces.

    Args:
        subscribe_to: List of agent names to read from.
        query: Search query.
        memory_service: MemoryService instance.
        retrieval_k: Max results per agent.
        relevance_threshold: Min relevance score.

    Returns:
        List of dicts with 'agent_name', 'content', 'relevance_score' keys.
    """
    results: list[dict[str, Any]] = []
    for agent_name in subscribe_to:
        scope = _build_published_scope(agent_name)
        try:
            entries = memory_service.search(
                scope, query, limit=retrieval_k, threshold=relevance_threshold
            )
            for entry in entries:
                if entry.relevance_score >= relevance_threshold:
                    results.append(
                        {
                            "agent_name": agent_name,
                            "content": entry.content,
                            "relevance_score": entry.relevance_score,
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to retrieve knowledge from agent %s: %s", agent_name, exc
            )
    return results


def format_cross_pollination_context(
    results: list[dict[str, Any]],
    max_chars: int = _DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    """Format cross-pollination results as a context string for prompt injection."""
    if not results:
        return ""
    sections = []
    total = 0
    for result in results:
        entry = f"[From {result['agent_name']}]: {result['content']}"
        if total + len(entry) > max_chars:
            break
        sections.append(entry)
        total += len(entry)
    return "\n".join(sections)
