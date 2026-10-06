"""The auth bridge against the real, pinned Pi SDK (the one the owner's chats load), with a
fake token endpoint, a temp auth.json and synthetic slots.  Never a real login or network
call: a test-only preload sends the SDK's token requests to a local fake and refuses every
other request.

Runs only when TEMPER_PI_HOST_TEST_SDK_ROOT names a folder whose node_modules holds the Pi
SDK (for example the chat app's checkout); CI has no such folder, so there it is skipped and
the stub-SDK tests stand in."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from .support import HERE, NODE, Host, login, now_ms, tph

SDK_ENV = "TEMPER_PI_HOST_TEST_SDK_ROOT"
SDK_ROOT = os.environ.get(SDK_ENV, "")
pytestmark = [
    pytest.mark.skipif(not SDK_ROOT, reason=f"set {SDK_ENV} to a folder holding the Pi SDK"),
    pytest.mark.skipif(NODE is None, reason="the auth bridge needs node"),
    pytest.mark.timeout(90),
]

BASE = "anthropic"  # the SDK's real built-in provider (its OAuth flow); the slots are made up
SLOT = f"{BASE}-5"
OTHER = f"{BASE}-6"


def sdk_versions() -> tuple[str, str]:
    root = Path(SDK_ROOT) / "node_modules" / "@earendil-works"
    sdk = json.loads((root / "pi-coding-agent" / "package.json").read_text())["version"]
    ai = json.loads((root / "pi-ai" / "package.json").read_text())["version"]
    return sdk, ai


class FakeTokenEndpoint:
    """A local stand-in for the OAuth token endpoint: counts refreshes, answers after a delay."""

    def __init__(self, delay_s: float = 0.8, fail: bool = False):
        self.calls: list[dict] = []
        self.delay_s = delay_s
        self.fail = fail
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (http.server's name)
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                endpoint.calls.append(body)
                n = len(endpoint.calls)
                time.sleep(endpoint.delay_s)
                if endpoint.fail:
                    data, code = b"SECRET-BODY-from-the-endpoint", 400
                else:
                    data, code = json.dumps({"access_token": f"new-access-{n}", "refresh_token": f"new-refresh-{n}",
                                             "expires_in": 3600}).encode(), 200
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/token"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def endpoint():
    e = FakeTokenEndpoint()
    yield e
    e.close()


@pytest.fixture
def host():
    h = Host()
    (h.agent / "multi-pass.json").write_text(json.dumps({"subscriptions": [
        {"provider": BASE, "index": 5}, {"provider": BASE, "index": 6}]}))
    h.write_auth({SLOT: login("old-access", "old-refresh", 2 * 3600 * 1000)})
    yield h
    h.cleanup()


@pytest.fixture
def bridges():
    started: list = []
    yield started
    for bridge in started:
        bridge.stop_all()


def node_wrapper(host: Host, endpoint: FakeTokenEndpoint) -> str:
    """A node command for the bridge that preloads the test-only fetch redirect."""
    wrapper = host.root / "node-test"
    wrapper.write_text(f"#!/bin/sh\nexport TPH_FAKE_TOKEN_URL='{endpoint.url}'\n"
                       f"exec '{NODE}' --import '{(HERE / 'fake_fetch.mjs').as_uri()}' \"$@\"\n")
    wrapper.chmod(0o755)
    return str(wrapper)


def real_bridge(host: Host, endpoint: FakeTokenEndpoint, bridges: list, **bridge_over) -> tph.Bridge:
    sdk, ai = sdk_versions()
    raw = host.config(base_provider=BASE, allowed_slots=[SLOT, OTHER])
    raw["bridge"] = {**raw["bridge"], "node": node_wrapper(host, endpoint), "sdk_root": SDK_ROOT,
                     "sdk_version": sdk, "ai_version": ai, **bridge_over}
    bridge = tph.Bridge(tph.parse_config(raw))
    bridges.append(bridge)
    return bridge


def lock_dir(host: Host) -> Path:
    return Path(str(host.auth) + ".lock")


def test_the_hello_names_the_real_sdk(host, endpoint, bridges):
    sdk, ai = sdk_versions()
    hello = real_bridge(host, endpoint, bridges).start()
    assert (hello["package"], hello["version"], hello["loaded_version"]) == (tph.DEFAULT_SDK_PACKAGE, sdk, sdk)
    assert (hello["ai_package"], hello["ai_version"]) == (tph.AI_PACKAGE, ai)


def test_a_fresh_login_is_served_without_the_network(host, endpoint, bridges):
    bridge = real_bridge(host, endpoint, bridges)
    bridge.start()
    assert bridge.request("token", SLOT, 20) == {"id": 1, "ok": True, "slot": SLOT, "token": "old-access"}
    assert endpoint.calls == []
    assert not lock_dir(host).exists()


def test_the_chats_and_the_bridge_refresh_once_between_them(host, endpoint, bridges):
    """A login due for refresh, asked for at the same moment by a chat (the SDK as the chat
    app uses it, the alias registered as pi-multi-pass registers it) and by the bridge:
    exactly one refresh, and both get the same new login."""
    host.write_auth({SLOT: login("old-access", "old-refresh", 2 * 60 * 1000)})  # due for both sides
    bridge = real_bridge(host, endpoint, bridges)
    bridge.start()
    go_at = now_ms() + 2500
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(host.root), "LANG": "C.UTF-8",
           "PI_CODING_AGENT_DIR": str(host.agent), "PI_OFFLINE": "1", "TPH_FAKE_TOKEN_URL": endpoint.url}
    chat = subprocess.Popen([NODE, "--import", (HERE / "fake_fetch.mjs").as_uri(), str(HERE / "chat_side.mjs"),
                             SDK_ROOT, str(host.agent), SLOT, BASE, str(go_at)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=str(host.root))
    time.sleep(max(0.0, (go_at - now_ms()) / 1000))
    ours = bridge.request("token", SLOT, 30)
    out, _ = chat.communicate(timeout=60)
    theirs = json.loads(out.decode().strip().splitlines()[-1])
    assert len(endpoint.calls) == 1, endpoint.calls
    assert endpoint.calls[0]["refresh_token"] == "old-refresh"
    assert ours == {"id": 1, "ok": True, "slot": SLOT, "token": "new-access-1"}
    assert theirs == {"token": "new-access-1"}
    stored = host.read_auth()[SLOT]
    assert (stored["type"], stored["access"], stored["refresh"]) == ("oauth", "new-access-1", "new-refresh-1")
    assert stored["expires"] > now_ms() + 50 * 60 * 1000
    assert not lock_dir(host).exists()


@pytest.mark.parametrize("slot, setup, reason", [
    (BASE, None, "account_1"),
    (f"{BASE}-9", None, "not_served"),
    (OTHER, "unregistered", "not_registered"),
    (OTHER, None, "no_login"),
    (SLOT, "api_key", "not_oauth"),
    (SLOT, "failing_refresh", "refresh_failed"),
])
def test_each_refusal_names_the_slot(host, bridges, slot, setup, reason):
    endpoint = FakeTokenEndpoint(delay_s=0, fail=setup == "failing_refresh")
    try:
        if setup == "unregistered":
            (host.agent / "multi-pass.json").write_text(json.dumps({"subscriptions": [{"provider": BASE, "index": 5}]}))
        elif setup == "api_key":
            host.write_auth({SLOT: {"type": "api_key", "key": "some-key"}})
        elif setup == "failing_refresh":
            host.write_auth({SLOT: login("old-access", "old-refresh", 60 * 1000)})
        before = host.auth_state()
        bridge = real_bridge(host, endpoint, bridges)
        bridge.start()
        answer = bridge.request("token", slot, 30)
        assert (answer["ok"], answer["slot"], answer["reason"]) == (False, slot, reason)
        assert "token" not in answer and "SECRET-BODY" not in json.dumps(answer)
        assert host.auth_state() == before
        assert len(endpoint.calls) == (1 if setup == "failing_refresh" else 0)
    finally:
        endpoint.close()


def test_a_different_expected_version_refuses_before_any_auth(host, endpoint, bridges):
    sdk, _ = sdk_versions()
    before = host.auth_state()
    bridge = real_bridge(host, endpoint, bridges, sdk_version="0.0.0-not-this")
    with pytest.raises(tph.BridgeRefused) as refused:
        bridge.start()
    assert refused.value.code == "sdk_version_mismatch" and refused.value.hello["version"] == sdk
    assert host.auth_state() == before
    assert not lock_dir(host).exists()
