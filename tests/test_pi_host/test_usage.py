"""Read-only usage over the real bridge, pinned checker and Unix socket. Fake fetch only;
synthetic auth store and SDK; no actual account, HTTP, model, profile or room producer."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from .support import (
    BRIDGE,
    HERE,
    NODE,
    SDK_VERSION,
    Host,
    Served,
    ask_in_process,
    login,
    tph,
)

pytestmark = [pytest.mark.skipif(NODE is None, reason="usage needs Node 22.18+"), pytest.mark.timeout(40)]
BASE, SLOT, OTHER = "anthropic", "anthropic-5", "anthropic-6"
RESET = "2030-01-02T03:04:05Z"
CANARY = "PROVIDER-SECRET-BODY"
DIGESTS = {
    "subs-limits.ts": "22a2297e9ad5b493875129a0fb6fa7dea575e7bfb3355d36219f3b9bb73f7489",
    "reset-countdown.ts": "3bb5b9f8171726b8c1ce25b2cd3382e8aa2604490a7bac164299ab104427c8b6",
    "LICENSE": "11b2d9776f60557f994e63fd4daceaadfffb5757502121a50eb301a8e03ec535",
}


def body():
    return {"five_hour": {"utilization": 12.5, "resets_at": RESET},
            "seven_day": {"utilization": 70, "resets_at": None},
            "seven_day_sonnet": {"utilization": 100, "resets_at": RESET},
            "email": "DO-NOT-PUBLISH@example.invalid", "profile": CANARY}


class UsageHost(Host):
    def __init__(self):
        super().__init__()
        tph.write_stub_sdk(self.sdk_root, base=BASE, version=SDK_VERSION)
        (self.agent / "multi-pass.json").write_text(json.dumps({"subscriptions": [
            {"provider": BASE, "index": 5}, {"provider": BASE, "index": 6}]}))
        self.write_auth({SLOT: login(self.canary, self.canary_refresh, 10 * 60_000),
                         OTHER: login("unused-account", "unused-refresh", 3600_000)})
        self.fixture()
        wrapper = self.root / "offline-node"
        wrapper.write_text(f"#!/bin/sh\nexport TPH_USAGE_FIXTURE={shlex.quote(str(self.root))}\n"
                           f"exec {shlex.quote(NODE)} --import {shlex.quote((HERE / 'fake_usage.mjs').as_uri())} \"$@\"\n")
        wrapper.chmod(0o755)
        self.node = str(wrapper)

    def fixture(self, **over):
        data = {"auth": str(self.auth), "slot": SLOT, "sdk_root": str(self.sdk_root), "body": body(), **over}
        (self.root / "usage-fixture.json").write_text(json.dumps(data))

    def raw(self, **over):
        data = self.config(base_provider=BASE, allowed_slots=[SLOT, OTHER], tokens_per_hour=100000)
        data["bridge"]["node"] = self.node
        data.update(over)
        return data

    def fetch_events(self):
        file = self.root / "usage-events.log"
        return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []


@pytest.fixture
def host():
    h = UsageHost()
    yield h
    h.cleanup()


@pytest.fixture
def helpers(host, monkeypatch):
    monkeypatch.setattr(tph, "USAGE_ATTEMPT_TIMEOUT_MS", 50)  # same paths/retry policy, short offline deadlines
    made = []

    def make(**over):
        helper = tph.Helper(tph.parse_config(host.raw(**over)))
        made.append(helper)
        return helper

    yield make
    for helper in made:
        if helper.bridge:
            helper.bridge.stop_all()


def ask(helper, slot=SLOT):
    text = ask_in_process(helper, f"usage {slot}")
    assert text.startswith("ok "), text
    return json.loads(text[3:])


def unchanged(host, before):
    assert host.auth_state() == before
    assert host.refreshes() == 0
    assert host.forbidden_pi_calls() == []
    assert not Path(str(host.auth) + ".lock").exists()
    assert not any(e.startswith(("runtime-created", "register", "list-credentials", "get-auth", "write-auth"))
                   for e in host.events())
    assert {e for e in host.events() if e.startswith("read-stored")} <= {f"read-stored {SLOT}"}
    assert host.files_holding(host.canary, skip=(host.auth,)) == []
    assert host.files_holding(host.canary_refresh, skip=(host.auth,)) == []
    allowed = {"auth.json", "multi-pass.json", "usage-fixture.json", "offline-node", "stub_pi.py",
               "usage-events.log", "stub-events.log", "stub-pi-calls.log", "package.json", "index.js", "all.js"}
    assert {p.name for p in host.root.rglob("*") if p.is_file()} <= allowed
    assert not list(host.root.rglob("*limits*"))
    assert not list(host.root.rglob("*room*"))


def test_fresh_all_and_scoped_windows_no_identity_no_refresh_no_cap(host, helpers, capsys):
    helper = helpers()
    before = host.auth_state()
    began = time.time()
    result = ask(helper)
    assert set(result) == {"status", "observed_at", "windows"}
    assert result["status"] == "ok"
    assert began - 1 <= tph.utc_seconds(result["observed_at"]) <= time.time()
    assert result["windows"] == [
        {"key": "5h", "used_percent": 12.5, "resets_at": RESET},
        {"key": "7d", "used_percent": 70, "resets_at": None},
        {"key": "7d:sonnet", "used_percent": 100, "resets_at": RESET},
    ]
    assert helper.ceiling.used() == 0 and helper.cfg.tokens_per_hour == 100000
    assert host.fetch_events() == [{"usage": True, "authorised": True, "noRedirect": True}]
    assert host.events().count(f"read-stored {SLOT}") == 2
    text = json.dumps(result) + capsys.readouterr().err
    for secret in [host.canary, host.canary_refresh, CANARY, "DO-NOT-PUBLISH", "profile", "email"]:
        assert secret not in text
    unchanged(host, before)


def test_new_scoped_format_preserved_overall_zero_does_not_erase_scoped_limit(host, helpers):
    data = {"limits": [
        {"kind": "session", "percent": 0, "resets_at": None},
        {"kind": "weekly_all", "percent": 0, "resets_at": None},
        {"kind": "weekly_scoped", "percent": 100, "resets_at": RESET,
         "scope": {"model": {"display_name": "Claude Sonnet", "id": "sonnet"}}},
        {"kind": "weekly_scoped", "percent": 5, "resets_at": None, "scope": {"model": {"id": "opus"}}},
    ]}
    host.fixture(body=data)
    result = ask(helpers())
    assert result["status"] == "ok"
    assert [(w["key"], w["used_percent"]) for w in result["windows"]] == [
        ("5h", 0), ("7d", 0), ("7d:claude-sonnet", 100), ("7d:opus", 5)]


@pytest.mark.parametrize("field,value", [
    ("five_hour", None), ("seven_day", None),
    ("five_hour", {"utilization": "12", "resets_at": RESET}),
    ("five_hour", {"utilization": True, "resets_at": RESET}),
    ("five_hour", {"utilization": -1, "resets_at": RESET}),
    ("five_hour", {"utilization": 101, "resets_at": RESET}),
    ("five_hour", {"utilization": 10, "resets_at": "not a date " + CANARY}),
    ("five_hour", {"utilization": 10, "resets_at": "2030-02-30T00:00:00Z"}),
    ("five_hour", {"utilization": 10}),
    ("seven_day_sonnet", {"utilization": "100", "resets_at": RESET}),
    ("seven_day_sonnet", {"utilization": 100, "resets_at": 0}),
])
def test_missing_or_malformed_windows_never_partially_succeed(host, helpers, field, value):
    data = body()
    data[field] = value
    host.fixture(body=data)
    before = host.auth_state()
    result = ask(helpers())
    reason = "incomplete_reading" if value is None else "check_failed"
    assert result == {"status": "unavailable", "reason": reason}
    unchanged(host, before)


@pytest.mark.parametrize("reset", [
    "2030-01-02T24:00:00Z", "2030-01-02T24:00:00.000+00:00",
    "2030-01-02T23:60:00Z", "2030-01-02T23:59:60Z",
    "2030-01-02T03:04:05+24:00", "2030-01-02T03:04:05-24:00",
    "2030-01-02T03:04:05+00:60", "2030-01-02T03:04:05-00:60",
])
@pytest.mark.parametrize("new_format", [False, True])
def test_raw_clock_and_offset_components_never_repaired(host, helpers, reset, new_format):
    if new_format:
        data = {"limits": [{"kind": "session", "percent": 12.5, "resets_at": reset},
                           {"kind": "weekly_all", "percent": 70, "resets_at": None}]}
    else:
        data = body()
        data["five_hour"]["resets_at"] = reset
    host.fixture(body=data)
    before = host.auth_state()
    assert ask(helpers()) == {"status": "unavailable", "reason": "check_failed"}
    unchanged(host, before)


@pytest.mark.parametrize("reset", ["2030-01-02T05:04:05+02:00", "2030-01-02T02:04:05-01:00",
                                   "2030-01-02T03:04:05.999Z"])
def test_valid_reset_offsets_and_fractions_normalised_to_utc_seconds(host, helpers, reset):
    data = body()
    data["five_hour"]["resets_at"] = reset
    host.fixture(body=data)
    result = ask(helpers())
    assert result["status"] == "ok" and result["windows"][0]["resets_at"] == RESET


@pytest.mark.parametrize("extra", [
    {"limits": "not a list"},
    {"limits": [{"kind": "weekly_scoped", "percent": 1, "resets_at": None, "scope": {"model": {}}}]},
    {"limits": [{"kind": "weekly_all", "percent": 0, "resets_at": None}]},  # conflicts with 70
    {"limits": [{"kind": "weekly_scoped", "percent": 2, "resets_at": None}]},
    {"limits": [None]},
    {"limits": [{}] * 33},
])
def test_malformed_or_conflicting_scoped_data_not_dropped(host, helpers, extra):
    host.fixture(body={**body(), **extra})
    assert ask(helpers()) == {"status": "unavailable", "reason": "check_failed"}


@pytest.mark.parametrize("model", ["bad", [], ["sonnet"], True, 7, {}])
def test_surface_cannot_hide_supplied_malformed_model_scope(host, helpers, model):
    host.fixture(body={**body(), "limits": [{"kind": "weekly_scoped", "percent": 1, "resets_at": None,
                                           "scope": {"model": model, "surface": {}}}]})
    before = host.auth_state()
    assert ask(helpers()) == {"status": "unavailable", "reason": "check_failed"}
    unchanged(host, before)


@pytest.mark.parametrize("scope", [{"surface": {}}, {"model": None, "surface": {}}])
def test_surface_only_absent_or_null_model_is_not_a_model_weekly_window(host, helpers, scope):
    host.fixture(body={**body(), "limits": [{"kind": "weekly_scoped", "percent": 1, "resets_at": None,
                                           "scope": scope}]})
    result = ask(helpers())
    assert result["status"] == "ok"
    assert [(w["key"], w["used_percent"]) for w in result["windows"]] == [
        ("5h", 12.5), ("7d", 70), ("7d:sonnet", 100)]


@pytest.mark.parametrize("data,reason", [
    ({}, "signed_out"),
    ({SLOT: {"type": "api_key", "key": CANARY}}, "not_subscription"),
    ({SLOT: login("expired", "refresh", -1)}, "sign_in_expired"),
    ({SLOT: {"type": "oauth", "access": "x"}}, "sign_in_expired"),
    ({SLOT: {"type": "oauth", "access": "", "expires": 9999999999999}}, "sign_in_expired"),
])
def test_invalid_credentials_unavailable_without_network_or_refresh(host, helpers, data, reason):
    host.write_auth(data)
    before = host.auth_state()
    assert ask(helpers()) == {"status": "unavailable", "reason": reason}
    assert host.fetch_events() == []
    unchanged(host, before)


@pytest.mark.parametrize("status,reason,calls", [(401, "sign_in_expired", 1), (403, "check_failed", 1),
                                               (429, "busy", 2), (500, "no_answer", 2), (302, "check_failed", 1)])
def test_http_errors_and_rate_limits_fixed_reasons(host, helpers, capsys, status, reason, calls):
    host.fixture(statuses=[status], raw=CANARY)
    before = host.auth_state()
    assert ask(helpers()) == {"status": "unavailable", "reason": reason}
    assert len(host.fetch_events()) == calls
    assert CANARY not in capsys.readouterr().err
    unchanged(host, before)


@pytest.mark.parametrize("fixture,reason", [({"error": True}, "no_answer"), ({"hang": True}, "timeout"),
                                            ({"hang_body": True}, "timeout"), ({"raw": CANARY}, "check_failed")])
def test_network_timeout_body_timeout_and_parse_failure(host, helpers, fixture, reason):
    host.fixture(**fixture)
    assert ask(helpers()) == {"status": "unavailable", "reason": reason}


def test_no_stale_windows_after_success_then_failure(host, helpers):
    helper = helpers()
    assert ask(helper)["status"] == "ok"
    host.fixture(statuses=[500], raw=CANARY)
    assert ask(helper) == {"status": "unavailable", "reason": "no_answer"}


def test_one_retry_can_succeed(host, helpers):
    host.fixture(statuses=[429, 200])
    assert ask(helpers())["status"] == "ok"
    assert len(host.fetch_events()) == 2


def test_changed_login_not_rechecked_or_refreshed(host, helpers):
    before = host.auth_state()
    host.fixture(change_login=True)
    assert ask(helpers()) == {"status": "unavailable", "reason": "login_changed"}
    assert host.auth_state() != before  # the fake other chat changed it, not the bridge
    assert host.refreshes() == 0 and len(host.fetch_events()) == 1
    assert not any(e.startswith("write-auth") for e in host.events())


def test_sdk_change_during_usage_discards_reading(host, helpers):
    host.fixture(change_sdk=True)
    before = host.auth_state()
    assert ask(helpers()) == {"status": "unavailable", "reason": "sdk_changed"}
    unchanged(host, before)


def test_sdk_drift_before_request_reads_no_auth(host, helpers):
    helper = helpers()
    helper.bridge.start()
    tph.set_stub_version(host.sdk_root, "7.7.8-drift")
    before = host.auth_state()
    assert ask(helper) == {"status": "unavailable", "reason": "sdk_changed"}
    assert not any(e.startswith("read-stored") for e in host.events())
    assert host.fetch_events() == []
    unchanged(host, before)


@pytest.mark.parametrize("slot,reason", [(BASE, "account 1"), ("anthropic-9", "not one this helper serves"),
                                        ("acme-2", "not an alias"), ("a/b", "malformed"), (OTHER, "not registered")])
def test_alias_and_registration_refused_before_auth(host, helpers, slot, reason):
    (host.agent / "multi-pass.json").write_text(json.dumps({"subscriptions": [{"provider": BASE, "index": 5}]}))
    helper = helpers()
    answer = ask_in_process(helper, f"usage {slot}")
    assert answer.startswith("denied ") and reason in answer
    assert helper.ceiling.used() == 0
    assert not any(e.startswith("read-stored") for e in host.events())
    assert host.fetch_events() == []


@pytest.mark.parametrize("sdk_failure", ["changed", "unreadable"])
@pytest.mark.parametrize("registry,reason", [({"subscriptions": []}, "not_registered"),
                                          (None, "registry_unreadable")])
def test_registration_denial_precedes_sdk_skew_in_already_started_bridge(host, helpers, sdk_failure, registry, reason):
    helper = helpers()
    helper.bridge.start()
    before = host.auth_state()
    if sdk_failure == "changed":
        tph.set_stub_version(host.sdk_root, "7.7.8-drift")
    else:
        (tph.sdk_package_dir(host.sdk_root) / "package.json").unlink()
    (host.agent / "multi-pass.json").write_text(json.dumps(registry) if registry is not None else "{")
    response = helper.bridge.request("usage", SLOT, 10)
    assert response["ok"] is False and response["reason"] == reason
    assert ask_in_process(helper, f"usage {SLOT}") == "denied " + tph.refusal(reason, SLOT, helper.cfg)
    assert not any(e.startswith("read-stored") for e in host.events())
    assert host.fetch_events() == [] and helper.ceiling.used() == 0
    unchanged(host, before)


def uid_answer(path, line=None):
    """One connection to a helper that doesn't serve this uid. It answers before it reads
    anything and closes, maybe before ``line`` is sent: the send can then fail (broken pipe)
    while its answer is still there to read."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(30)
        conn.connect(path)
        if line is not None:
            try:
                conn.sendall((line + "\n").encode())
            except (BrokenPipeError, ConnectionResetError):
                pass
        data = b""
        while b"\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        return data.decode()


