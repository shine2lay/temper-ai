"""The one-shot delivery in real, disposable boxes (BS2 model-free gate: G02).

Each box is started by the real DockerSpawner under TEMPER_BOX_RUNTIME_BOUNDARY=sealed and
TEMPER_BOX_SECRET_BOOTSTRAP=oneshot, from a synthetic install tree whose final entry is the
real temper_ai/cli/main.py and the real spawner/box_bootstrap.py; only what comes after the
delivery (cli/run_workflow.py) is a probe. The worker's writer is the real one, run by
`docker exec`. Every container is labelled temper.test=box-sealed, is named after its test
and this test process (box_fixtures.run_id), and runs with --network
none; every "secret" is synthetic text; no database, model, account or service is touched.

What is looked at is the box itself: docker inspect, docker-init's environment (PID 1),
the runner's environ, memory, descriptors and ptrace from another process of the same
user (as an agent tool would be), the delivery folder, and the runner's own report.

The probe sets PR_SET_PTRACER_ANY (test only: Temper never does) so that Yama is not
why a read fails: in the positive control, the same box without the runner's
protection, the delivered value is found in the runner's memory after it was read,
closed and removed.

Skipped when docker can't be used here, unless TEMPER_TEST_BOX_REQUIRED=1.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from temper_ai.shared.box_env import BoxEnv
from temper_ai.spawner import box_bootstrap, box_profile
from temper_ai.spawner.base import SpawnerError
from temper_ai.spawner.box_seal import WorkerView
from temper_ai.spawner.docker_spawner import DockerSpawner
from tests.test_spawner.box_fixtures import (
    OWN_LABEL,
    SYNTHETIC_MARK,
    TEST_LABEL,
    Install,
    MemoryStore,
    box_image,
    box_name,
    box_user,
    docker_ok,
    image_id,
    run_id,
)

pytestmark = [pytest.mark.timeout(900)]

REPO = Path(__file__).resolve().parents[2]
RUN_COMMAND = "/app/.venv/bin/python -m temper_ai.cli.main run-workflow"
INTERPRETER = "/app/.venv/bin/python"
DB_URL = f"postgresql://temper:{SYNTHETIC_MARK}@db.synthetic:5432/temper"
#: What the box may get: two secrets (one by name, one by its value) and plain settings.
BOX_LIST = BoxEnv(
    names=frozenset({"PATH", "HOME", "WORKSPACE_DIR", "SYNTH_SERVICE_TOKEN", "SYNTH_DB_URL",
                     "TEMPER_API"}),
    agent_tools=frozenset({"PATH", "HOME", "WORKSPACE_DIR", "SYNTH_DB_URL", "TEMPER_API"}))
DELIVERED = ["SYNTH_DB_URL", "SYNTH_SERVICE_TOKEN"]
FAST = {"ready": 8, "delivery": 20, "ack": 4}


def _unavailable(why: str) -> None:
    if os.environ.get("TEMPER_TEST_BOX_REQUIRED") == "1":
        pytest.fail(f"the real-container one-shot gate can't run: {why}")
    pytest.skip(f"the real-container one-shot gate can't run here: {why}")


# -- the box's code: the real final entry, then a probe ----------------------------------------

STUB_PARSER = "def add_parser(subparsers):\n    pass\n"

#: What runs once the real entry has taken the delivery: reports names, counts and
#: booleans only (never a value), then waits to be released or restarted.
RUNNER = r'''
import ctypes, json, os, resource, subprocess, sys, time

def cmd_run_workflow(args):
    libc = ctypes.CDLL(None)
    libc.prctl(0x59616D61, ctypes.c_ulong(2 ** 64 - 1), 0, 0, 0)  # PR_SET_PTRACER_ANY (test only)
    from temper_ai.spawner import box_bootstrap as bb
    doc = json.loads(os.environ["TEMPER_BOX_PROFILE"])
    ws = next(g["target"] for g in doc["grants"] if g["kind"] == "workspace")
    names = doc["bootstrap"]["names"]
    values = [os.environ[n] for n in names if os.environ.get(n)]

    def leaks(text):
        return any(v in text for v in values)

    seen = {
        "default": subprocess.run(["env"], capture_output=True, text=True).stdout,
        "close_fds False": subprocess.run(["env"], capture_output=True, text=True,
                                          close_fds=False).stdout,
    }
    r, w = os.pipe()
    os.set_inheritable(w, True)
    os.system(f"env >&{w}")
    os.close(w)
    with os.fdopen(r) as fh:
        seen["os.system"] = fh.read()
    try:  # an error child: a failing program started the default way
        subprocess.run(["sh", "-c", "env; exit 3"], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        seen["error child"] = exc.stdout
    # (a process that isn't dumpable can't read even its own /proc/self/environ: its C
    # environment, the one it started with, is asked by name instead)
    libc.getenv.restype = ctypes.c_char_p
    start_names = sorted(n for n in names if libc.getenv(n.encode()) is not None)
    targets = []
    for fd in os.listdir("/proc/self/fd"):
        try:
            targets.append(os.readlink(f"/proc/self/fd/{fd}"))
        except OSError:
            pass
    report = {
        "pid": os.getpid(),
        "names": len(names),
        "all_present": len(values) == len(names),
        "child_leaks": sorted(k for k, v in seen.items() if leaks(v)),
        "children_checked": sorted(seen),
        "start_environ_names": start_names,
        "dumpable": libc.prctl(3, 0, 0, 0, 0),
        "core": list(resource.getrlimit(resource.RLIMIT_CORE)),
        "fds_into_boot": [t for t in targets if t.startswith(bb.BOOT_DIR)],
        "boot": sorted(os.listdir(bb.BOOT_DIR)),
        "tools_allowed": bb.tools_allowed(),
    }
    values.clear()
    with open(os.path.join(ws, ".runner.json"), "w") as fh:
        json.dump(report, fh)
    os.rename(os.path.join(ws, ".runner.json"), os.path.join(ws, "runner.json"))
    release = os.path.join(ws, "release")
    deadline = time.time() + 300
    while not os.path.exists(release) and time.time() < deadline:
        time.sleep(0.1)
    if os.path.exists(release) and open(release).read().strip() == "restart":
        os.execv(sys.executable, [sys.executable, "-I", "-m", "temper_ai.cli.main",
                                  "run-workflow", "--execution-id", args.execution_id])
    return 0
'''

#: The positive control's entry: the real exchange, without the runner's protection.
CONTROL_MAIN = r'''
import argparse
from temper_ai.spawner import box_bootstrap

box_bootstrap.receive(protect=lambda: None)
parser = argparse.ArgumentParser()
parser.add_argument("command")
parser.add_argument("--execution-id")
from temper_ai.cli.run_workflow import cmd_run_workflow
raise SystemExit(cmd_run_workflow(parser.parse_args()))
'''

#: A runner that never gets ready (the box is cancelled before it waits).
NEVER_READY_MAIN = "import time\ntime.sleep(600)\n"

#: A runner that waits for its delivery but never takes it (cancelled after ready).
STALLED_MAIN = r'''
import os, time
from temper_ai.spawner import box_bootstrap as bb
doc = bb.oneshot_doc()
params = bb.Params.of(doc["bootstrap"])
bb.protect_process()
bb._check_folder(params.dir, bb._mounts())
bb._publish(params.dir, bb.WAITING, {"pid": os.getpid(), "execution_id": doc["execution_id"],
                                     "generation": doc["generation"],
                                     "profile": os.environ["TEMPER_BOX_PROFILE_DIGEST"]})
time.sleep(600)
'''


def _code_tree(install: Install, main: str | None = None) -> None:
    """The box's temper_ai: the real entry and delivery code, stubs for the rest."""
    code = install.code
    shutil.rmtree(code)
    files = {
        "__init__.py": "",
        "cli/__init__.py": "",
        "cli/run_workflow.py": RUNNER,
        "integrations/__init__.py": "",
        "integrations/github/__init__.py": "",
        "integrations/github/secret.py": "def take():\n    pass\n",
        "spawner/__init__.py": "",
        **{f"cli/{name}.py": STUB_PARSER
           for name in ("linear", "github", "slack", "telegram", "notion", "events", "check",
                        "trim", "pi")},
    }
    for rel, text in files.items():
        (code / rel).parent.mkdir(parents=True, exist_ok=True)
        (code / rel).write_text(text)
    for rel in ("spawner/box_bootstrap.py", "spawner/box_view.py"):
        shutil.copyfile(REPO / "temper_ai" / rel, code / rel)
    if main is None:
        shutil.copyfile(REPO / "temper_ai" / "cli" / "main.py", code / "cli" / "main.py")
    else:
        (code / "cli" / "main.py").write_text(main)
    assert SYNTHETIC_MARK not in "".join(p.read_text() for p in code.rglob("*.py"))


