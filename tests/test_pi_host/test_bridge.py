"""The auth bridge (temper_pi_host_bridge.mjs) against a stub Pi SDK: its version checks, the
slot it serves and every refusal.  No real login, no network, no model call."""

from __future__ import annotations

import json
import os
import signal
import time

import pytest

from .support import BASE, NODE, OTHER, SDK_VERSION, SLOT, Host, login, tph

pytestmark = pytest.mark.skipif(NODE is None, reason="the auth bridge needs node")

AUTH_EVENTS = ("runtime-created", "list-credentials", "get-auth", "read-stored", "write-auth")


@pytest.fixture
def host():
    h = Host()
    yield h
    h.cleanup()


@pytest.fixture
def bridges():
    started: list = []
    yield started
    for bridge in started:
        bridge.stop_all()


def bridge_for(host: Host, bridges: list, **over) -> tph.Bridge:
    bridge = tph.Bridge(host.cfg(**over))
    bridges.append(bridge)
    return bridge


def auth_events(events: list[str]) -> list[str]:
    return [e for e in events if e.startswith(AUTH_EVENTS)]


def test_hello_names_the_sdk_it_loaded(host, bridges):
    hello = bridge_for(host, bridges).start()
    assert hello["ok"] is True
    assert hello["package"] == "@earendil-works/pi-coding-agent"
    assert hello["version"] == SDK_VERSION
    assert hello["loaded_version"] == SDK_VERSION
    assert hello["ai_package"] == "@earendil-works/pi-ai"
    assert hello["ai_version"] == SDK_VERSION
    assert hello["node"].startswith("v")
    # Starting reads no login: the SDK is loaded, its auth storage not yet made.
    assert host.events() == ["imported"]


def test_a_different_expected_version_refuses_the_start_before_any_auth(host, bridges):
    before = host.auth_state()
    bridge = bridge_for(host, bridges, bridge={**host.config()["bridge"], "sdk_version": "9.9.9"})
    with pytest.raises(tph.BridgeRefused) as refused:
        bridge.start()
    assert refused.value.code == "sdk_version_mismatch"
    assert refused.value.hello["version"] == SDK_VERSION  # what it found on disk
    assert bridge.proc is None
    assert "imported" not in host.events()  # the SDK was not even loaded
    assert host.auth_state() == before


def test_a_different_providers_version_refuses_the_start(host, bridges):
    bridge = bridge_for(host, bridges, bridge={**host.config()["bridge"], "ai_version": "9.9.9"})
    with pytest.raises(tph.BridgeRefused) as refused:
        bridge.start()
    assert refused.value.code == "sdk_version_mismatch"
    assert refused.value.hello["ai_version"] == SDK_VERSION
    assert "imported" not in host.events()


def test_the_version_evidence_is_the_sdk_on_disk_not_the_config(host, bridges):
    """The hello reports what is installed: change the stub on disk and the same expected
    version is refused, naming the version found."""
    tph.set_stub_version(host.sdk_root, "7.7.8-other")
    bridge = bridge_for(host, bridges)
    with pytest.raises(tph.BridgeRefused) as refused:
        bridge.start()
    assert refused.value.hello["version"] == "7.7.8-other"
    tph.set_stub_version(host.sdk_root, SDK_VERSION)
    assert bridge.start()["version"] == SDK_VERSION


def test_code_that_says_another_version_than_its_package_is_refused(host, bridges):
    """The stub regression: package.json says the expected version but the loaded code's own
    VERSION differs (a half-done upgrade).  The start is refused with both versions named."""
    index = tph.sdk_package_dir(host.sdk_root) / "dist" / "index.js"
    index.write_text(index.read_text().replace(f'VERSION = "{SDK_VERSION}"', 'VERSION = "7.7.9-half"'))
    bridge = bridge_for(host, bridges)
    with pytest.raises(tph.BridgeRefused) as refused:
        bridge.start()
    assert refused.value.code == "sdk_version_mismatch"
    assert refused.value.hello["version"] == SDK_VERSION
    assert refused.value.hello["loaded_version"] == "7.7.9-half"
    assert auth_events(host.events()) == []


def test_an_sdk_it_cannot_read_refuses_the_start(host, bridges):
    bridge = bridge_for(host, bridges, bridge={**host.config()["bridge"], "sdk_root": str(host.root / "nothing")})
    with pytest.raises(tph.BridgeRefused) as refused:
        bridge.start()
    assert refused.value.code == "sdk_unreadable"


