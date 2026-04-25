"""RedisChunkNotifier — adapts EventNotifier protocol → Redis Streams publish.

Implements `notify_event`, `notify_stream_chunk`, `cleanup` so EventRecorder
can use it without knowing about Redis. Chunks → XADD; events → no-op
(they're already persisted to DB by EventRecorder); cleanup → terminal
sentinel + close.

This is the worker's exclusive use of Redis. The server uses
RedisChunkSubscriber on the read side; the two never share a process.
"""

from __future__ import annotations

import logging

from temper_ai.streaming.redis_streams import RedisChunkPublisher

logger = logging.getLogger(__name__)


class RedisChunkNotifier:
    """EventNotifier that forwards chunks to Redis Streams.

    Drop-in replacement for ws_manager when used from a subprocess
    worker. The worker constructs one of these and passes it as the
    `notifier` argument to EventRecorder/execute_workflow.
    """

    def __init__(self, publisher: RedisChunkPublisher | None = None) -> None:
        # Allow injection for tests; default constructs from env.
        self._publisher = publisher or RedisChunkPublisher()

    def notify_event(self, execution_id: str, event_type: str, data: dict) -> None:
        """Events are persisted to DB by EventRecorder before this notifier
        sees them. Subprocess workers don't need a second copy on Redis —
        the dashboard polls/snapshots from DB. So: no-op."""

    def notify_stream_chunk(
        self,
        execution_id: str,
        agent_id: str,
        content: str,
        chunk_type: str = "content",
        done: bool = False,
    ) -> None:
        """Live LLM chunk → Redis Stream. Best-effort; publisher swallows
        Redis outages so the worker keeps running."""
        self._publisher.publish(
            execution_id, agent_id, content, chunk_type=chunk_type, done=done,
        )

    def cleanup(self, execution_id: str) -> None:
        """Worker is done with this run. Send sentinel so subscribers wake,
        then close the client. Idempotent — double-cleanup is harmless."""
        self._publisher.publish_terminal(execution_id)

    def close(self) -> None:
        """Release the underlying Redis client. Called from the worker's
        terminal cleanup; routes never call this (per-run lifecycle)."""
        self._publisher.close()