# -- docker ---------------------------------------------------------------------------------------


@dataclass
class OneshotDocker:
    """DockerSpawner's ``run``: a fake template inspect, real detached boxes and real execs.

    ``on_exec`` may change the writer's command and stdin (a tampered delivery) or act
    while it runs (a cancelled box); the box is kept after it exits so its exit code and
    log can be read, and removed by cleanup().
    """

    install: Install
    on_exec: Callable[[list[str], dict], tuple[list[str], dict]] | None = None
    names: list[str] = field(default_factory=list)
    execs: list[subprocess.CompletedProcess] = field(default_factory=list)

    def __call__(self, cmd, **kwargs) -> subprocess.CompletedProcess:
        cmd = list(cmd)
        if cmd[1] == "inspect":
            return subprocess.CompletedProcess(cmd, 0, stdout=self.install.inspect(), stderr="")
        if cmd[1] == "run" and "--name" in cmd:
            cmd = [c for c in cmd if c != "--rm"]
            cmd[2:2] = ["--label", TEST_LABEL, "--label", OWN_LABEL]
            self.names.append(box_name(cmd))
        if cmd[1] == "exec" and self.on_exec is not None:
            cmd, kwargs = self.on_exec(cmd, kwargs)
        kwargs.setdefault("timeout", 120)
        result = subprocess.run(cmd, **kwargs)
        if cmd[1] == "exec":
            self.execs.append(result)
        return result

    def cleanup(self) -> None:
        for name in self.names:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)


