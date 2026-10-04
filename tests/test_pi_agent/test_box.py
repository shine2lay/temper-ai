"""The worker box without Docker or network: how the container is asked for and checked, the
two host-side sockets (provider-only egress, the login handoff), session checks, the config
and the RPC transport's process group."""

from __future__ import annotations

import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from temper_ai.llm.pi_stream import Redactor
from temper_ai.pi_agent.box import (
    BoxConfig,
    BoxError,
    WorkerBox,
    check_session,
    jwt_account_ids,
)
from temper_ai.pi_agent.rpc import JsonLines, Rpc, RpcError
from tests.test_pi_agent import support as sup


@pytest.fixture
def short_root():
    # Unix socket paths must stay under ~108 bytes; pytest's tmp paths can be longer.
    root = Path(tempfile.mkdtemp(prefix="pibox-", dir="/tmp"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _box(tmp_path, short_root, token="", **over):
    cfg = sup.box_config(tmp_path, socket_root=str(short_root), **over)
    pdir = tmp_path / "participant"
    calls: list[str] = []

    def connector(host):
        calls.append(host)
        a, b = socket.socketpair()
        connector.far = b
        return a

    box = WorkerBox(cfg, sup.spec(pdir), Redactor(), owner_token=lambda _p: token,
                    connector=connector)
    box.connector_calls = calls
    box.connector_fn = connector
    return box


def _talk(path: Path, data: bytes, read_until: bytes | None = None) -> bytes:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(str(path))
    s.sendall(data)
    got = b""
    while True:
        try:
            chunk = s.recv(4096)
        except TimeoutError:
            break
        if not chunk:
            break
        got += chunk
        if read_until and read_until in got:
            break
    s.close()
    return got


# --- the container ------------------------------------------------------------------------


def test_the_container_is_asked_for_sealed(tmp_path, short_root):
    box = _box(tmp_path, short_root)
    box.sock_dir = short_root / "s"
    args = box.create_args()
    joined = " ".join(args)
    for flag in ("--pull=never", "--init", "--network none", "--read-only", "--cap-drop ALL",
                 "--security-opt no-new-privileges", "--log-driver none", "--dns 127.0.0.1",
                 f"--user {os.getuid()}:{os.getgid()}"):
        assert flag in joined, flag
    mounts = [a for a in args if a.startswith("type=bind")]
    writable = [m for m in mounts if not m.endswith(",readonly")]
    assert len(writable) == 1 and "target=/w," in writable[0] + ","
    assert not any(str(Path.home() / ".pi") in m for m in mounts)
    env = [args[i + 1] for i, a in enumerate(args) if a == "--env"]
    keys = {e.split("=", 1)[0] for e in env}
    assert not keys & {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "PI_IDENTITY", "PI_SUBAGENT_CHILD"}
    assert "HTTPS_PROXY=http://127.0.0.1:3128" in env
    pi = args[args.index("/box/entry.py") + 1:]
    assert pi[:9] == ["--mode", "rpc", "--offline", "--no-approve", "--no-extensions",
                      "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files"]
    assert [pi[i + 1] for i, a in enumerate(pi) if a == "--extension"] == [
        "/ext/identity/index.ts", "/ext/temper-box/index.ts"]
    assert pi[pi.index("--tools") + 1] == "read"
    assert pi[pi.index("--session-id") + 1] == "sess-1"
    assert "--continue" not in pi and "--resume" not in pi


def _inspect_json(box) -> dict:
    return {
        "Image": box.cfg.image,
        "Config": {"User": f"{os.getuid()}:{os.getgid()}"},
        "Mounts": [{"Source": s, "Destination": d, "RW": w} for s, d, w in box.mounts()],
        "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                       "CapDrop": ["ALL"], "CapAdd": None,
                       "SecurityOpt": ["no-new-privileges"], "PidMode": "", "Devices": [],
                       "LogConfig": {"Type": "none"}, "Init": True},
    }


TAMPER = {
    "network_none": lambda i: i["HostConfig"].update(NetworkMode="bridge"),
    "read_only_root": lambda i: i["HostConfig"].update(ReadonlyRootfs=False),
    "not_privileged": lambda i: i["HostConfig"].update(Privileged=True),
    "cap_drop_all": lambda i: i["HostConfig"].update(CapDrop=["NET_RAW"]),
    "no_cap_add": lambda i: i["HostConfig"].update(CapAdd=["NET_ADMIN"]),
    "no_new_privileges": lambda i: i["HostConfig"].update(SecurityOpt=[]),
    "own_pid_namespace": lambda i: i["HostConfig"].update(PidMode="host"),
    "init": lambda i: i["HostConfig"].update(Init=False),
    "image": lambda i: i.update(Image="sha256:" + "1" * 64),
    "user": lambda i: i["Config"].update(User="0:0"),
    "mounts_exact": lambda i: i["Mounts"].append({"Source": "/", "Destination": "/host", "RW": True}),
    "no_owner_pi_mount": lambda i: i["Mounts"].append(
        {"Source": str(Path.home() / ".pi" / "agent"), "Destination": "/w/agent", "RW": False}),
}


@pytest.mark.parametrize("broken", [None, *TAMPER])
def test_a_container_not_sealed_exactly_is_refused(tmp_path, short_root, monkeypatch, broken):
    box = _box(tmp_path, short_root)
    box.sock_dir = short_root / "s"
    info = _inspect_json(box)
    if broken:
        TAMPER[broken](info)
    monkeypatch.setattr(box, "_docker", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, json.dumps([info]), ""))
    if broken is None:
        assert all(box._inspect().values())
        return
    with pytest.raises(BoxError) as err:
        box._inspect()
    assert err.value.code == "box_not_sealed"
    assert broken in str(err.value) or broken == "no_owner_pi_mount"