def test_an_sdk_without_the_auth_surface_refuses_the_start(host, bridges):
    index = tph.sdk_package_dir(host.sdk_root) / "dist" / "index.js"
    index.write_text(index.read_text().replace("export function readStoredCredential", "function readStoredCredential"))
    with pytest.raises(tph.BridgeRefused) as refused:
        bridge_for(host, bridges).start()
    assert refused.value.code == "sdk_surface"
    assert auth_events(host.events()) == []


def test_it_serves_the_slot_asked_for(host, bridges):
    bridge = bridge_for(host, bridges)
    bridge.start()
    answer = bridge.request("token", SLOT, 10)
    assert answer == {"id": answer["id"], "ok": True, "slot": SLOT, "token": host.canary}
    assert f"register {SLOT}" in host.events()
    # The slot has its own key: the alias was registered under its own name, nothing else.
    assert [e for e in host.events() if e.startswith("register")] == [f"register {SLOT}"]


def test_the_base_slot_account_1_is_served_when_listed_with_nothing_registered(host, bridges):
    """Account 1 is the SDK's own built-in provider (the owner's decision dr-393b503dcdff
    replaced ADR-M4-14's refusal of it): served when listed, nothing registered for it."""
    host.write_auth({BASE: login("BASE-" + host.canary, host.canary_refresh, 2 * 3600 * 1000),
                     SLOT: login(host.canary, host.canary_refresh, 2 * 3600 * 1000)})
    before = host.auth_state()
    bridge = bridge_for(host, bridges, allowed_slots=[BASE, SLOT])
    bridge.start()
    answer = bridge.request("token", BASE, 10)
    assert answer == {"id": answer["id"], "ok": True, "slot": BASE, "token": "BASE-" + host.canary}
    assert [e for e in host.events() if e.startswith("register")] == []
    assert bridge.request("token", SLOT, 10)["token"] == host.canary
    assert [e for e in host.events() if e.startswith("register")] == [f"register {SLOT}"]
    assert host.refreshes() == 0 and host.auth_state() == before


def test_the_base_slot_needs_no_multi_pass_entry(host, bridges):
    (host.agent / "multi-pass.json").write_text("not json")
    host.write_auth({BASE: login(host.canary, host.canary_refresh, 2 * 3600 * 1000)})
    bridge = bridge_for(host, bridges, allowed_slots=[BASE, SLOT])
    bridge.start()
    assert bridge.request("token", BASE, 10)["token"] == host.canary
    assert bridge.request("token", SLOT, 10)["reason"] == "registry_unreadable"


def test_a_base_slot_login_near_expiry_is_refreshed_once_and_no_other_entry_changes(host, bridges):
    """The base slot's refresh is the built-in flow, run by the SDK's own storage (under
    auth.json's lock in the real SDK); only its own entry is rewritten."""
    alias_login = login(host.canary, host.canary_refresh, 2 * 3600 * 1000)
    host.write_auth({BASE: login("old-access", "old-refresh", 10 * 60 * 1000), SLOT: alias_login})
    host.control(next_access="new-access", next_refresh="new-refresh")
    bridge = bridge_for(host, bridges, allowed_slots=[BASE, SLOT])
    bridge.start()
    assert bridge.request("token", BASE, 10)["token"] == "new-access"
    assert host.refreshes() == 1
    stored = host.read_auth()
    assert (stored[BASE]["access"], stored[BASE]["refresh"]) == ("new-access", "new-refresh")
    assert stored[SLOT] == alias_login and set(stored) == {BASE, SLOT}
    assert bridge.request("token", BASE, 10)["token"] == "new-access"
    assert host.refreshes() == 1


def test_a_login_near_expiry_is_refreshed_once_through_the_sdk(host, bridges):
    host.write_auth({SLOT: login("old-access", "old-refresh", 10 * 60 * 1000)})  # 10 min < 30 min
    host.control(next_access="new-access", next_refresh="new-refresh")
    bridge = bridge_for(host, bridges)
    bridge.start()
    answer = bridge.request("token", SLOT, 10)
    assert answer["ok"] is True and answer["token"] == "new-access"
    assert host.refreshes() == 1
    stored = host.read_auth()[SLOT]
    assert (stored["access"], stored["refresh"]) == ("new-access", "new-refresh")
    # Fresh now: the next request is served without another refresh.
    assert bridge.request("token", SLOT, 10)["token"] == "new-access"
    assert host.refreshes() == 1