def _docker(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout,
                          check=False)


def _running(name: str) -> bool:
    return _docker("inspect", "-f", "{{.State.Running}}", name).stdout.strip() == "true"


def _exit_code(name: str, wait: float = 60) -> int:
    deadline = time.monotonic() + wait
    while _running(name) and time.monotonic() < deadline:
        time.sleep(0.2)
    return int(_docker("inspect", "-f", "{{.State.ExitCode}}", name).stdout.strip())


#: Run inside the box as its user, from outside the runner (docker exec), as an agent tool
#: could: what of the runner and of docker-init can be read. Names and booleans only.
OUTSIDE = r'''
import ctypes, json, os, sys
mark = sys.argv[1].encode()
runner = int(sys.argv[2])
delivered = set(sys.argv[3].split(","))
libc = ctypes.CDLL(None, use_errno=True)
libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]

def environ(pid):
    try:
        data = open(f"/proc/{pid}/environ", "rb").read()
    except PermissionError:
        return "EACCES"
    keys = {e.split(b"=", 1)[0].decode() for e in data.split(b"\0") if e}
    return {"mark": mark in data, "delivered": sorted(delivered & keys)}

def memory(pid):
    try:
        maps = open(f"/proc/{pid}/maps").read().splitlines()
        mem = open(f"/proc/{pid}/mem", "rb", buffering=0)
    except PermissionError:
        return "EACCES"
    for line in maps:
        parts = line.split()
        if parts[1][0] != "r" or (len(parts) > 5 and parts[5] in ("[vvar]", "[vsyscall]")):
            continue
        lo, hi = (int(x, 16) for x in parts[0].split("-"))
        if hi - lo > (512 << 20):
            continue
        try:
            mem.seek(lo)
            if mark in mem.read(hi - lo):
                return "mark found"
        except OSError:
            continue
    return "read, no mark"

def fds(pid):
    try:
        return len(os.listdir(f"/proc/{pid}/fd"))
    except PermissionError:
        return "EACCES"

def ptrace(pid):
    if libc.ptrace(0x4206, pid, None, None) == 0:  # PTRACE_SEIZE; let go when this exits
        return "attached"
    return "errno %d" % ctypes.get_errno()

every = []
writers = 0
for entry in os.listdir("/proc"):
    if not entry.isdigit() or int(entry) == os.getpid():
        continue
    try:
        if b"--deliver" in open(f"/proc/{entry}/cmdline", "rb").read():
            writers += 1
        every.append(mark in open(f"/proc/{entry}/environ", "rb").read())
    except OSError:
        pass
print(json.dumps({
    "init": environ(1), "runner_environ": environ(runner), "runner_memory": memory(runner),
    "runner_fds": fds(runner), "runner_ptrace": ptrace(runner),
    "readable_environs_with_mark": sum(every), "writers": writers,
    "boot": sorted(os.listdir(sys.argv[4])),
}))
'''