def test_uid_refusal_over_actual_unix_socket_precedes_every_other_check(host):
    server = Served(host, host.raw(uid=os.getuid() + 1))
    denial = f"denied uid {os.getuid()} is not served\n"
    try:
        assert server.wait_ready()
        assert uid_answer(server.socket) == denial  # no request sent at all: still denied
        assert uid_answer(server.socket, f"usage {SLOT}") == denial
        assert host.fetch_events() == [] and not any(e.startswith("read-stored") for e in host.events())
    finally:
        assert server.stop() == 0
    assert server.log().count(" why=uid ") == 2 and " verb=usage " not in server.log()


def test_ask_cli_explicit_slot_and_legacy_status(host):
    server = Served(host, host.raw())
    try:
        assert server.wait_ready()
        cmd = [sys.executable, str(tph.__file__), "ask", "--socket", server.socket]
        result = subprocess.run([*cmd, "usage", "--slot", SLOT], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0 and json.loads(result.stdout[3:])["status"] == "ok"
        for args in [["usage"], ["status", "--slot", SLOT]]:
            bad = subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=20)
            assert bad.returncode == 2
        assert server.ask("usage") == "denied the request is not one this helper knows"
        assert server.ask("usage anthropic-5 extra") == "denied the request is not one this helper knows"
        state = json.loads(server.ask("status")[3:])
        assert state["protocol"] == 1 and state["tokens_per_hour"] == 100000 and state["tokens_last_hour"] == 0
        assert state["slots"][SLOT]["bridge"] == "registered login_refresh_due"
        for secret in [host.canary, host.canary_refresh, CANARY]:
            assert secret not in server.log() and secret not in result.stdout
    finally:
        assert server.stop() == 0