@pytest.mark.parametrize("slot, setup, reason", [
    (BASE, None, "not_served"),  # account 1 is served only when listed, like any slot
    (BASE, "base_listed", "no_login"),
    (BASE, "base_listed_api_key", "not_oauth"),
    (BASE, "base_listed_failing_refresh", "refresh_failed"),
    ("acme-9", None, "not_served"),
    ("other-2", None, "not_alias"),
    ("acme-1", None, "not_alias"),
    ("a/b", None, "bad_slot"),
    (OTHER, "unregistered", "not_registered"),
    (OTHER, "bad_registry", "registry_unreadable"),
    (OTHER, None, "no_login"),
    (SLOT, "api_key", "not_oauth"),
    (SLOT, "failing_refresh", "refresh_failed"),
])
def test_each_refusal_names_the_slot_and_serves_nothing(host, bridges, slot, setup, reason):
    if setup == "unregistered":
        host.register(2)
    elif setup == "bad_registry":
        (host.agent / "multi-pass.json").write_text("not json")
    elif setup == "api_key":
        host.write_auth({SLOT: {"type": "api_key", "key": host.canary}})
    elif setup == "failing_refresh":
        host.write_auth({SLOT: login(host.canary, host.canary_refresh, 60 * 1000)})
        host.control(refresh="fail")
    elif setup == "base_listed_api_key":
        host.write_auth({BASE: {"type": "api_key", "key": host.canary}})
    elif setup == "base_listed_failing_refresh":
        host.write_auth({BASE: login(host.canary, host.canary_refresh, 60 * 1000)})
        host.control(refresh="fail")
    over = {"allowed_slots": [BASE, SLOT, OTHER]} if (setup or "").startswith("base_listed") else {}
    before = host.auth_state()
    bridge = bridge_for(host, bridges, **over)
    bridge.start()
    answer = bridge.request("token", slot, 10)
    assert answer["ok"] is False
    assert answer["reason"] == reason
    assert answer["slot"] == slot
    assert "token" not in answer
    text = json.dumps(answer)
    assert host.canary not in text and "STUB-SECRET-BODY" not in text  # never SDK error text
    assert host.auth_state() == before


@pytest.mark.parametrize("slot", [SLOT, BASE])
def test_the_sdk_changing_on_disk_refuses_the_next_mint_without_touching_auth_json(host, bridges, slot):
    """The per-request check: a stubbed mint works, the SDK on disk changes (as a pi-web-ui
    upgrade under a running helper would), the next mint is refused and auth.json is
    byte-identical with the same mtime; nothing of auth.json was read after the change.
    The same for an alias and for the base slot (account 1)."""
    host.write_auth({s: login(host.canary, host.canary_refresh, 2 * 3600 * 1000) for s in (BASE, SLOT)})
    bridge = bridge_for(host, bridges, allowed_slots=[BASE, SLOT])
    bridge.start()
    assert bridge.request("token", slot, 10)["token"] == host.canary
    before = host.auth_state()
    mark = len(host.events())
    tph.set_stub_version(host.sdk_root, "7.7.8-upgraded")
    answer = bridge.request("token", slot, 10)
    assert answer["ok"] is False
    assert (answer["reason"], answer["found_version"], answer["slot"]) == ("sdk_changed", "7.7.8-upgraded", slot)
    assert "token" not in answer
    assert host.auth_state() == before
    assert auth_events(host.events()[mark:]) == []
    status = bridge.request("status", "", 10)
    assert status["state"] == "sdk_changed"
    assert auth_events(host.events()[mark:]) == []


def test_the_providers_package_changing_on_disk_refuses_the_next_mint(host, bridges):
    bridge = bridge_for(host, bridges)
    bridge.start()
    before = host.auth_state()
    tph.set_stub_version(host.sdk_root, "7.7.8-upgraded", package="@earendil-works/pi-ai")
    answer = bridge.request("token", SLOT, 10)
    assert (answer["ok"], answer["reason"], answer["found_version"]) == (False, "sdk_changed", "ai:7.7.8-upgraded")
    assert host.auth_state() == before