def _outside(install: Install, name: str, runner_pid: int) -> dict:
    result = _docker("exec", "--user", install.user, name, INTERPRETER, "-I", "-S", "-c",
                     OUTSIDE, SYNTHETIC_MARK, str(runner_pid), ",".join(DELIVERED),
                     box_bootstrap.BOOT_DIR)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout)


def _report(workspace: Path, name: str, wait: float = 60) -> dict:
    path = workspace / "runner.json"
    deadline = time.monotonic() + wait
    while not path.exists() and time.monotonic() < deadline and _running(name):
        time.sleep(0.1)
    if not path.exists():
        logs = _docker("logs", name)
        pytest.fail("the runner wrote no report; its box said: "
                    + (logs.stdout + logs.stderr)[-3000:].replace(SYNTHETIC_MARK, "<mark>"))
    return json.loads(path.read_text())


# -- fixtures --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def image() -> tuple[str, str]:
    if not docker_ok():
        _unavailable("no docker")
    ref = box_image()
    if ref is None:
        _unavailable("no image (TEMPER_TEST_BOX_IMAGE, temper-ci-server or python:3.12-slim)")
    return ref, image_id(ref)


@pytest.fixture
def install(tmp_path, image) -> Install:
    ref, iid = image
    install = Install(tmp_path / "host", user=box_user(), image_ref=ref, image_id=iid,
                      extra_env=[f"SYNTH_DB_URL={DB_URL}", "TEMPER_API=http://server:8420"])
    return install.build()


@pytest.fixture(autouse=True)
def oneshot_install(monkeypatch):
    for name in ("TEMPER_BOX_ENV", "TEMPER_DOCKER_WORKSPACES", "TEMPER_DOCKER_IMAGE",
                 "TEMPER_SPAWNER", "TEMPER_EXECUTION_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(box_profile.BOUNDARY_ENV, box_profile.SEALED)
    monkeypatch.setenv(box_profile.BOOTSTRAP_ENV, box_bootstrap.ONESHOT)
    monkeypatch.setenv("TEMPER_DOCKER_RUN_COMMAND", RUN_COMMAND)
    yield
    left = subprocess.run(["docker", "ps", "-aq", "--filter", f"label={OWN_LABEL}"],
                          capture_output=True, text=True, timeout=60)
    for cid in left.stdout.split():
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=60)


def _start(install: Install, eid: str, *, main: str | None = None, on_exec=None,
           limits: dict | None = None) -> tuple[MemoryStore, OneshotDocker, DockerSpawner]:
    _code_tree(install, main)
    store = MemoryStore()
    store.add(eid, workspace=str(install.run_a), status="queued")
    docker = OneshotDocker(install, on_exec=on_exec)
    spawner = DockerSpawner(
        template_container="worker-self",
        workspace_lookup=lambda e: store.rows[e]["workspace"],
        run=docker, box_env=lambda: BOX_LIST, profile_store=store,
        worker_view=WorkerView(None), engine_launches=install.engine_table(),
        delivery_limits=limits,
    )
    return store, docker, spawner