def test_bridge_defence_and_bad_auth_never_pass_exception_text(host, helpers):
    helper = helpers()
    helper.bridge.start()
    result = helper.bridge.request("usage", BASE, 10)
    assert result["ok"] is False and result["reason"] == "account_1"
    index = tph.sdk_package_dir(host.sdk_root) / "dist/index.js"
    index.write_text(index.read_text().replace('note("read-stored " + providerId);',
                                              'throw new Error("STUB-SECRET-BODY");'))
    helper.bridge.stop_all()  # load the modified synthetic SDK in a fresh bridge
    assert ask(helper) == {"status": "unavailable", "reason": "auth_unreadable"}


def test_vendor_byte_identity_and_license():
    folder = BRIDGE.parent / "vendor/pi-multi-pass-b8423d2"
    for file, digest in DIGESTS.items():
        assert hashlib.sha256((folder / file).read_bytes()).hexdigest() == digest
    provenance = (folder / "VENDOR.md").read_text()
    assert "b8423d27d71e557483319061724528a4b88a83b6" in provenance
    assert "hjanuschka" in (folder / "LICENSE").read_text()


@pytest.mark.parametrize("vendor", ["missing", "byte_changed"])
def test_vendor_integrity_refusal_without_auth_or_network(host, helpers, vendor):
    folder = host.root / "changed-bridge"
    folder.mkdir()
    script = folder / BRIDGE.name
    script.write_bytes(BRIDGE.read_bytes())  # no edits to the source copy
    if vendor == "byte_changed":
        source = BRIDGE.parent / "vendor/pi-multi-pass-b8423d2"
        target = folder / "vendor/pi-multi-pass-b8423d2"
        target.mkdir(parents=True)
        for name in ["subs-limits.ts", "reset-countdown.ts"]:
            target.joinpath(name).write_bytes(source.joinpath(name).read_bytes())
        changed = target / "subs-limits.ts"
        # Still loadable: without the digest loop this checker imports and would read auth/fetch.
        changed.write_bytes(changed.read_bytes() + b"\n// Harmless offline byte-change fixture.\n")
    raw = host.raw()
    raw["bridge"]["script"] = str(script)
    helper = helpers(bridge=raw["bridge"])
    before = host.auth_state()
    assert ask(helper) == {"status": "unavailable", "reason": "checker_unreadable"}
    assert host.fetch_events() == [] and not any(e.startswith("read-stored") for e in host.events())
    assert host.auth_state() == before and host.refreshes() == 0 and helper.ceiling.used() == 0
    assert host.forbidden_pi_calls() == []


