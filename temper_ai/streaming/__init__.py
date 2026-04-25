"""Live LLM chunk streaming via Redis Streams.

Subprocess workers don't share memory with the server, so the in-memory
event bus (used for in-process workers) doesn't reach them. Redis Streams
fills the gap — workers XADD chunk events; the server's WS handler XREADs
and forwards to connected clients.

Why Redis Streams (not pub/sub):
  - Backed by a log; late-connecting clients can XREAD from history
  - Bounded with MAXLEN so a stuck consumer can't OOM the broker
  - Native to existing infra; no new component to operate

Phase 4 ships:
  - RedisChunkPublisher (worker writes)
  - RedisChunkSubscriber (server reads)
  - RedisChunkNotifier (worker-side EventNotifier adapter)

Failure mode: if Redis is unreachable, publisher silently drops chunks.
Events still go to the DB via EventRecorder, so milestones flow normally;
only the live token stream is degraded. Server WS handler treats Redis
absence as "no live chunks for this run" — UI shows static updates only.
"""

from temper_ai.streaming.redis_notifier import RedisChunkNotifier
from temper_ai.streaming.redis_streams import (
    Chunk,
    RedisChunkPublisher,
    RedisChunkSubscriber,
    chunk_stream_key,
)

__all__ = [
    "Chunk",
    "RedisChunkNotifier",
    "RedisChunkPublisher",
    "RedisChunkSubscriber",
    "chunk_stream_key",
]
