"""The Pi lane view (ADR-M4-21) in tests: a stand-in Redis and pi-worker's write, so a server
outside the Pi lane has a view to read. Nothing reaches the network."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from temper_ai.shared import pi_lane_view

URL = "redis://lane-view.test:6379/0"


class FakeRedis:
    """``get``, ``set`` (with ``ex``) and ``delete`` over a dict, each call's name recorded.
    Any other Redis call is one neither side of the view makes: it fails the test."""

    def __init__(self, *, down: bool = False) -> None:
        self.data: dict[str, Any] = {}
        self.ttl: dict[str, int | None] = {}
        self.calls: list[str] = []
        self.down = down

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.down:
            raise ConnectionError("Redis is down (stand-in)")

    def get(self, key: str) -> Any:
        self._call("get")
        return self.data.get(key)

    def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self._call("set")
        self.data[key], self.ttl[key] = value, ex
        return True

    def delete(self, *keys: str) -> int:
        self._call("delete")
        return sum(self.data.pop(key, None) is not None for key in keys)

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the Pi lane view made a Redis call it never makes: {name}")


def serve(monkeypatch, fake: FakeRedis | None = None) -> FakeRedis:
    """This process's Redis setting pointed at ``fake`` (both sides of the view use it), with
    the server's cached connection dropped now and after the test."""
    fake = fake if fake is not None else FakeRedis()
    monkeypatch.setenv("TEMPER_REDIS_URL", URL)
    monkeypatch.setattr(pi_lane_view, "_connect", lambda url: fake)
    monkeypatch.setattr(pi_lane_view, "_reader", None)
    monkeypatch.setattr(pi_lane_view, "_reader_url", None)
    return fake


def publisher(fake: FakeRedis, config: str | None = None, *,
              preflight: Callable[[], list] = lambda: [], **kw: Any) -> pi_lane_view.Publisher:
    """pi-worker's writer over ``fake``, for the box config at ``config`` (default
    ``TEMPER_PI_BOX_CONFIG``)."""
    path = config or os.environ["TEMPER_PI_BOX_CONFIG"]
    return pi_lane_view.Publisher(URL, preflight=preflight, config_path=lambda: path,
                                  connect=lambda url: fake, **kw)


def publish(monkeypatch, config: str | None = None, *, fake: FakeRedis | None = None) -> FakeRedis:
    """pi-worker's write, now, with its preflight passed: the view of the box config at
    ``config`` (default ``TEMPER_PI_BOX_CONFIG``) in the stand-in Redis this process reads."""
    fake = serve(monkeypatch, fake)
    assert publisher(fake, config).tick() == "published"
    return fake