@pytest.mark.parametrize("mutation,reason", [
    (lambda a: a.update(observed_at="2000-01-01T00:00:00Z"), "stale_reading"),
    (lambda a: a["windows"].pop(1), "incomplete_reading"),
    (lambda a: a["windows"][0].update(used_percent=True), "check_failed"),
    (lambda a: a["windows"][0].update(profile=CANARY), "check_failed"),
    (lambda a: a.update(status="unavailable", reason=CANARY), "check_failed"),
])
def test_helper_validates_bridge_and_strips_unexpected_fields(host, helpers, monkeypatch, mutation, reason):
    helper = helpers()
    result = {"id": 1, "ok": True, "slot": SLOT, "status": "ok", "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "windows": [{"key": "5h", "used_percent": 0, "resets_at": None},
                          {"key": "7d", "used_percent": 0, "resets_at": None}], "profile": CANARY}
    mutation(result)
    monkeypatch.setattr(helper.bridge, "request", lambda *_: copy.deepcopy(result))
    assert ask(helper) == {"status": "unavailable", "reason": reason}


def test_usage_succeeds_when_token_cap_is_full_and_does_not_change_it(host, helpers):
    helper = helpers(tokens_per_hour=1)
    assert helper.ceiling.take()
    assert ask(helper)["status"] == "ok"
    assert helper.ceiling.used() == 1


