"""temper-pi-host's verbs, asked in process over a socket pair: token, status, the uid check,
the timeout, the hourly ceiling and the log lines.  The auth bridge is the real one over a
stub Pi SDK; the Pi CLI is a stub.  No real login, no network, no model call."""

from __future__ import annotations

import json
import os
import socket

import pytest

from .support import (
    BASE,
    NODE,
    OTHER,
    PI_VERSION,
    SDK_VERSION,
    SLOT,
    Host,
    ask_in_process,
    login,
    tph,
)

needs_node = pytest.mark.skipif(NODE is None, reason="the auth bridge needs node")


@pytest.fixture
def host():
    h = Host()
    yield h
    h.cleanup()


@pytest.fixture
def helpers():
    made: list = []
    yield made
    for helper in made:
        if helper.bridge is not None:
            helper.bridge.stop_all()


def helper_for(host: Host, helpers: list, **over) -> tph.Helper:
    helper = tph.Helper(host.cfg(**over))
    helpers.append(helper)
    return helper


def log_lines(capsys) -> list[str]:
    return [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith("temper-pi-host:")]


# --- token -----------------------------------------------------------------------------


@needs_node
def test_token_serves_the_slot_asked_for(host, helpers, capsys):
    helper = helper_for(host, helpers)
    assert ask_in_process(helper, f"token {SLOT}") == "ok " + host.canary
    lines = log_lines(capsys)
    assert len(lines) == 1
    assert f" verb=token slot={SLOT} result=ok " in lines[0]
    assert f" sdk={SDK_VERSION} " in lines[0] and " peer=" in lines[0]
    assert host.canary not in "\n".join(lines)


@needs_node
@pytest.mark.parametrize("slot, answer", [
    (BASE, f"denied slot {BASE} is account 1 and is never served"),
    (f"{BASE}-9", f"denied slot {BASE}-9 is not one this helper serves"),
    ("other-2", f"denied slot other-2 is not an alias of {BASE}"),
    (f"{BASE}-1", f"denied slot {BASE}-1 is not an alias of {BASE}"),
    ("a/b", "denied the slot name is missing or malformed"),
])
def test_token_refusals_before_the_bridge(host, helpers, capsys, slot, answer):
    helper = helper_for(host, helpers)
    assert ask_in_process(helper, f"token {slot}") == answer
    assert helper.ceiling.used() == 0  # refused before the ceiling and the bridge
    assert helper.bridge.proc is None  # the bridge was never even started
    assert "result=denied" in log_lines(capsys)[0]


@needs_node
@pytest.mark.parametrize("setup, slot, answer", [
    ("unregistered", OTHER, f"denied slot {OTHER} is not registered in Pi's multi-pass subscriptions"),
    (None, OTHER, f"denied slot {OTHER} has no stored login"),
    ("api_key", SLOT, f"denied slot {SLOT} has no OAuth login"),
    ("failing_refresh", SLOT, f"denied slot {SLOT}: its login could not be refreshed"),
])
def test_token_refusals_from_the_bridge(host, helpers, capsys, setup, slot, answer):
    if setup == "unregistered":
        host.register(2)
    elif setup == "api_key":
        host.write_auth({SLOT: {"type": "api_key", "key": host.canary}})
    elif setup == "failing_refresh":
        host.write_auth({SLOT: login(host.canary, host.canary_refresh, 60 * 1000)})
        host.control(refresh="fail")
    before = host.auth_state()
    helper = helper_for(host, helpers)
    assert ask_in_process(helper, f"token {slot}") == answer
    assert host.auth_state() == before
    text = "\n".join(log_lines(capsys))
    assert "result=denied" in text
    assert host.canary not in text and "STUB-SECRET-BODY" not in text


@needs_node
def test_a_changed_sdk_refuses_the_token_and_names_both_versions(host, helpers):
    helper = helper_for(host, helpers)
    assert ask_in_process(helper, f"token {SLOT}") == "ok " + host.canary
    before = host.auth_state()
    tph.set_stub_version(host.sdk_root, "7.7.8-upgraded")
    assert ask_in_process(helper, f"token {SLOT}") == (
        f"denied slot {SLOT}: the Pi SDK on disk changed since the helper started (now 7.7.8-upgraded, "
        f"expected {SDK_VERSION}); auth.json was not read or written")
    assert host.auth_state() == before


@needs_node
def test_no_bridge_configured(host, helpers):
    helper = helper_for(host, helpers, bridge=None)
    assert ask_in_process(helper, f"token {SLOT}") == f"denied slot {SLOT}: no auth bridge is configured"