def _failed(install: Install, eid: str, expect: str, **kwargs) -> tuple[str, MemoryStore, str]:
    """The delivery fails: a safe message, the box stopped, the delivery revoked."""
    store, docker, spawner = _start(install, eid, **kwargs)
    try:
        with pytest.raises(SpawnerError) as caught:
            spawner.spawn(eid)
        name = docker.names[0]
        message = str(caught.value)
        assert expect in message, message
        assert "the box was stopped and the delivery revoked" in message
        assert SYNTHETIC_MARK not in message
        assert not _running(name)
        record = store.record(eid)
        assert record["delivery"]["state"] == "revoked"
        assert SYNTHETIC_MARK not in json.dumps(record)
        logs = _docker("logs", name)
        assert SYNTHETIC_MARK not in logs.stdout + logs.stderr
        if "box refused: " in logs.stderr:  # the runner refused and ended itself
            assert _exit_code(name) == box_bootstrap.REFUSED_EXIT
        return message, store, logs.stderr
    finally:
        docker.cleanup()


# -- G02: the protected runner ------------------------------------------------------------------


def test_g02_a_oneshot_box_starts_clean_and_its_runner_refuses_reads(install):
    eid = run_id("g02-main")
    store, docker, spawner = _start(install, eid)
    try:
        handle = spawner.spawn(eid)
        (name,) = docker.names
        record = store.record(eid)
        assert record == handle.metadata["box_profile"]
        assert record["delivery"]["state"] == "consumed"
        assert record["doc"]["bootstrap"]["names"] == DELIVERED

        # Startup: nothing docker holds or shows carries a delivered name or value.
        shown = _docker("inspect", name).stdout
        assert SYNTHETIC_MARK not in shown
        config = json.loads(shown)[0]["Config"]
        assert not {e.split("=", 1)[0] for e in config["Env"]} & set(DELIVERED)
        assert config["Healthcheck"]["Test"] == ["NONE"]
        assert not any(SYNTHETIC_MARK in " ".join(e.args) for e in docker.execs)
        assert all(SYNTHETIC_MARK.encode() not in e.stdout + e.stderr for e in docker.execs)

        report = _report(install.run_a, name)
        outside = _outside(install, name, report["pid"])

        # docker-init (PID 1) and the runner's own start environment: no marker, no name.
        assert outside["init"] == {"mark": False, "delivered": []}
        assert report["start_environ_names"] == []
        # The runner: values in its own mapping only; not dumpable, no core files; every
        # child it starts (an error child too) starts without them.
        assert report["all_present"] and report["names"] == 2
        assert (report["dumpable"], report["core"]) == (0, [0, 0])
        assert report["child_leaks"] == []
        assert report["children_checked"] == ["close_fds False", "default", "error child",
                                              "os.system"]
        assert report["tools_allowed"]
        # Another process of the same user (an agent tool) can't read it.
        assert outside["runner_environ"] == "EACCES"
        assert outside["runner_memory"] == "EACCES"
        assert outside["runner_fds"] == "EACCES"
        assert outside["runner_ptrace"] == "errno 1"
        assert outside["readable_environs_with_mark"] == 0
        # After the ack: no delivery source or destination, no writer, no descriptor.
        assert report["boot"] == outside["boot"] == [box_bootstrap.ACK]
        assert report["fds_into_boot"] == []
        assert outside["writers"] == 0

        # Restart: a replacement interpreter (exec resets the protection) has to take a
        # delivery of its own, and a box gives one only once.
        (install.run_a / "release").write_text("restart")
        assert _exit_code(name) == box_bootstrap.REFUSED_EXIT
        logs = _docker("logs", name)
        assert "box refused: the delivery folder is not empty" in logs.stderr
        assert "one consumption per box" in logs.stderr
        assert SYNTHETIC_MARK not in logs.stdout + logs.stderr
    finally:
        docker.cleanup()