def test_usage_start_drift_and_missing_bridge(host, helpers):
    raw = host.raw()
    raw["bridge"]["sdk_version"] = "0.0.0-drift"
    assert ask(helpers(bridge=raw["bridge"])) == {"status": "unavailable", "reason": "sdk_changed"}
    assert ask_in_process(helpers(bridge=None), f"usage {SLOT}") == f"denied slot {SLOT}: no auth bridge is configured"
    assert host.fetch_events() == []


def test_helper_bridge_timeout_fixed_and_no_cap(host, helpers, monkeypatch):
    helper = helpers()

    def fail(*_):
        raise tph.BridgeTimeout("PRIVATE-EXCEPTION-CANARY")

    monkeypatch.setattr(helper.bridge, "request", fail)
    assert ask(helper) == {"status": "unavailable", "reason": "timeout"}
    assert helper.ceiling.used() == 0


@pytest.mark.skipif(not os.environ.get("TEMPER_PI_HOST_TEST_SDK_ROOT"), reason="optional pinned SDK not set")
def test_usage_on_real_pinned_sdk_synthetic_login_fake_fetch(host, helpers):
    root = Path(os.environ["TEMPER_PI_HOST_TEST_SDK_ROOT"])
    packages = root / "node_modules/@earendil-works"
    versions = {p: json.loads((packages / p / "package.json").read_text())["version"]
                for p in ["pi-coding-agent", "pi-ai"]}
    raw = host.raw()
    raw["bridge"].update(sdk_root=str(root), sdk_version=versions["pi-coding-agent"], ai_version=versions["pi-ai"])
    before = host.auth_state()
    assert ask(helpers(bridge=raw["bridge"]))["status"] == "ok"
    assert host.fetch_events() == [{"usage": True, "authorised": True, "noRedirect": True}]
    unchanged(host, before)
