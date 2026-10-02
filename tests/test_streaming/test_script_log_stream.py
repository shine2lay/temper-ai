"""Script log rows over Redis: a subprocess worker publishes each saved row, the server reads them
on from where the stream was when a viewer connected, and stops at the run's terminal sentinel.

Unit tests use small fake clients; the round trip at the end needs a real Redis
($TEMPER_REDIS_URL) and skips without one, like tests/test_streaming/test_redis_streams.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest

from temper_ai.observability.script_logs import LIVE_ROW_MAX_BYTES
from temper_ai.streaming import RedisChunkNotifier
from temper_ai.streaming.redis_streams import (
    DEFAULT_SCRIPT_LOG_MAXLEN,
    RedisChunkPublisher,
    RedisChunkSubscriber,
    chunk_stream_key,
    script_log_stream_key,
)


def _row(seq: int, text: str = "hello\n", attempt: str = "a1") -> dict:
    return {"attempt_id": attempt, "seq": seq, "bytes": len(text.encode()),
            "entries": [{"stream": "stdout", "t": "2026-10-02T12:00:00.000+00:00", "text": text}]}


def test_the_stream_key_is_per_run_and_beside_the_chunks():
    assert script_log_stream_key("abc-123") == "temper:scriptlog:abc-123"
    assert script_log_stream_key("abc-123") != chunk_stream_key("abc-123")


@pytest.fixture
def no_redis(monkeypatch):
    monkeypatch.delenv("TEMPER_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)


class TestWithoutRedis:
    def test_publishing_does_nothing(self, no_redis):
        pub = RedisChunkPublisher()
        pub.publish_script_log("e", _row(1))
        pub.publish_terminal("e")

    @pytest.mark.asyncio
    async def test_there_is_no_position_and_nothing_to_read(self, no_redis):
        sub = RedisChunkSubscriber()
        assert await sub.script_log_position("e") is None
        assert [row async for row in sub.subscribe_script_logs("e", from_id="0")] == []
        await sub.close()


# --- The publisher, with a fake client --------------------------------------------------------

class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.calls: list[tuple] = []

    def xadd(self, *args, **kwargs):
        self.calls.append(("xadd", args, kwargs))

    def expire(self, *args):
        self.calls.append(("expire", args, {}))

    def execute(self):
        if self.client.fail:
            raise ConnectionError("redis went away")
        self.client.executed.append(self.calls)


class FakeClient:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.executed: list[list[tuple]] = []
        self.calls: list[tuple] = []

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    def xadd(self, *args, **kwargs):
        self.calls.append(("xadd", args, kwargs))

    def expire(self, *args):
        self.calls.append(("expire", args, {}))


def _publisher(no_redis_env, client) -> RedisChunkPublisher:
    pub = RedisChunkPublisher(ttl_seconds=600)
    pub._client = client
    pub._unhealthy = False
    return pub


class TestPublisher:
    def test_a_row_is_one_short_bounded_entry_that_expires(self, no_redis):
        client = FakeClient()
        _publisher(no_redis, client).publish_script_log("run-1", _row(1, "héllo ✓\n"))
        [[(op1, args1, kw1), (op2, args2, _)]] = client.executed
        assert (op1, args1[0]) == ("xadd", "temper:scriptlog:run-1")
        assert json.loads(args1[1]["row"]) == _row(1, "héllo ✓\n")
        assert "héllo ✓" in args1[1]["row"], "text is kept as written, not escaped"
        assert kw1 == {"maxlen": DEFAULT_SCRIPT_LOG_MAXLEN, "approximate": True}
        assert (op2, args2) == ("expire", ("temper:scriptlog:run-1", 600))

    def test_a_failure_degrades_quietly(self, no_redis):
        pub = _publisher(no_redis, FakeClient(fail=True))
        pub.publish_script_log("run-1", _row(1))
        assert pub.enabled is False
        pub.publish_script_log("run-1", _row(2))  # a no-op from now on

    def test_the_end_of_a_run_ends_its_log_stream_too(self, no_redis):
        client = FakeClient()
        _publisher(no_redis, client).publish_terminal("run-1")
        log_adds = [c for c in client.calls if c[0] == "xadd" and c[1][0] == "temper:scriptlog:run-1"]
        assert [c[1][1] for c in log_adds] == [{"terminal": "1"}]
        assert ("expire", ("temper:scriptlog:run-1", 600), {}) in client.calls


# --- The subscriber, with a fake async client -------------------------------------------------

class FakeAsyncClient:
    def __init__(self, newest=None, reads=None, fail_newest=False):
        self.newest = newest or []
        self.reads = list(reads or [])
        self.fail_newest = fail_newest
        self.read_from: list[str] = []

    async def xrevrange(self, key, count=None):
        if self.fail_newest:
            raise ConnectionError("down")
        return self.newest

    async def xread(self, streams, block=None, count=None):
        [(key, last_id)] = streams.items()
        self.read_from.append(last_id)
        if not self.reads:
            raise ConnectionError("no more scripted reads")
        nxt = self.reads.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return [(key, nxt)] if nxt else []

    async def aclose(self):
        pass

    async def close(self):
        pass


def _subscriber(no_redis_env, client) -> RedisChunkSubscriber:
    sub = RedisChunkSubscriber()
    sub._client = client
    return sub


class TestSubscriber:
    @pytest.mark.asyncio
    async def test_the_position_is_the_newest_entry(self, no_redis):
        assert await _subscriber(no_redis, FakeAsyncClient()).script_log_position("e") == "0"
        newest = [("17-3", {"row": json.dumps(_row(9))})]
        assert await _subscriber(no_redis, FakeAsyncClient(newest=newest)).script_log_position("e") == "17-3"

    @pytest.mark.asyncio
    async def test_an_ended_or_unreadable_stream_has_no_position(self, no_redis):
        ended = FakeAsyncClient(newest=[("18-0", {"terminal": "1"})])
        assert await _subscriber(no_redis, ended).script_log_position("e") is None
        broken = FakeAsyncClient(fail_newest=True)
        assert await _subscriber(no_redis, broken).script_log_position("e") is None

    @pytest.mark.asyncio
    async def test_rows_are_read_on_from_the_position_until_the_end(self, no_redis):
        client = FakeAsyncClient(reads=[
            [],  # nothing yet: block again
            [("21-0", {"row": json.dumps(_row(1))}), ("22-0", {"row": "not json"})],
            [("23-0", {"row": "[1, 2]"}), ("24-0", {"row": json.dumps(_row(2))}),
             ("25-0", {"terminal": "1"}), ("26-0", {"row": json.dumps(_row(3))})],
        ])
        sub = _subscriber(no_redis, client)
        rows = [row async for row in sub.subscribe_script_logs("e", from_id="20-0")]
        assert [r["seq"] for r in rows] == [1, 2]
        assert client.read_from == ["20-0", "20-0", "22-0"]

    @pytest.mark.asyncio
    async def test_a_read_that_fails_ends_the_rows(self, no_redis):
        client = FakeAsyncClient(reads=[[("1-0", {"row": json.dumps(_row(1))})], ConnectionError("gone")])
        rows = [row async for row in _subscriber(no_redis, client).subscribe_script_logs("e", from_id="0")]
        assert [r["seq"] for r in rows] == [1]


# --- The worker's notifier ----------------------------------------------------------------------

class TestNotifier:
    def test_a_small_row_is_published_whole(self):
        published = []

        class Pub:
            def publish_script_log(self, eid, row):
                published.append((eid, row))

        RedisChunkNotifier(Pub()).notify_script_log("run-1", _row(1))
        assert published == [("run-1", _row(1))]

    def test_a_large_row_is_published_without_its_text(self):
        published = []

        class Pub:
            def publish_script_log(self, eid, row):
                published.append(row)

        RedisChunkNotifier(Pub()).notify_script_log("run-1", _row(4, "x" * (LIVE_ROW_MAX_BYTES + 1)))
        [row] = published
        assert row["stub"] is True and "entries" not in row and row["seq"] == 4


# --- Real Redis (skipped without one) ---------------------------------------------------------

REDIS_URL = os.environ.get("TEMPER_REDIS_URL") or os.environ.get("REDIS_URL")


@pytest.mark.skipif(REDIS_URL is None, reason="No TEMPER_REDIS_URL configured — Redis-backed tests skipped")
class TestRoundTrip:
    @pytest.fixture
    def execution_id(self):
        eid = f"test-{uuid.uuid4()}"
        yield eid
        import redis
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        r.delete(script_log_stream_key(eid), chunk_stream_key(eid))

    def test_a_viewer_gets_the_rows_saved_after_it_connected_then_stops(self, execution_id):
        pub = RedisChunkPublisher(REDIS_URL)
        pub.publish_script_log(execution_id, _row(1))
        pub.publish_script_log(execution_id, _row(2))

        async def connect_then_read():
            sub = RedisChunkSubscriber(REDIS_URL)
            try:
                start = await sub.script_log_position(execution_id)
                assert start not in (None, "0")
                pub.publish_script_log(execution_id, _row(3, "après\n"))
                pub.publish_terminal(execution_id)
                return [row async for row in sub.subscribe_script_logs(execution_id, from_id=start)]
            finally:
                await sub.close()

        rows = asyncio.run(asyncio.wait_for(connect_then_read(), timeout=5))
        assert rows == [_row(3, "après\n")]

        async def after_the_end():
            sub = RedisChunkSubscriber(REDIS_URL)
            try:
                return await sub.script_log_position(execution_id)
            finally:
                await sub.close()

        assert asyncio.run(after_the_end()) is None
        pub.close()

    def test_a_new_run_s_stream_reads_from_its_start(self, execution_id):
        async def position():
            sub = RedisChunkSubscriber(REDIS_URL)
            try:
                return await sub.script_log_position(execution_id)
            finally:
                await sub.close()

        assert asyncio.run(position()) == "0"