def test_close_removes_the_container_and_reports(tmp_path, short_root, monkeypatch):
    box = _box(tmp_path, short_root)
    calls = []

    def docker(*args, **kw):
        calls.append(args[:2])
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(box, "_docker", docker)
    box.created = True
    receipt = box.close()
    assert ("rm", "--force") in calls and receipt["container_removed"] is True
    never = _box(tmp_path, short_root)
    assert never.close()["container_removed"] is True  # nothing was created


# --- the two host-side sockets ------------------------------------------------------------


def test_egress_passes_only_the_route_host_on_443(tmp_path, short_root):
    box = _box(tmp_path, short_root)
    box._open_sockets()
    try:
        egress = box.sock_dir / "egress.sock"
        for head in (b"CONNECT evil.example:443 HTTP/1.1\r\n\r\n",
                     b"CONNECT chatgpt.com:80 HTTP/1.1\r\n\r\n",
                     b"CONNECT chatgpt.com.evil.example:443 HTTP/1.1\r\n\r\n",
                     b"GET http://chatgpt.com/ HTTP/1.1\r\nHost: chatgpt.com\r\n\r\n",
                     b"\x16\x03\x01 not http at all\r\n\r\n"):
            assert _talk(egress, head).startswith(b"HTTP/1.1 403"), head
        assert box.connector_calls == []

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(str(egress))
        s.sendall(b"CONNECT chatgpt.com:443 HTTP/1.1\r\nHost: chatgpt.com:443\r\n\r\nHELLO")
        assert s.recv(64).startswith(b"HTTP/1.1 200")
        far = box.connector_fn.far
        far.settimeout(5)
        assert far.recv(64) == b"HELLO"
        far.sendall(b"WORLD")
        assert s.recv(64) == b"WORLD"
        s.close()
        far.close()
        assert box.connector_calls == ["chatgpt.com"]
    finally:
        receipt = box.close()
    assert receipt["tunnels_allowed"] == 1 and receipt["tunnels_refused"] == 5
    assert not box.sock_dir.exists()