@needs_node
@pytest.mark.timeout(60)
def test_a_token_that_takes_too_long_is_refused_and_the_next_one_works(host, helpers, capsys):
    host.write_auth({SLOT: login("old-access", "old-refresh", 60 * 1000)})
    host.control(refresh="hang")
    raw = host.config(token_timeout_s=1)
    raw["bridge"]["stop_grace_s"] = 1
    helper = tph.Helper(tph.parse_config(raw))
    helpers.append(helper)
    assert ask_in_process(helper, f"token {SLOT}") == f"denied slot {SLOT}: no token within 1 s"
    assert "why=timeout" in log_lines(capsys)[0]
    host.control(next_access="new-access")
    raw["token_timeout_s"] = 10
    helper.cfg = tph.parse_config(raw)
    assert ask_in_process(helper, f"token {SLOT}") == "ok new-access"


@needs_node
def test_the_hourly_ceiling_is_a_tripwire(host, helpers, capsys):
    helper = helper_for(host, helpers, tokens_per_hour=2)
    assert ask_in_process(helper, f"token {SLOT}") == "ok " + host.canary
    assert ask_in_process(helper, f"token {BASE}").startswith("denied")  # refusals before it don't count
    assert ask_in_process(helper, f"token {SLOT}") == "ok " + host.canary
    assert ask_in_process(helper, f"token {SLOT}") == f"denied slot {SLOT}: the hourly token ceiling (2) is reached"
    err = capsys.readouterr().err
    assert "tripwire: the hourly token ceiling (2) is reached" in err
    assert "why=ceiling" in err


def test_the_ceiling_allows_120_an_hour():
    now = [1000.0]
    ceiling = tph.Ceiling(120, clock=lambda: now[0])
    for _ in range(120):
        assert ceiling.take()
        now[0] += 10  # 120 hand-offs over 20 minutes
    assert not ceiling.take()
    assert ceiling.used() == 120
    now[0] = 1000.0 + 3600  # an hour after the first
    assert ceiling.take()
    assert ceiling.used() == 120
    now[0] += 3600
    assert ceiling.used() == 0


# --- status ----------------------------------------------------------------------------


@needs_node
def test_status_words(host, helpers):
    helper = helper_for(host, helpers)
    answer = ask_in_process(helper, "status")
    assert answer.startswith("ok ")
    words = json.loads(answer[3:])
    assert words["helper"] == "temper-pi-host" and words["protocol"] == 1
    assert words["pi"] == PI_VERSION and words["git"] != "unknown"
    assert words["uid"] == os.getuid() and words["branch"] == "off"
    assert (words["tokens_last_hour"], words["tokens_per_hour"]) == (0, 120)
    bridge = words["bridge"]
    assert (bridge["state"], bridge["package"], bridge["version"]) == ("ready", tph.DEFAULT_SDK_PACKAGE, SDK_VERSION)
    assert (bridge["ai_package"], bridge["ai_version"], bridge["expected"]) == (tph.AI_PACKAGE, SDK_VERSION, SDK_VERSION)
    assert words["slots"] == {
        SLOT: {"pi": "not_ready provider_not_found", "bridge": "registered login_ready"},
        OTHER: {"pi": "not_ready provider_not_found", "bridge": "registered login_missing"},
    }
    assert host.canary not in answer and host.canary_refresh not in answer
    assert host.forbidden_pi_calls() == []
    assert host.refreshes() == 0


@needs_node
def test_status_after_the_sdk_changed(host, helpers):
    helper = helper_for(host, helpers)
    ask_in_process(helper, "status")
    tph.set_stub_version(host.sdk_root, "7.7.8-upgraded")
    words = json.loads(ask_in_process(helper, "status")[3:])
    assert words["bridge"]["state"] == "sdk_changed" and words["bridge"]["found"] == "7.7.8-upgraded"
    assert words["slots"][SLOT]["bridge"] == "sdk_changed"


def test_status_without_a_bridge(host, helpers):
    helper = helper_for(host, helpers, bridge=None)
    words = json.loads(ask_in_process(helper, "status")[3:])
    assert words["bridge"] == {"state": "not_configured"}
    assert words["slots"][SLOT] == {"pi": "not_ready provider_not_found", "bridge": "unknown"}


# --- requests, the uid check -------------------------------------------------------------


@pytest.mark.parametrize("line", ["frobnicate", "token", f"token {SLOT} extra", "status now", "branch a b",
                                  "", "x" * 5000])
def test_requests_it_does_not_know(host, helpers, line):
    helper = helper_for(host, helpers, bridge=None)
    assert ask_in_process(helper, line) == "denied the request is not one this helper knows"


def test_only_the_configured_uid_is_served(host, helpers, capsys):
    other = os.getuid() + 1
    helper = helper_for(host, helpers, bridge=None, uid=other)
    assert ask_in_process(helper, "status") == f"denied uid {os.getuid()} is not served"
    line = log_lines(capsys)[0]
    assert " result=denied why=uid " in line and f" uid={os.getuid()} " in line


def test_peer_cred_names_this_process():
    ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with ours, theirs:
        assert tph.peer_cred(ours) == (os.getpid(), os.getuid())


def test_log_lines_are_one_line_of_words():
    import contextlib
    import io

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        tph.log(verb="token", slot="a b\nc", result="ok")
    assert err.getvalue() == "temper-pi-host: verb=token slot=a_b_c result=ok\n"