def test_g02_positive_control_an_unprotected_runner_keeps_what_it_read(install):
    """The same box and exchange without the runner's protection: the value it read,
    closed and removed is still in its memory, readable by any process of the user."""
    eid = run_id("g02-control")
    store, docker, spawner = _start(install, eid, main=CONTROL_MAIN)
    try:
        spawner.spawn(eid)
        (name,) = docker.names
        report = _report(install.run_a, name)
        outside = _outside(install, name, report["pid"])
        assert report["dumpable"] == 1 and report["boot"] == [box_bootstrap.ACK]
        assert outside["runner_memory"] == "mark found"
        assert outside["runner_ptrace"] == "attached"
        assert outside["runner_environ"] == {"mark": False, "delivered": []}
        assert isinstance(outside["runner_fds"], int)
        assert store.record(eid)["delivery"]["state"] == "consumed"
        (install.run_a / "release").write_text("done")
        assert _exit_code(name) == 0
    finally:
        docker.cleanup()


# -- G02: what goes wrong ---------------------------------------------------------------------------


def _tamper(change: Callable[[dict], None] | None = None, *, extra: bytes = b"",
            args: dict[str, str] | None = None):
    """Change the envelope's header (and the writer's own arguments) on its way in."""
    def on_exec(cmd: list[str], kwargs: dict) -> tuple[list[str], dict]:
        data = bytearray(kwargs["input"])
        if change is not None:
            head = json.loads(bytes(data[:box_bootstrap.HEADER_BYTES]).decode("ascii"))
            change(head)
            raw = json.dumps(head).encode("ascii").ljust(box_bootstrap.HEADER_BYTES - 1)
            data[:box_bootstrap.HEADER_BYTES] = raw + b"\n"
        for flag, value in (args or {}).items():
            cmd[cmd.index(flag) + 1] = value
        return cmd, {**kwargs, "input": bytes(data + extra)}
    return on_exec


#: (how the envelope is changed, the failure, whether the runner itself refused it: the
#: writer refuses first what it can check, the run, the generation and the size)
@pytest.mark.parametrize(("on_exec", "expect"), [
    (_tamper(lambda h: h.update(generation=0)),
     "refused: wrong envelope: not this box's run and generation"),
    (_tamper(lambda h: h.update(execution_id="another-run")),
     "refused: wrong envelope: not this box's run and generation"),
    (_tamper(lambda h: h.update(profile="sha256:" + "0" * 64)),
     "refused: wrong envelope: it is for another box profile"),
    (_tamper(lambda h: h.update(expires_at=h["issued_at"] - 1)),
     "refused: wrong envelope: its times are not the profile's"),
    (_tamper(extra=b"x" * 300_000), "refused: oversized envelope"),
    (_tamper(lambda h: h.update(length=h["length"] + 5)),
     "refused: malformed envelope: its length is not the leaf's"),
], ids=["stale", "another run", "wrong profile", "malformed times", "oversized",
        "malformed length"])
def test_g02_a_wrong_stale_oversized_or_malformed_envelope_stops_the_box(install, on_exec,
                                                                           expect):
    _, _, stderr = _failed(install, run_id("g02-bad"), expect, on_exec=on_exec)
    if "not this box's" in expect or "oversized" in expect:  # the writer's refusals
        assert "box refused" not in stderr  # the runner was still waiting when stopped
    else:
        assert "box refused: " + expect.split(": ", 1)[1] in stderr


def test_g02_cancelled_before_ready_the_box_is_stopped_and_nothing_written(install):
    _failed(install, run_id("g02-never-ready"),
            "timeout: timeout: the runner was not waiting within 8s",
            main=NEVER_READY_MAIN, limits=FAST)


def test_g02_no_acknowledgement_takes_the_delivery_back(install):
    _failed(install, run_id("g02-no-ack"), "timeout: timeout: no acknowledgement within 4s",
            main=STALLED_MAIN, limits=FAST)


def test_g02_cancelled_after_ready_the_delivery_is_revoked(install):
    """The box is killed while the writer waits for the runner's acknowledgement."""
    def kill_soon(cmd: list[str], kwargs: dict) -> tuple[list[str], dict]:
        name = cmd[cmd.index("--user") + 2]
        threading.Timer(2.0, lambda: _docker("kill", name)).start()
        return cmd, kwargs

    _failed(install, run_id("g02-cancel"), "error: the writer gave no status", main=STALLED_MAIN,
            on_exec=kill_soon, limits={**FAST, "ack": 30})