def _jwt(account: str) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return ".".join([enc({"alg": "none"}),
                     enc({"https://api.openai.com/auth": {"chatgpt_account_id": account}}),
                     "c2lnbmF0dXJl"])


def test_the_login_is_handed_over_only_within_the_turns_allowance(tmp_path, short_root):
    token = _jwt("acct-1234567890")
    box = _box(tmp_path, short_root, token=token)
    box._open_sockets()
    try:
        handoff = box.sock_dir / "handoff.sock"
        assert _talk(handoff, b"openai-codex\n") == b"", "no allowance before the prompt"
        box.allow(1)
        assert _talk(handoff, b"anthropic\n") == b"", "only the route's provider"
        assert box.redactor.secrets == []
        got = _talk(handoff, b"openai-codex\n")
        assert got == token.encode()
        # The redactor knew the token and its account id before the worker had them.
        assert token in box.redactor.secrets and "acct-1234567890" in box.redactor.secrets
        assert _talk(handoff, b"openai-codex\n") == b"", "the allowance is spent"
    finally:
        receipt = box.close()
    assert receipt["handoffs"] == 1 and receipt["handoffs_denied"] == 3
    assert token not in json.dumps(receipt)


def test_a_denied_handoff_fault_hands_over_nothing(tmp_path, short_root):
    box = _box(tmp_path, short_root, token="sk-test-token-123456", fault="deny_handoff")
    box._open_sockets()
    try:
        box.allow(5)
        assert _talk(box.sock_dir / "handoff.sock", b"openai-codex\n") == b""
    finally:
        assert box.close()["handoffs"] == 0


def test_account_ids_are_found_inside_a_jwt():
    assert jwt_account_ids(_jwt("acct-abcdef")) == ["acct-abcdef"]
    assert jwt_account_ids("not-a-jwt") == []


# --- sessions -----------------------------------------------------------------------------


def _session(dirpath: Path, sid: str, entries: list[dict], cwd: str = "/w/workspace") -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    path = dirpath / f"2026-10-03T00-00-00-000Z_{sid}.jsonl"
    lines = [{"type": "session", "version": 3, "id": sid, "timestamp": "t", "cwd": cwd}]
    parent = None
    for i, e in enumerate(entries):
        eid = e.pop("id", f"e{i}")
        lines.append({"id": eid, "parentId": e.pop("parentId", parent), "timestamp": "t", **e})
        parent = eid
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))
    return path


IDENT = {"type": "custom", "customType": "identity", "data": {"id": "scout"}}


def _msg(role: str, stop: str | None = None) -> dict:
    m: dict = {"role": role, "content": []}
    if stop:
        m["stopReason"] = stop
    return {"type": "message", "message": m}


def test_session_checks(tmp_path):
    d = tmp_path / "sessions"
    assert check_session(d, "s1", must_exist=False)["exists"] is False
    with pytest.raises(BoxError, match="missing"):
        check_session(d, "s1", must_exist=True)
    _session(d, "s1", [dict(IDENT), _msg("user"), _msg("assistant", "stop")])
    ok = check_session(d, "s1", must_exist=True)
    assert ok["settled"] and ok["identity_entries"] == 1 and ok["settle_point"] == "e2"
    (d / "other.jsonl").write_text("{}\n")
    with pytest.raises(BoxError) as err:
        check_session(d, "s1", must_exist=True)
    assert err.value.code == "session_folder_not_private"


@pytest.mark.parametrize("tail, settle", [
    ([_msg("user")], "e2"),                                       # an unanswered prompt
    ([_msg("user"), _msg("assistant", "toolUse")], "e2"),         # a tool call never answered
    ([_msg("user"), _msg("assistant", "toolUse"), _msg("toolResult")], "e2"),
])
def test_a_cut_off_turn_is_not_settled_and_names_where_to_go_back(tmp_path, tail, settle):
    d = tmp_path / "sessions"
    _session(d, "s1", [dict(IDENT), _msg("user"), _msg("assistant", "stop"), *tail])
    got = check_session(d, "s1", must_exist=True)
    assert got["settled"] is False and got["settle_point"] == settle


