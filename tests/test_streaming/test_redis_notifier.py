"""Tests for RedisChunkNotifier — adapter from EventNotifier → publisher."""

from __future__ import annotations

from unittest.mock import MagicMock

from temper_ai.streaming import RedisChunkNotifier
from temper_ai.streaming.redis_streams import RedisChunkPublisher


def test_notify_event_is_no_op():
    """Events go to DB via EventRecorder; notifier ignores them."""
    pub = MagicMock(spec=RedisChunkPublisher)
    notif = RedisChunkNotifier(pub)
    notif.notify_event("e", "anything", {"data": 1})
    pub.publish.assert_not_called()
    pub.publish_terminal.assert_not_called()


def test_notify_stream_chunk_publishes():
    pub = MagicMock(spec=RedisChunkPublisher)
    notif = RedisChunkNotifier(pub)
    notif.notify_stream_chunk("e", "agent-1", "hi", "content", False)
    pub.publish.assert_called_once_with(
        "e", "agent-1", "hi", chunk_type="content", done=False,
    )


def test_cleanup_publishes_terminal():
    pub = MagicMock(spec=RedisChunkPublisher)
    notif = RedisChunkNotifier(pub)
    notif.cleanup("e")
    pub.publish_terminal.assert_called_once_with("e")


def test_close_releases_publisher():
    pub = MagicMock(spec=RedisChunkPublisher)
    notif = RedisChunkNotifier(pub)
    notif.close()
    pub.close.assert_called_once()


def test_default_constructor_uses_env(monkeypatch):
    """Without an explicit publisher, build one from the env. With no Redis
    URL configured this still succeeds — publisher just runs in degraded mode."""
    monkeypatch.delenv("TEMPER_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    notif = RedisChunkNotifier()  # must not raise
    notif.notify_stream_chunk("e", "a", "x")  # no-op; publisher disabled
    notif.cleanup("e")
    notif.close()
