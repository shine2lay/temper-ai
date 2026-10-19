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

from .support import HERE, NODE, Host, ask_in_process, login, now_ms, tph

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


def real_config(host: Host, endpoint: FakeTokenEndpoint, allowed: tuple[str, ...] = (SLOT, OTHER),
                **bridge_over) -> tph.Config:
    sdk, ai = sdk_versions()
    raw = host.config(base_provider=BASE, allowed_slots=list(allowed))
    raw["bridge"] = {**raw["bridge"], "node": node_wrapper(host, endpoint), "sdk_root": SDK_ROOT,
                     "sdk_version": sdk, "ai_version": ai, **bridge_over}
    return tph.parse_config(raw)


def real_bridge(host: Host, endpoint: FakeTokenEndpoint, bridges: list,
                allowed: tuple[str, ...] = (SLOT, OTHER), **bridge_over) -> tph.Bridge:
    bridge = tph.Bridge(real_config(host, endpoint, allowed, **bridge_over))
    bridges.append(bridge)
    return bridge


def chat_asks(host: Host, endpoint: FakeTokenEndpoint, slot: str, go_at: int) -> subprocess.Popen:
    """A chat (the SDK as the chat app uses it) asking for ``slot``'s login at ``go_at``."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(host.root), "LANG": "C.UTF-8",
           "PI_CODING_AGENT_DIR": str(host.agent), "PI_OFFLINE": "1", "TPH_FAKE_TOKEN_URL": endpoint.url}
    return subprocess.Popen([NODE, "--import", (HERE / "fake_fetch.mjs").as_uri(), str(HERE / "chat_side.mjs"),
                             SDK_ROOT, str(host.agent), slot, BASE, str(go_at)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=str(host.root))


def lock_dir(host: Host) -> Path:
    return Path(str(host.auth) + ".lock")


def test_happy_path_temper_picks_account_1_and_the_helper_serves_it_and_an_alias(
        host, endpoint, bridges, tmp_path):
    """The whole change at once (the owner's decision dr-393b503dcdff replaced ADR-M4-14's
    refusal of account 1). Temper's team settings name account 1 and the run takes it; a
    helper listing account 1 and an alias serves both through the real bridge over the real
    pinned SDK, from a synthetic auth store. Account 1's due login is refreshed once, by the
    SDK's built-in flow under auth.json's lock, and no other entry changes."""
    import yaml

    from temper_ai.pi_agent.accounts import choose
    from temper_ai.pi_agent.team_config import TEAM_DIR, load_team_config

    settings = tmp_path / "configs" / TEAM_DIR / "team.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text(yaml.safe_dump({"account_slots": [BASE], "account_pick": "settings_order"}))
    cfg = load_team_config(tmp_path / "configs")
    assert cfg.problems == () and cfg.account_slots == (BASE,)
    picked = choose({}, config=cfg)["slot"]
    assert picked == BASE

    alias_login = login("alias-access", "alias-refresh", 2 * 3600 * 1000)
    host.write_auth({BASE: login("old-base-access", "old-base-refresh", 2 * 60 * 1000), SLOT: alias_login})
    helper = tph.Helper(real_config(host, endpoint, allowed=(BASE, SLOT)))
    bridges.append(helper.bridge)
    assert ask_in_process(helper, f"token {picked}") == "ok new-access-1"
    assert ask_in_process(helper, f"token {SLOT}") == "ok alias-access"
    assert ask_in_process(helper, f"token {OTHER}") == f"denied slot {OTHER} is not one this helper serves"
    assert [call["refresh_token"] for call in endpoint.calls] == ["old-base-refresh"]
    stored = host.read_auth()
    assert set(stored) == {BASE, SLOT} and stored[SLOT] == alias_login
    assert (stored[BASE]["type"], stored[BASE]["access"], stored[BASE]["refresh"]) == (
        "oauth", "new-access-1", "new-refresh-1")
    assert not lock_dir(host).exists()
    assert ask_in_process(helper, f"token {BASE}") == "ok new-access-1"  # fresh now: no refresh
    assert len(endpoint.calls) == 1


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
    chat = chat_asks(host, endpoint, SLOT, go_at)
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


def test_the_chats_and_the_bridge_refresh_account_1_once_between_them(host, endpoint, bridges):
    """Account 1's login, due, asked for at the same moment by a chat (the SDK's built-in
    provider, untouched, as the chat app uses it) and by the bridge (the same built-in
    provider, nothing registered): exactly one refresh under auth.json's lock, both get the
    same new login, and the alias's entry is byte-for-byte what it was."""
    alias_login = login("alias-access", "alias-refresh", 2 * 3600 * 1000)
    host.write_auth({BASE: login("old-access", "old-refresh", 2 * 60 * 1000), SLOT: alias_login})
    bridge = real_bridge(host, endpoint, bridges, allowed=(BASE, SLOT))
    bridge.start()
    go_at = now_ms() + 2500
    chat = chat_asks(host, endpoint, BASE, go_at)
    time.sleep(max(0.0, (go_at - now_ms()) / 1000))
    ours = bridge.request("token", BASE, 30)
    out, _ = chat.communicate(timeout=60)
    theirs = json.loads(out.decode().strip().splitlines()[-1])
    assert len(endpoint.calls) == 1, endpoint.calls
    assert endpoint.calls[0]["refresh_token"] == "old-refresh"
    assert ours == {"id": 1, "ok": True, "slot": BASE, "token": "new-access-1"}
    assert theirs == {"token": "new-access-1"}
    stored = host.read_auth()
    assert (stored[BASE]["access"], stored[BASE]["refresh"]) == ("new-access-1", "new-refresh-1")
    assert stored[SLOT] == alias_login and set(stored) == {BASE, SLOT}
    assert not lock_dir(host).exists()


@pytest.mark.parametrize("slot, setup, reason", [
    (BASE, None, "not_served"),  # account 1, not listed
    (BASE, "base_listed", "no_login"),
    (BASE, "base_listed_failing_refresh", "refresh_failed"),
    (f"{BASE}-9", None, "not_served"),
    (OTHER, "unregistered", "not_registered"),
    (OTHER, None, "no_login"),
    (SLOT, "api_key", "not_oauth"),
    (SLOT, "failing_refresh", "refresh_failed"),
])
def test_each_refusal_names_the_slot(host, bridges, slot, setup, reason):
    endpoint = FakeTokenEndpoint(delay_s=0, fail=(setup or "").endswith("failing_refresh"))
    try:
        if setup == "unregistered":
            (host.agent / "multi-pass.json").write_text(json.dumps({"subscriptions": [{"provider": BASE, "index": 5}]}))
        elif setup == "api_key":
            host.write_auth({SLOT: {"type": "api_key", "key": "some-key"}})
        elif setup == "failing_refresh":
            host.write_auth({SLOT: login("old-access", "old-refresh", 60 * 1000)})
        elif setup == "base_listed_failing_refresh":
            host.write_auth({BASE: login("old-access", "old-refresh", 60 * 1000)})
        allowed = (BASE, SLOT, OTHER) if (setup or "").startswith("base_listed") else (SLOT, OTHER)
        before = host.auth_state()
        bridge = real_bridge(host, endpoint, bridges, allowed=allowed)
        bridge.start()
        answer = bridge.request("token", slot, 30)
        assert (answer["ok"], answer["slot"], answer["reason"]) == (False, slot, reason)
        assert "token" not in answer and "SECRET-BODY" not in json.dumps(answer)
        assert host.auth_state() == before
        assert len(endpoint.calls) == (1 if (setup or "").endswith("failing_refresh") else 0)
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
