"""Synthetic W1 transport stages, not a browser/control/workflow or UID999 qualification.

Real WorkflowConfig/input resolution, ScriptAgent, ToolExecutor/Bash, private writer and W1 reader.
Only checker launch is replaced by a fixed local boundary script; that boundary cannot prove a browser.
No actual environment values, credentials, model inputs or real readings are inspected or printed.
"""
from __future__ import annotations

import base64
import errno
import hashlib
import importlib
import json
import os
import re
import socket
import stat
from types import SimpleNamespace

import pytest
import yaml

from temper_ai.agent.script_agent import ScriptAgent, _ValueStash
from temper_ai.shared.types import ExecutionContext, NodeResult, Status
from temper_ai.stage.executor import _resolve_inputs, _resolve_single_input
from temper_ai.stage.models import WorkflowConfig
from temper_ai.tools.bash import Bash
from temper_ai.tools.executor import ToolExecutor
from tests.test_agent.test_script_agent_log import Recorder
from tests.test_architecture import test_first_app_check as wiring
from tests.test_architecture import test_first_app_p3_w1 as fixtures

BIN = wiring.SCRIPT.parent
ROOT = BIN.parents[2]
CANARY = "SYNTHETIC-W1-CANARY-café-雪"
EXACT = ('{ "canary": "' + CANARY + '" }\r\n\n').encode()


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("transport tests must not contact browser/host/network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.syspath_prepend(str(BIN))
    return importlib.import_module("first_app_p3_w1_input")


def envelope(data=EXACT, **changes):
    obj = {"data_base64": base64.b64encode(data).decode("ascii"), "sha256": hashlib.sha256(data).hexdigest()}
    obj.update(changes)
    return json.dumps(obj)


def destination(workspace):
    return workspace / "check/w1-input/before.json"


def test_exact_bytes_fixed_path_create_once_and_real_w1_reader(transport, tmp_path):
    raw = json.dumps(fixtures.reading(), indent=3).encode() + b"\n\n"
    text, meta = transport.prepare(envelope(raw), tmp_path)
    path = destination(tmp_path)
    ref = json.loads(text)
    assert ref == {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
    assert path.read_bytes() == raw
    info = path.stat()
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_uid == os.geteuid() and info.st_gid == os.getegid()
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert meta == {**ref, "process_uid": os.geteuid(), "process_gid": os.getegid(),
                    "file_uid": info.st_uid, "file_gid": info.st_gid, "file_mode": "0600"}
    assert transport.w1.precheck(ref, fixtures.START) == fixtures.reading()
    with pytest.raises(transport.Refused):
        transport.prepare(envelope(raw), tmp_path)
    assert path.read_bytes() == raw and path.stat().st_ino == info.st_ino
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == [
        "check", "check/w1-input", "check/w1-input/before.json"]


@pytest.mark.parametrize("raw", [EXACT, b"", b"\xff\x00\n", b" " * 65536],
                         ids=["non-ascii-and-newlines", "empty-is-w1s-decision", "binary-is-w1s-decision", "max-size"])
def test_transport_never_normalizes_or_duplicates_w1_validation(transport, tmp_path, raw):
    text, _ = transport.prepare(envelope(raw), tmp_path)
    assert destination(tmp_path).read_bytes() == raw
    gated = transport.w1.gate(json.loads(text), fixtures.START, fixtures.WK)
    assert gated["status"] == "REFUSED"
    assert gated["rule"].startswith(("bad-schema:", "missing:"))


BAD_INLINE = {
    "missing-digest": '{"data_base64":"e30="}',
    "mixed-path": envelope(path="/never-open-this-host-path"),
    "extra-key": envelope(extra="unused"),
    "duplicate-data": '{"data_base64":null,' + envelope()[1:],
    "duplicate-sha": '{"sha256":"' + "0" * 64 + '",' + envelope()[1:],
    "escaped-duplicate-key": '{"data_\\u0062ase64":null,' + envelope()[1:],
    "data-null": envelope(data_base64=None),
    "data-bool": envelope(data_base64=True),
    "data-array": envelope(data_base64=[]),
    "data-object": envelope(data_base64={}),
    "sha-null": envelope(sha256=None),
    "sha-list": envelope(sha256=[]),
    "sha-number": envelope(sha256=12),
    "sha-upper": envelope(sha256="A" * 64),
    "sha-short": envelope(sha256="a" * 63),
    "sha-long": envelope(sha256="a" * 65),
    "sha-newline": envelope(sha256="a" * 64 + "\n"),
    "sha-mismatch": envelope(sha256="0" * 64),
    "base64-whitespace": envelope(data_base64="e30=\n"),
    "base64-url-alphabet": envelope(data_base64="__8="),
    "base64-non-ascii": envelope(data_base64="雪"),
    "base64-no-padding": envelope(data_base64="e30"),
    "base64-extra-padding": envelope(b"abc", data_base64="YWJj="),
    "base64-pad-bits": envelope(b"a", data_base64="YR=="),
    "base64-trailing-data": envelope(data_base64="e30=AAAA"),
    "base64-invalid": envelope(data_base64="!!!!"),
    "over-decoded-bound-same-encoded-length": envelope(b" " * 65537),
    "over-encoded-bound": envelope(b" " * 65539),
    "nan-type": '{"data_base64":NaN,"sha256":"' + "0" * 64 + '"}',
}


@pytest.mark.parametrize("text", BAD_INLINE.values(), ids=BAD_INLINE)
def test_bad_inline_refuses_before_any_file_or_checker(transport, monkeypatch, tmp_path, capsys, text):
    with pytest.raises(transport.Refused):
        transport.prepare(text, tmp_path)
    assert list(tmp_path.iterdir()) == []
    cmd, how, refusal = wiring.run_agent(monkeypatch, tmp_path, mode="controls_p3", w1_before=text)
    assert cmd is None and how is None and refusal.startswith("first_app_check: inline W1")
    assert not destination(tmp_path).exists() and not (tmp_path / "check/run.log").exists()
    assert CANARY not in refusal and json.loads(envelope())["data_base64"] not in refusal
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("text", ["not json", '{"data_base64":', '{"path":1,"path":2}',
                                    '[{"data_base64":"bad"}]', '"data_base64"', "null", " \n", wiring.W1_REF])
def test_non_inline_text_remains_identical_without_any_files(transport, tmp_path, text):
    assert transport.prepare(text, tmp_path) == (text, None)
    assert list(tmp_path.iterdir()) == []


COLLISIONS = ["check-symlink", "stage-symlink", "stage-file", "stage-public", "leaf-file", "leaf-directory",
              "leaf-symlink", "leaf-fifo", "ancestor-symlink"]


def collision(workspace, kind):
    """Only synthetic paths; never repair/chmod/chown any existing path."""
    check = workspace / "check"
    outside = workspace / "outside"
    outside.mkdir()
    if kind == "check-symlink":
        check.symlink_to(outside, target_is_directory=True)
        return workspace
    check.mkdir()
    stage = check / "w1-input"
    if kind == "stage-symlink":
        stage.symlink_to(outside, target_is_directory=True)
    elif kind == "stage-file":
        stage.write_bytes(b"retained")
    elif kind == "stage-public":
        # The evidence runner uses umask 0077; without this, the negative is accidentally a safe 0700 dir.
        old_umask = os.umask(0)
        try:
            stage.mkdir(mode=0o755)
        finally:
            os.umask(old_umask)
        assert stat.S_IMODE(stage.stat().st_mode) == 0o755
    elif kind == "ancestor-symlink":
        alias = workspace / "alias"
        alias.symlink_to(workspace, target_is_directory=True)
        return alias
    else:
        stage.mkdir(mode=0o700)
        leaf = stage / "before.json"
        if kind == "leaf-file":
            leaf.write_bytes(b"retained")
        elif kind == "leaf-directory":
            leaf.mkdir()
        elif kind == "leaf-symlink":
            leaf.symlink_to(outside / "not-created")
        elif kind == "leaf-fifo":
            os.mkfifo(leaf, 0o600)
    return workspace


@pytest.mark.parametrize("kind", COLLISIONS)
def test_unsafe_paths_and_collisions_refuse_without_repair(transport, tmp_path, kind):
    workspace = collision(tmp_path, kind)
    before = {str(p): (p.lstat().st_ino, p.lstat().st_mode, p.lstat().st_mtime_ns)
              for p in tmp_path.rglob("*")}
    with pytest.raises(transport.Refused, match="fixed create-once destination"):
        transport.prepare(envelope(), workspace)
    assert {str(p): (p.lstat().st_ino, p.lstat().st_mode, p.lstat().st_mtime_ns)
            for p in tmp_path.rglob("*")} == before
    assert list((tmp_path / "outside").iterdir()) == []


@pytest.mark.parametrize("kind", COLLISIONS[:-1])
def test_collision_stops_agent_before_checker(transport, monkeypatch, tmp_path, kind):
    collision(tmp_path, kind)
    cmd, _, refusal = wiring.run_agent(monkeypatch, tmp_path, mode="controls_p3", w1_before=envelope())
    assert cmd is None and "fixed create-once destination" in refusal
    assert not (tmp_path / "check/run.log").exists()


def test_wrong_directory_owner_is_not_repaired(transport, monkeypatch, tmp_path):
    actual_fstat = os.fstat

    def foreign_directory(fd):
        actual = actual_fstat(fd)
        if stat.S_ISDIR(actual.st_mode):
            return SimpleNamespace(st_uid=os.geteuid() + 1, st_mode=actual.st_mode)
        return actual

    monkeypatch.setattr(transport.os, "fstat", foreign_directory)
    with pytest.raises(transport.Refused):
        transport.prepare(envelope(), tmp_path)
    assert not destination(tmp_path).exists()


def test_compatible_empty_private_directory_is_usable(transport, tmp_path):
    destination(tmp_path).parent.mkdir(parents=True, mode=0o700)
    transport.prepare(envelope(), tmp_path)
    assert destination(tmp_path).read_bytes() == EXACT


def test_fsync_error_preserves_new_evidence_and_never_launches_checker(transport, monkeypatch, tmp_path):
    calls = []

    def fail(fd):
        calls.append(fd)
        raise OSError(errno.EIO, CANARY)

    monkeypatch.setattr(transport.guard.os, "fsync", fail)
    cmd, _, refusal = wiring.run_agent(monkeypatch, tmp_path, mode="controls_p3", w1_before=envelope())
    assert cmd is None and len(calls) == 1 and CANARY not in refusal
    assert destination(tmp_path).read_bytes() == EXACT
    assert stat.S_IMODE(destination(tmp_path).stat().st_mode) == 0o600
    assert not (tmp_path / "check/run.log").exists()


@pytest.mark.parametrize("case", [k for k in wiring.TODAY if k != "controls_p3"])
def test_inline_in_other_modes_refuses_before_staging(monkeypatch, tmp_path, case):
    cmd, _, refusal = wiring.run_agent(monkeypatch, tmp_path, **wiring.TODAY[case][0], w1_before=envelope())
    assert cmd is None and "w1_before is for mode=controls_p3" in refusal
    assert not destination(tmp_path).parent.exists()


def local_script_agent(workspace, text, monkeypatch):
    """Real host execution, remapping only installed source paths and the checker execution boundary.

    Recorder is the existing in-memory event sink; no live DB. The checker stand-in invokes the REAL W1 gate
    and checks one known synthetic input slot, not the host environment. It makes no browser/network calls.
    """
    agent = yaml.safe_load((ROOT / "configs/architecture/agents/first_app_check.yaml").read_text())["agent"]
    flow = WorkflowConfig.from_dict(
        yaml.safe_load((ROOT / "configs/architecture/workflows/first_app_check.yaml").read_text())["workflow"])
    (check,) = flow.nodes
    given = {"mode": "controls_p3", "w1_before": text}
    inputs = _resolve_inputs(SimpleNamespace(name=check.name, config=check), given, {})
    boundary = workspace / "checker_boundary.py"
    slot = _ValueStash.PREFIX + "4"  # workspace, mode, profile, then the SINGLE w1_before slot
    boundary.write_text(
        "import json, os, pathlib, sys\n"
        f"sys.path.insert(0, {str(BIN)!r})\n"
        "import first_app_p3_w1 as w1\n"
        "pathlib.Path('checker-contact').write_text('synthetic boundary only')\n"
        f"assert os.environ.get({slot!r}) is None\n"
        "ref = json.loads(sys.argv[sys.argv.index('--w1-before') + 1])\n"
        f"gate = w1.gate(ref, {fixtures.START!r}, {fixtures.WK!r})\n"
        "out = {'mode': 'controls_p3', 'verdict': 'SYNTHETIC-BOUNDARY', 'all_ok': False,\n"
        "       'w1_status': gate['status'], 'w1_rule': gate['rule'], 'child_env_removed': True}\n"
        "pathlib.Path('check/summary.md').write_text('Synthetic boundary only; no browser.')\n"
        "print(json.dumps(out))\n")
    agent["script_template"] = agent["script_template"].replace(
        "/app/configs/architecture/bin/first_app_p3.py", str(boundary)).replace(
        "/app/configs/architecture/bin", str(BIN))
    recorder = Recorder()
    executor = ToolExecutor(workspace_root=str(workspace))
    executor.register_tools({"Bash": Bash(config={"workspace_root": str(workspace)})})
    real_execute = executor.execute
    observations = {}

    def observe(name, params, **kwargs):
        # Inspect only the named synthetic slot, never enumerate host environment values or print the script.
        found = re.search(r'w1_before_env = "([^"]+)"', params["command"]).group(1)
        assert found == slot and params["env"][slot] == text
        assert params["command"].count(slot) == 1
        observations["envelope_chars"] = len(params["env"][slot])
        return real_execute(name, params, **kwargs)

    monkeypatch.setattr(executor, "execute", observe)
    ctx = ExecutionContext(run_id="synthetic-351", workflow_name=flow.name, node_path="check",
                           agent_name="first_app_check", event_recorder=recorder, tool_executor=executor,
                           workspace_path=str(workspace))
    result = ScriptAgent(config=agent).run(inputs, ctx)
    return result, recorder, flow, observations


@pytest.mark.parametrize("case", ["clean", "exact-invalid-w1", "maximum", "transport-refusal", "collision"])
def test_real_script_agent_bash_transport_privacy_and_workflow_output(monkeypatch, tmp_path, case):
    raw = json.dumps(fixtures.reading(), indent=2).encode() + b"\n"
    if case == "exact-invalid-w1":
        raw = EXACT
    if case == "maximum":
        raw += b" " * (65536 - len(raw))
    text = envelope(raw)
    if case == "transport-refusal":
        text = envelope(EXACT, sha256="0" * 64)
    if case == "collision":
        destination(tmp_path).parent.mkdir(parents=True, mode=0o700)
        destination(tmp_path).write_bytes(b"retained")
    result, rec, flow, observations = local_script_agent(tmp_path, text, monkeypatch)
    [started] = rec.started()
    assert started["data"]["input_data"]["w1_before"] == text  # Expected ordinary storage, NOT secrecy.
    log_text = rec.text(started["id"])
    sinks = [result.output, result.error or "", log_text, json.dumps(result.structured_output)]
    for name in ("check/run.log", "check/summary.md"):
        path = tmp_path / name
        if path.exists():
            sinks.append(path.read_text())
    encoded = json.loads(text)["data_base64"]
    assert all(encoded not in sink and CANARY not in sink and EXACT.decode() not in sink for sink in sinks)
    if case in ("transport-refusal", "collision"):
        assert result.status == Status.FAILED and not (tmp_path / "checker-contact").exists()
        assert not (tmp_path / "check/run.log").exists()
        if case == "collision":
            assert destination(tmp_path).read_bytes() == b"retained"
        else:
            assert not destination(tmp_path).exists()
        return
    assert result.status == Status.COMPLETED
    assert (tmp_path / "checker-contact").exists()
    assert destination(tmp_path).read_bytes() == raw
    out = result.structured_output
    assert out["verdict"] == "SYNTHETIC-BOUNDARY" and out["all_ok"] is False
    assert out["child_env_removed"] is True and out["exit_code"] == 0
    assert out["w1_status"] == ("REFUSED" if case == "exact-invalid-w1" else "PROVISIONAL")
    if case == "exact-invalid-w1":
        assert out["w1_rule"] == "bad-schema:before"
    meta = out["w1_input_staging"]
    assert meta["path"] == str(destination(tmp_path)) and meta["sha256"] == hashlib.sha256(raw).hexdigest()
    assert meta["file_mode"] == "0600" and meta["process_uid"] == meta["file_uid"] == os.geteuid()
    assert meta["process_gid"] == meta["file_gid"] == os.getegid()
    outputs = {key: _resolve_single_input("__workflow__", key, source, {},
               {"check": NodeResult(status=result.status, structured_output=out)}) for key, source in flow.outputs.items()}
    assert outputs["w1_input_staging"] == meta and outputs["verdict"] == out["verdict"]
    legacy = dict(out)
    legacy.pop("w1_input_staging")
    assert _resolve_single_input("__workflow__", "w1_input_staging", flow.outputs["w1_input_staging"], {},
                                 {"check": NodeResult(status=result.status, structured_output=legacy)}) is None
    if case == "maximum":
        assert len(raw) == 65536 and len(encoded) == 87384
        assert observations["envelope_chars"] == len(text) > 87384
