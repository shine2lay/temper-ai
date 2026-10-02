"""Redis Streams primitives for live chunk transport.

`chunk_stream_key(execution_id)` is the canonical key shape — both publisher
and subscriber import it so a typo in one can't silently break the other.

Stream entries are flat string maps (Redis Streams' native shape):
    agent_id, content, chunk_type, done, ts

Done events carry an additional `done=1` flag so subscribers can stop
reading without polling for stream-end. We also XADD a final sentinel
when the worker exits so a subscriber that's blocked on XREAD can wake.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Chunk:
    """One chunk as it flows through Redis Streams.

    Mirrors the EventNotifier.notify_stream_chunk signature one-for-one
    so the worker side and server side can use identical fields without
    translation. Distinct from worker_proto.ChunkEvent which is the
    on-the-wire spec for the future structured chunk format — phase 4
    keeps the simple shape that today's executor already produces.
    """

    execution_id: str
    agent_id: str
    content: str
    chunk_type: str = "content"
    done: bool = False
    # The LLM call this chunk belongs to, when the service stamped one.
    call_id: str | None = None


# Per-run stream length cap. Each chunk is ~50-200 bytes; 10k entries
# bounds memory at ~2 MB per active run. Old entries roll off automatically
# via Redis's MAXLEN trim.
DEFAULT_STREAM_MAXLEN = 10_000

# Default TTL for the stream key after the run completes. Enough for a
# late dashboard reconnect to fetch backlog; auto-cleanup after.
DEFAULT_STREAM_TTL_SECONDS = 24 * 60 * 60


def chunk_stream_key(execution_id: str) -> str:
    """Canonical Redis key for the chunk stream of one workflow run."""
    return f"temper:chunks:{execution_id}"


# Script agents' saved log rows (observability/script_logs.py), one stream per run beside the
# chunks: each entry is one row, already saved, as JSON. The stream only carries rows to viewers
# connected at the time (each reads from where the stream was when it connected); anyone else
# reads the rows from the database. So it is kept short: a row is up to ~100 KB, and a viewer
# that falls behind by more than this many rows sees a gap in the sequence numbers and fills it
# from the database too.
DEFAULT_SCRIPT_LOG_MAXLEN = 200


def script_log_stream_key(execution_id: str) -> str:
    """Redis key of the stream of script log rows of one workflow run."""
    return f"temper:scriptlog:{execution_id}"


def _resolve_url(url: str | None) -> str | None:
    """Pick the Redis URL: explicit arg > $TEMPER_REDIS_URL > $REDIS_URL.

    Returns None when no URL is configured — callers treat this as
    "Redis disabled" and run in degraded mode.
    """
    if url:
        return url
    return os.environ.get("TEMPER_REDIS_URL") or os.environ.get("REDIS_URL")


class RedisChunkPublisher:
    """Sync XADD client — used by the worker subprocess.

    Sync (not async) because the worker's streaming callback runs from
    LLM token threads; async-bridging would add latency for no gain. The
    underlying redis-py client is thread-safe.

    Best-effort: a Redis outage logs once and degrades to no-op so the
    worker keeps running. The DB still receives milestones via EventRecorder.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        maxlen: int = DEFAULT_STREAM_MAXLEN,
        ttl_seconds: int = DEFAULT_STREAM_TTL_SECONDS,
    ) -> None:
        self._url = _resolve_url(url)
        self._maxlen = maxlen
        self._ttl_seconds = ttl_seconds
        self._client: Any | None = None
        self._unhealthy = False  # set after first failure to suppress repeated logs

        if self._url is None:
            logger.info(
                "RedisChunkPublisher disabled (no $TEMPER_REDIS_URL set) — "
                "live chunks will not be available; events still go to DB",
            )
            return

        try:
            import redis
            self._client = redis.Redis.from_url(self._url, decode_responses=True)
            # ping so a misconfig fails-fast at worker startup, not at
            # the first chunk where it'd be hidden in callback noise
            self._client.ping()
            logger.info("RedisChunkPublisher connected: %s", self._url)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RedisChunkPublisher init failed (%s) — running degraded", exc,
            )
            self._client = None
            self._unhealthy = True

    @property
    def enabled(self) -> bool:
        return self._client is not None and not self._unhealthy

    def publish(
        self,
        execution_id: str,
        agent_id: str,
        content: str,
        chunk_type: str = "content",
        done: bool = False,
        call_id: str | None = None,
    ) -> None:
        """XADD a chunk event. Silently no-ops if Redis is unavailable.

        XADD with MAXLEN ~ N keeps the stream bounded (the `~` makes the
        trim approximate, which is faster than exact)."""
        client = self._client
        if not self.enabled or client is None:
            return
        try:
            client.xadd(
                chunk_stream_key(execution_id),
                {
                    "agent_id": agent_id,
                    "content": content,
                    "chunk_type": chunk_type,
                    "done": "1" if done else "0",
                    "call_id": call_id or "",
                },
                maxlen=self._maxlen,
                approximate=True,
            )
        except Exception as exc:  # noqa: BLE001
            self._mark_unhealthy(exc)

    def publish_script_log(self, execution_id: str, row: dict) -> None:
        """XADD one saved script log row. Silently no-ops if Redis is unavailable: the row is in
        the database, and a viewer that misses it here catches up from there."""
        client = self._client
        if not self.enabled or client is None:
            return
        key = script_log_stream_key(execution_id)
        try:
            pipe = client.pipeline(transaction=False)
            pipe.xadd(key, {"row": json.dumps(row, ensure_ascii=False)},
                      maxlen=DEFAULT_SCRIPT_LOG_MAXLEN, approximate=True)
            # Kept a day after its last row, like the chunks after the run: a worker that dies
            # before its terminal sentinel must not leave the stream behind for ever.
            pipe.expire(key, self._ttl_seconds)
            pipe.execute()
        except Exception as exc:  # noqa: BLE001
            self._mark_unhealthy(exc)

    def publish_terminal(self, execution_id: str) -> None:
        """Sentinel chunk: signals "no more chunks for this execution_id".

        Subscribers blocked on XREAD wake up, see done=1 with no content,
        and exit cleanly. Without this they'd time out on the next BLOCK
        cycle (slower UI dismissal of the streaming state). The script
        log stream gets one too, so its readers stop as well.
        """
        client = self._client
        if not self.enabled or client is None:
            return
        try:
            client.xadd(
                chunk_stream_key(execution_id),
                {
                    "agent_id": "",
                    "content": "",
                    "chunk_type": "terminal",
                    "done": "1",
                },
                maxlen=self._maxlen,
                approximate=True,
            )
            # Stamp a TTL so the stream doesn't live forever after the
            # last subscriber disconnects.
            client.expire(chunk_stream_key(execution_id), self._ttl_seconds)
            log_key = script_log_stream_key(execution_id)
            client.xadd(log_key, {"terminal": "1"},
                        maxlen=DEFAULT_SCRIPT_LOG_MAXLEN, approximate=True)
            client.expire(log_key, self._ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            self._mark_unhealthy(exc)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    def _mark_unhealthy(self, exc: Exception) -> None:
        if not self._unhealthy:
            logger.warning(
                "RedisChunkPublisher: write failed (%s) — degrading to no-op", exc,
            )
            self._unhealthy = True


class RedisChunkSubscriber:
    """Async XREAD reader — used by the server's WS handler.

    Each WS connection that opens for an execution_id runs one subscriber
    task. The task yields ChunkEvents to the WS forwarder until it sees
    a terminal sentinel or the WS closes.

    Block timeout is short (250ms) so cancellation propagates quickly:
    when the WS disconnects, the asyncio.CancelledError lands during a
    BLOCK, the redis call returns, the loop checks done and exits.
    """

    BLOCK_MS = 250

    def __init__(self, url: str | None = None) -> None:
        self._url = _resolve_url(url)
        self._client: Any | None = None

        if self._url is None:
            logger.info(
                "RedisChunkSubscriber disabled (no $TEMPER_REDIS_URL) — "
                "subprocess workers will not stream live chunks",
            )
            return

        try:
            from redis.asyncio import Redis as AsyncRedis
            self._client = AsyncRedis.from_url(self._url, decode_responses=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RedisChunkSubscriber init failed (%s)", exc)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def subscribe(
        self,
        execution_id: str,
        *,
        from_id: str = "0",
    ) -> AsyncIterator[Chunk]:
        """Yield Chunks for one execution_id until a terminal sentinel.

        Args:
            from_id: Redis Stream entry ID to start from. "0" replays
                full history (good for late-connecting clients); "$"
                streams only new entries arriving after subscribe.
        """
        if self._client is None:
            return

        key = chunk_stream_key(execution_id)
        last_id = from_id

        while True:
            try:
                resp = await self._client.xread(
                    {key: last_id}, block=self.BLOCK_MS, count=64,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Subscriber XREAD failed for %s (%s) — exiting",
                    execution_id, exc,
                )
                return

            if not resp:
                # BLOCK timeout, no new entries. Loop and re-block — gives
                # asyncio a chance to deliver cancellation between iterations.
                continue

            # resp shape: [(stream_key, [(entry_id, {field: value}), ...])]
            _key, entries = resp[0]
            for entry_id, fields in entries:
                last_id = entry_id
                chunk = Chunk(
                    execution_id=execution_id,
                    agent_id=fields.get("agent_id", ""),
                    content=fields.get("content", ""),
                    chunk_type=fields.get("chunk_type", "content"),
                    call_id=fields.get("call_id") or None,
                    done=fields.get("done", "0") == "1",
                )
                yield chunk
                if chunk.chunk_type == "terminal":
                    # Sentinel: worker is done; close the stream cleanly.
                    return

    async def script_log_position(self, execution_id: str) -> str | None:
        """Where a run's script log stream is now, to read on from: its last entry's id, "0"
        when it has none yet, or None when it has ended (or cannot be read). Never raises.

        A viewer reads what was saved before it connected from the database
        (`read_script_log`), so reading the stream from its beginning would only send rows
        twice; starting from the last entry's id rather than "$" leaves no gap between now and
        the first XREAD.
        """
        if self._client is None:
            return None
        try:
            newest = await self._client.xrevrange(script_log_stream_key(execution_id), count=1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Script log XREVRANGE failed for %s (%s)", execution_id, exc)
            return None
        if not newest:
            return "0"
        last_id, fields = newest[0]
        return None if fields.get("terminal") else last_id

    async def subscribe_script_logs(self, execution_id: str, *, from_id: str) -> AsyncIterator[dict]:
        """Yield the script log rows of one run after ``from_id`` (see `script_log_position`),
        until its terminal sentinel."""
        if self._client is None:
            return
        key = script_log_stream_key(execution_id)
        last_id = from_id
        while True:
            try:
                resp = await self._client.xread({key: last_id}, block=self.BLOCK_MS, count=16)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Script log XREAD failed for %s (%s); exiting", execution_id, exc)
                return
            if not resp:
                continue
            _key, entries = resp[0]
            for entry_id, fields in entries:
                last_id = entry_id
                if fields.get("terminal"):
                    return
                try:
                    row = json.loads(fields.get("row") or "")
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
