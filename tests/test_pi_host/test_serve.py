"""temper-pi-host run as the unit runs it (``serve --config``): its start checks, its socket,
its stop, and where a login may and may not end up.  Also ``check``, ``ask`` and
``selftest``.  Stub Pi CLI and stub Pi SDK only."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys

import pytest

from .support import (
    BASE,
    NODE,
    PI_VERSION,
    SCRIPT,
    SDK_VERSION,
    SLOT,
    Host,
    Served,
    tph,
)

pytestmark = pytest.mark.skipif(NODE is None, reason="the auth bridge needs node")


@pytest.fixture
def host():
    h = Host()
    yield h
    h.cleanup()


@pytest.fixture
def served():
    started: list[Served] = []
    yield started
    for s in started:
        s.stop()


def serve(host: Host, served: list, name: str = "served", **over) -> Served:
    s = Served(host, host.config(**over), name)
    served.append(s)
    return s


def children(pid: int) -> list[int]:
    try:
        with open(f"/proc/{pid}/task/{pid}/children") as f:
            return [int(p) for p in f.read().split()]
    except OSError:
        return []


def proc_bytes(pid: int, name: str) -> bytes:
    with open(f"/proc/{pid}/{name}", "rb") as f:
        return f.read()


@pytest.mark.timeout(60)
def test_serves_and_stops(host, served):
    s = serve(host, served)
    assert s.wait_ready()
    mode = os.lstat(s.socket).st_mode
    assert stat.S_ISSOCK(mode) and stat.S_IMODE(mode) == 0o600
    assert stat.S_IMODE(os.stat(host.sock_dir).st_mode) == 0o700  # its folder untouched
    words = json.loads(s.ask("status")[3:])
    assert words["pi"] == PI_VERSION and words["bridge"]["version"] == SDK_VERSION
    assert s.ask(f"token {BASE}") == f"denied slot {BASE} is account 1 and is never served"
    assert s.stop() == 0
    assert not os.path.exists(s.socket)
    log = s.log()
    assert (f"temper-pi-host: serving {s.socket} for uid {os.getuid()}: pi {PI_VERSION}, sdk "
            f"{tph.DEFAULT_SDK_PACKAGE} {SDK_VERSION}, slots {SLOT},acme-3, branch off, ceiling 120/h") in log
    requests = [ln for ln in log.splitlines() if " verb=" in ln]
    assert len(requests) == 2
    assert " verb=status result=ok " in requests[0]
    assert f" verb=token slot={BASE} result=denied why=account_1 " in requests[1]
    assert log.rstrip().endswith("temper-pi-host: stopped")


@pytest.mark.timeout(60)
def test_a_login_never_leaves_the_socket(host, served):
    """The login goes to the asker only: never into the log, any file, any argv or any
    environment (the helper's or the bridge's).  auth.json is the one file holding it."""
    s = serve(host, served)
    assert s.wait_ready()
    assert s.ask(f"token {SLOT}") == "ok " + host.canary
    json.loads(s.ask("status")[3:])
    pids = [s.proc.pid, *children(s.proc.pid)]
    assert len(pids) == 2  # the helper and its bridge
    for pid in pids:
        for name in ("cmdline", "environ"):
            data = proc_bytes(pid, name)
            assert host.canary.encode() not in data and host.canary_refresh.encode() not in data
    assert s.stop() == 0
    assert host.canary not in s.log() and host.canary_refresh not in s.log()
    assert host.files_holding(host.canary, skip=(host.auth,)) == []
    assert host.files_holding(host.canary_refresh, skip=(host.auth,)) == []
    assert host.forbidden_pi_calls() == []


@pytest.mark.timeout(60)
def test_a_different_sdk_version_refuses_the_start_before_any_login_is_read(host, served):
    before = host.auth_state()
    raw = host.config()
    raw["bridge"]["sdk_version"] = "9.9.9"
    s = Served(host, raw)
    served.append(s)
    assert s.proc.wait(timeout=30) == 2
    assert not os.path.exists(s.socket)
    assert (f"temper-pi-host: refused to start: the Pi SDK the bridge found is {tph.DEFAULT_SDK_PACKAGE} "
            f"{SDK_VERSION} with {tph.AI_PACKAGE} {SDK_VERSION}, expected {tph.DEFAULT_SDK_PACKAGE} 9.9.9 with "
            f"{tph.AI_PACKAGE} {SDK_VERSION}; the bridge stopped before reading any login") in s.log()
    assert "imported" not in host.events()
    assert host.auth_state() == before
    assert not os.path.exists(str(host.auth) + ".lock")


@pytest.mark.timeout(60)
def test_an_unreadable_sdk_refuses_the_start(host, served):
    raw = host.config()
    raw["bridge"]["sdk_root"] = str(host.root / "no-sdk")
    s = Served(host, raw)
    served.append(s)
    assert s.proc.wait(timeout=30) == 2
    assert "could not be read; the bridge stopped before reading any login" in s.log()


@pytest.mark.parametrize("case", ["missing", "open_mode", "not_ours_shape"])
def test_the_socket_folder_must_be_private(host, served, case):
    if case == "missing":
        sock = str(host.root / "nope" / "h.sock")
        expected = f"the socket folder {host.root / 'nope'} does not exist"
    elif case == "open_mode":
        host.sock_dir.chmod(0o755)
        sock = str(host.sock_dir / "h.sock")
        expected = f"the socket folder {host.sock_dir} must be mode 0700 (it is 0755)"
    else:
        (host.root / "file").write_text("")
        sock = str(host.root / "file" / "h.sock")
        expected = f"the socket folder {host.root / 'file'} is not a folder"
    s = Served(host, host.config(socket=sock))
    served.append(s)
    assert s.proc.wait(timeout=30) == 2
    assert f"refused to start: {expected}" in s.log()
    assert not os.path.exists(host.root / "nope")
    if case == "open_mode":
        assert stat.S_IMODE(os.stat(host.sock_dir).st_mode) == 0o755  # never chmods a folder


@pytest.mark.timeout(60)
def test_one_helper_per_socket_and_a_stale_socket_is_replaced(host, served):
    first = serve(host, served, "first")
    assert first.wait_ready()
    second = serve(host, served, "second")
    assert second.proc.wait(timeout=30) == 2
    assert f"refused to start: another helper is serving {first.socket}" in second.log()
    first.proc.kill()  # dies without removing its socket
    first.proc.wait(timeout=10)
    assert os.path.exists(first.socket)
    third = serve(host, served, "third")
    assert third.wait_ready()
    assert third.ask("status").startswith("ok ")


@pytest.mark.timeout(60)
def test_a_bad_config_refuses_the_start(host, served):
    s = Served(host, host.config(allowed_slots=[BASE]))
    served.append(s)
    assert s.proc.wait(timeout=30) == 2
    assert "refused to start: allowed_slots can't hold acme: it is account 1, never served" in s.log()


@pytest.mark.timeout(60)
def test_check(host):
    config = host.write_config(host.config())
    done = subprocess.run([sys.executable, str(SCRIPT), "check", "--config", str(config)],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stdout
    report = json.loads(done.stdout)
    assert report["ok"] is True and report["socket_folder"] == "ok" and report["pi"] == PI_VERSION
    assert report["bridge"]["state"] == "ready" and report["bridge"]["version"] == SDK_VERSION
    assert not os.path.exists(host.sock_dir / "h.sock")
    raw = host.config()
    raw["bridge"]["sdk_version"] = "9.9.9"
    done = subprocess.run([sys.executable, str(SCRIPT), "check", "--config", str(host.write_config(raw, "bad.json"))],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 1
    report = json.loads(done.stdout)
    assert report["bridge"]["state"] == "refused" and "expected" in report["bridge"]["why"]
    assert "imported" not in host.events()[1:]


@pytest.mark.timeout(60)
def test_ask(host, served):
    s = serve(host, served)
    assert s.wait_ready()
    done = subprocess.run([sys.executable, str(SCRIPT), "ask", "--socket", s.socket, "status"],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0 and done.stdout.startswith("ok {")
    done = subprocess.run([sys.executable, str(SCRIPT), "ask", "--socket", s.socket, "token", SLOT],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 2  # ask only asks for the status
    done = subprocess.run([sys.executable, str(SCRIPT), "ask", "--socket", str(host.sock_dir / "none.sock"), "status"],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 1 and done.stdout.startswith("no answer from")


@pytest.mark.timeout(120)
def test_selftest_passes():
    done = subprocess.run([sys.executable, str(SCRIPT), "selftest"], capture_output=True, text=True,
                          timeout=110, check=False)
    assert done.returncode == 0, done.stdout
    assert "FAIL" not in done.stdout
    assert done.stdout.rstrip().splitlines()[-1].startswith("selftest: PASS (")