def test_the_check_inside_the_refresh_stops_a_refresh_after_a_change(host, bridges):
    """The SDK changes on disk between the request's first check and the refresh: the refresh
    callback checks again (under auth.json's lock in the real SDK) and the refresh never runs."""
    host.write_auth({SLOT: login("old-access", "old-refresh", 60 * 1000)})
    host.control(refresh="bump-before-refresh")
    before = host.auth_state()
    bridge = bridge_for(host, bridges)
    bridge.start()
    answer = bridge.request("token", SLOT, 10)
    assert (answer["ok"], answer["reason"], answer["slot"]) == (False, "sdk_changed", SLOT)
    assert host.refreshes() == 0
    assert host.auth_state() == before


def test_the_base_slot_refresh_is_the_builtin_flow_with_no_check_of_the_bridge_inside(host, bridges):
    """Account 1's refresh is the SDK's built-in flow, untouched, as the chats run it: the
    bridge has no callback in it, so its versions are checked only before the request (the
    documented difference from an alias; docs/pi-host-helper.md)."""
    host.write_auth({BASE: login("old-access", "old-refresh", 60 * 1000)})
    host.control(refresh="bump-before-refresh", next_access="new-access")
    bridge = bridge_for(host, bridges, allowed_slots=[BASE, SLOT])
    bridge.start()
    assert bridge.request("token", BASE, 10)["token"] == "new-access"
    assert host.refreshes() == 1
    # The very next request sees the change and is refused before any auth read.
    assert bridge.request("token", BASE, 10)["reason"] == "sdk_changed"


def test_status_words(host, bridges):
    host.write_auth({SLOT: login(host.canary, host.canary_refresh, 2 * 3600 * 1000),
                     OTHER: login("x", "y", 60 * 1000)})
    bridge = bridge_for(host, bridges, allowed_slots=[BASE, SLOT, OTHER])
    bridge.start()
    answer = bridge.request("status", "", 10)
    assert answer["ok"] is True and answer["state"] == "ready"
    assert answer["slots"] == {BASE: "registered login_missing", SLOT: "registered login_ready",
                               OTHER: "registered login_refresh_due"}
    assert host.canary not in json.dumps(answer)
    assert host.refreshes() == 0  # status never refreshes


def test_it_stops_between_requests_on_sigterm(host, bridges):
    bridge = bridge_for(host, bridges)
    bridge.start()
    proc = bridge.proc
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=10) == 0


def test_its_argv_and_environment_hold_no_login(host, bridges):
    bridge = bridge_for(host, bridges)
    bridge.start()
    assert bridge.request("token", SLOT, 10)["token"] == host.canary
    pid = bridge.proc.pid
    with open(f"/proc/{pid}/cmdline", "rb") as f:
        cmdline = f.read()
    with open(f"/proc/{pid}/environ", "rb") as f:
        environ = f.read()
    assert host.canary.encode() not in cmdline and host.canary.encode() not in environ
    assert sorted(k.split(b"=", 1)[0].decode() for k in environ.split(b"\0") if k) == sorted(
        ["HOME", "LANG", "PATH", "PI_CODING_AGENT_DIR", "PI_OFFLINE", "PI_SKIP_VERSION_CHECK", "PI_TELEMETRY"])
    assert host.files_holding(host.canary, skip=(host.auth,)) == []


def test_a_bridge_that_hangs_is_let_go_and_the_next_one_starts(host, bridges):
    host.write_auth({SLOT: login("old-access", "old-refresh", 60 * 1000)})
    host.control(refresh="hang")
    bridge = bridge_for(host, bridges, bridge={**host.config()["bridge"], "stop_grace_s": 1})
    bridge.start()
    first = bridge.proc
    started = time.monotonic()
    with pytest.raises(tph.BridgeTimeout):
        bridge.request("token", SLOT, 1)
    assert time.monotonic() - started < 5
    assert bridge.proc is None and bridge.retiring
    host.control(next_access="new-access")
    answer = bridge.request("token", SLOT, 10)  # a new bridge, after the start check
    assert answer["ok"] is True and answer["token"] == "new-access"
    assert bridge.proc is not first
    deadline = time.monotonic() + 10
    while first.poll() is None and time.monotonic() < deadline:
        bridge.reap()
        time.sleep(0.1)
    assert first.poll() is not None
    assert os.path.exists(host.auth)
