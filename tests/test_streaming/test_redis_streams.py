"""Tests for the Redis chunk streaming primitives.

Strategy: degraded-mode tests (no Redis available) are pure unit tests.
A second class hits a real Redis if $TEMPER_REDIS_URL is set, otherwise
those tests skip — keeps CI green when Redis isn't running locally but
exercises the actual XADD/XREAD round-trip when it is.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from temper_ai.streaming.redis_streams import (
    Chunk,
    RedisChunkPublisher,
    RedisChunkSubscriber,
    chunk_stream_key,
)


def test_chunk_stream_key_format():
    assert chunk_stream_key("abc-123") == "temper:chunks:abc-123"


def test_chunk_dataclass_defaults():
    c = Chunk(execution_id="x", agent_id="a", content="hi")
    assert c.chunk_type == "content"
    assert c.done is False


# --- Degraded mode (no Redis) ---------------------------------------------

class TestDegradedMode:
    """Behavior when no Redis URL is configured. All ops must no-op
    silently — the worker keeps running."""

    @pytest.fixture(autouse=True)
    def _no_redis(self, monkeypatch):
        monkeypatch.delenv("TEMPER_REDIS_URL", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)

    def test_publisher_disabled(self):
        pub = RedisChunkPublisher()
        assert pub.enabled is False

    def test_publish_is_silent_no_op(self):
        pub = RedisChunkPublisher()
        # Must not raise even with extreme inputs
        pub.publish("e", "agent", "x" * 10000, chunk_type="content", done=False)
        pub.publish_terminal("e")
        pub.close()

    def test_subscriber_disabled(self):
        sub = RedisChunkSubscriber()
        assert sub.enabled is False

    @pytest.mark.asyncio
    async def test_subscribe_yields_nothing_when_disabled(self):
        sub = RedisChunkSubscriber()
        chunks = []
        async for chunk in sub.subscribe("anything"):
            chunks.append(chunk)
        assert chunks == []
        await sub.close()


# --- Real Redis (skip if not configured) ----------------------------------

REDIS_URL = os.environ.get("TEMPER_REDIS_URL") or os.environ.get("REDIS_URL")


@pytest.mark.skipif(
    REDIS_URL is None,
    reason="No TEMPER_REDIS_URL configured — Redis-backed tests skipped",
)
class TestRoundTrip:
    """End-to-end publish → XREAD round trip against a real Redis."""

    @pytest.fixture
    def execution_id(self):
        # Unique per test run so parallel tests don't see each other's chunks
        import uuid
        eid = f"test-{uuid.uuid4()}"
        yield eid
        # Cleanup
        try:
            import redis
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            r.delete(chunk_stream_key(eid))
        except Exception:
            pass

    def test_publish_appears_in_subscribe(self, execution_id):
        pub = RedisChunkPublisher(REDIS_URL)
        pub.publish(execution_id, "agent-A", "hello world", "content", False)
        pub.publish_terminal(execution_id)
        pub.close()

        async def _read():
            sub = RedisChunkSubscriber(REDIS_URL)
            collected = []
            async for chunk in sub.subscribe(execution_id):
                collected.append(chunk)
                if chunk.chunk_type == "terminal":
                    break
            await sub.close()
            return collected

        chunks = asyncio.run(_read())
        assert len(chunks) >= 2
        first = chunks[0]
        assert first.agent_id == "agent-A"
        assert first.content == "hello world"
        assert chunks[-1].chunk_type == "terminal"

    def test_terminal_sentinel_unblocks_subscriber(self, execution_id):
        """Subscriber should exit promptly when terminal arrives."""
        pub = RedisChunkPublisher(REDIS_URL)
        pub.publish_terminal(execution_id)
        pub.close()

        async def _read():
            sub = RedisChunkSubscriber(REDIS_URL)
            try:
                async for chunk in sub.subscribe(execution_id):
                    return chunk
            finally:
                await sub.close()

        chunk = asyncio.run(asyncio.wait_for(_read(), timeout=2.0))
        assert chunk.chunk_type == "terminal"

    def test_stream_maxlen_bounded(self, execution_id):
        """MAXLEN ~ N trim keeps the stream from growing unbounded.

        We write enough entries (1000 with MAXLEN=10) that approximate trim
        has plenty of opportunities to run; the stream should end up well
        under the write count. Exact bound depends on Redis's macro-node
        size — 100 is safely above the trim threshold but well below 1000.
        """
        pub = RedisChunkPublisher(REDIS_URL, maxlen=10)
        for i in range(1000):
            pub.publish(execution_id, "agent", f"chunk {i}")
        pub.close()

        import redis
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        length = r.xlen(chunk_stream_key(execution_id))
        assert length < 1000  # trim definitely ran
        assert length < 200   # held well below 10x maxlen