def test_the_active_branch_is_the_one_pi_reopens(tmp_path):
    d = tmp_path / "sessions"
    # e0 identity, e1 user, e2 answer, e3 dangling user (abandoned); e4 a new user prompt
    # branched from e2 and its answer e5: the file's last entry is on the settled branch.
    _session(d, "s1", [dict(IDENT), _msg("user"), _msg("assistant", "stop"), _msg("user"),
                       {**_msg("user"), "parentId": "e2"}, _msg("assistant", "stop")])
    got = check_session(d, "s1", must_exist=True)
    assert got["settled"] and got["leaf_id"] == "e5" and got["branch_entries"] == 5


def test_a_session_from_another_place_is_refused(tmp_path):
    d = tmp_path / "sessions"
    _session(d, "s1", [dict(IDENT)], cwd="/home/someone")
    with pytest.raises(BoxError) as err:
        check_session(d, "s1", must_exist=True)
    assert err.value.code == "session_mismatch"


# --- the box config -----------------------------------------------------------------------


def test_the_box_config_is_checked(tmp_path, monkeypatch):
    monkeypatch.delenv("TEMPER_PI_BOX_CONFIG", raising=False)
    with pytest.raises(BoxError) as err:
        BoxConfig.load()
    assert err.value.code == "box_not_configured"
    assert sup.box_config(tmp_path / "a").pi_version == "0.87.1"
    for over, why in (({"pi_version": "1.0.1"}, "installed Pi version"),
                      ({"image": "python:3.12-slim"}, "sha256 image id"),
                      ({"fault": "anything"}, "unknown fault"),
                      ({"mode": "rehearsal"}, "upstream_port")):
        with pytest.raises(BoxError, match=why):
            sup.box_config(tmp_path / "b", **over)


# --- the RPC transport --------------------------------------------------------------------


def test_json_lines():
    j = JsonLines(limit=64)
    assert j.feed(b'{"a":1}\n{"b"') == [{"a": 1}]
    assert j.feed(b':2}\r\n') == [{"b": 2}]
    with pytest.raises(RpcError, match="protocol_record_not_object"):
        j.feed(b"[1]\n")
    with pytest.raises(RpcError, match="protocol_line_limit"):
        JsonLines(limit=8).feed(b"x" * 20)
    k = JsonLines()
    k.feed(b'{"a":')
    with pytest.raises(RpcError, match="incomplete"):
        k.finish()


CHILD = r"""
import json, subprocess, sys
kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(json.dumps({"type": "hello", "grandchild": kid.pid}), flush=True)
for line in sys.stdin:
    cmd = json.loads(line)
    print(json.dumps({"type": "response", "id": cmd["id"], "command": cmd["type"],
                      "success": True}), flush=True)
"""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); read its state.
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def test_closing_a_worker_stops_everything_it_started(tmp_path):
    seen: list[dict] = []
    rpc = Rpc([sys.executable, "-c", CHILD], cwd=str(tmp_path),
              env={"PATH": os.environ.get("PATH", "")}, event_sink=seen.append)
    hello = rpc.next(time.monotonic() + 10)
    grandchild = hello["grandchild"]
    assert rpc.command("get_state", 10)["success"] is True
    assert os.getpgid(grandchild) == rpc.process.pid, "the worker has its own process group"
    receipt = rpc.close(wait=5)
    assert receipt["exit_code"] == 0
    deadline = time.monotonic() + 5
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(grandchild), "nothing the worker started outlives it"
    assert "group_leftovers_killed" in receipt["escalation"]
    with pytest.raises(RpcError, match="command_pipe_closed"):
        rpc.send("prompt", message="late")
    _ = signal
