"""DockerSpawner liveness and signals by judged container id (S1-D).

A run's box is named ``temper-run-<execution_id>`` for every dispatch, so after dispatch A
is judged a later dispatch B may already hold the name. A handle that carries the judged
id (``JUDGED_CONTAINER_ID``, taken from the reaper's RowGeneration.container_id) is
checked and signalled by that id; ``is_gone`` and spawn's wait for the old box keep asking
by name, and a handle without the key behaves as before.

Everything here runs against a counting fake Docker that records each argv and keeps its
own containers (unique names, like Docker): no docker binary, daemon, network or model.
Each guard has a bite: the module rebuilt from its own source with the guard reverted
must get exactly its declared cases wrong.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType

import pytest

from temper_ai.runner.row_generation import RowGeneration
from temper_ai.spawner import docker_spawner
from temper_ai.spawner.base import SpawnerBusy, SpawnerError
from temper_ai.worker_proto import ProcessHandle, SpawnerKind

RUN = "exec-judged"
NAME = f"temper-run-{RUN}"
A = "a1" * 32   # the judged dispatch's container id (64 hex, as `docker run --detach` prints)
B = "b2" * 32   # a later dispatch of the same run, holding the same name


# --- The counting fake ------------------------------------------------------

@dataclass
class Box:
    name: str
    running: bool


@dataclass
class CountingDocker:
    """A tiny Docker: containers by id with unique names; answers inspect and kill only."""

    boxes: dict[str, Box] = field(default_factory=dict)
    daemon_down: bool = False
    calls: list[list[str]] = field(default_factory=list)
    signals: list[tuple[str, str]] = field(default_factory=list)   # (container id, signal)

    def add(self, cid: str, name: str, *, running: bool) -> None:
        assert all(b.name != name for b in self.boxes.values()), "Docker names are unique"
        self.boxes[cid] = Box(name, running)

    def _find(self, target: str) -> str | None:
        if target in self.boxes:
            return target
        return next((cid for cid, box in self.boxes.items() if box.name == target), None)

    def __call__(self, cmd, **_kwargs) -> subprocess.CompletedProcess:
        cmd = list(cmd)
        self.calls.append(cmd)
        if self.daemon_down:
            return _done(cmd, 1, err="Cannot connect to the Docker daemon at unix:///var/run/docker.sock")
        target = cmd[-1]
        cid = self._find(target)
        if cmd[1:3] == ["inspect", "--format"] and len(cmd) == 5:
            if cid is None:
                return _done(cmd, 1, err=f"Error: No such object: {target}")
            box = self.boxes[cid]
            if cmd[3] == "{{.State.Running}}":
                return _done(cmd, 0, out="true\n" if box.running else "false\n")
            if cmd[3] == "{{.State.Status}}":
                return _done(cmd, 0, out="running\n" if box.running else "exited\n")
        if cmd[1:3] == ["kill", "--signal"] and len(cmd) == 5:
            if cid is None:
                return _done(cmd, 1, err=f"Error response from daemon: No such container: {target}")
            if not self.boxes[cid].running:
                return _done(cmd, 1, err=(f"Error response from daemon: cannot kill container: "
                                          f"{target}: container {cid} is not running"))
            self.signals.append((cid, cmd[3]))
            if cmd[3] == "KILL":
                self.boxes[cid].running = False
            return _done(cmd, 0, out=f"{target}\n")
        raise AssertionError(f"the fake Docker has no answer for {cmd}")

    def targets(self) -> list[tuple[str, str]]:
        """(subcommand, last argument) of every call, in order."""
        return [(c[1], c[-1]) for c in self.calls]


def _done(cmd: list[str], code: int, *, out: str = "", err: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(cmd, code, stdout=out, stderr=err)


@pytest.fixture(autouse=True)
def _no_real_docker(monkeypatch):
    """Any path that reached the real subprocess.run would fail here, not touch a daemon."""
    def refuse(*args, **kwargs):
        raise AssertionError(f"real subprocess call attempted: {args!r}")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


def _spawner(module: ModuleType, docker: CountingDocker):
    return module.DockerSpawner(template_container="worker-self", run=docker,
                                workspace_lookup=lambda _eid: "/nonexistent-workspace",
                                profile_store=object())


def _judged_handle(module: ModuleType, container_id) -> ProcessHandle:
    """The reaper's handle for the dispatch it judged: the id from its one snapshot."""
    return ProcessHandle(kind=SpawnerKind.docker, handle=NAME,
                         metadata={"execution_id": RUN, module.JUDGED_CONTAINER_ID: container_id})


def _generation(container_id: str | None) -> RowGeneration:
    return RowGeneration.from_snapshot({"status": "running", "attempts": 2,
                                        "spawner_kind": "docker", "spawner_handle": NAME,
                                        "container_id": container_id})


def _name_handle(**extra) -> ProcessHandle:
    return ProcessHandle(kind=SpawnerKind.docker, handle=NAME, metadata={"execution_id": RUN, **extra})


def _raises(fn: Callable[[], object]) -> str:
    try:
        fn()
    except SpawnerBusy:
        return "busy"
    except SpawnerError:
        return "error"
    return "ok"


# --- Cases: each returns what it observed; expected is what is right --------

def case_happy(m: ModuleType) -> tuple:
    """One whole judged pass: id from RowGeneration, liveness, TERM, KILL, then the name
    questions (is_gone, spawn's wait) still by name."""
    docker = CountingDocker()
    docker.add(A, NAME, running=True)
    spawner = _spawner(m, docker)
    handle = _judged_handle(m, _generation(A).container_id)
    alive = spawner.is_alive(handle)
    spawner.kill(handle)
    spawner.kill(handle, force=True)
    after = spawner.is_alive(handle)
    gone = spawner.is_gone(handle)
    spawn = _raises(lambda: spawner.spawn(RUN))
    return alive, after, gone, spawn, docker.signals, docker.targets()


HAPPY = (True, False, False, "busy", [(A, "TERM"), (A, "KILL")],
         [("inspect", A), ("kill", A), ("kill", A), ("inspect", A),
          ("inspect", NAME), ("inspect", NAME)])


def _stale(running_a: bool | None) -> CountingDocker:
    """B holds the name and runs; A is gone (None) or still there under another name."""
    docker = CountingDocker()
    if running_a is not None:
        docker.add(A, "temper-run-renamed-away", running=running_a)
    docker.add(B, NAME, running=True)
    return docker


def case_stale_alive(m):
    docker = _stale(None)
    return _spawner(m, docker).is_alive(_judged_handle(m, A)), docker.targets()


def case_stale_term(m):
    docker = _stale(None)
    outcome = _raises(lambda: _spawner(m, docker).kill(_judged_handle(m, A)))
    return outcome, docker.signals, docker.targets()


def case_stale_kill(m):
    docker = _stale(None)
    outcome = _raises(lambda: _spawner(m, docker).kill(_judged_handle(m, A), force=True))
    return outcome, docker.signals, docker.targets()


def case_stale_live_a(m):
    """A still runs (not under the run's name); B holds the name: the signal reaches A only."""
    docker = _stale(True)
    spawner = _spawner(m, docker)
    alive = spawner.is_alive(_judged_handle(m, A))
    spawner.kill(_judged_handle(m, A))
    spawner.kill(_judged_handle(m, A), force=True)
    return alive, docker.signals, docker.boxes[B].running


def case_not_running(m):
    """A exited but not yet removed: not alive; TERM and KILL are already done, not errors."""
    docker = CountingDocker()
    docker.add(A, NAME, running=False)
    spawner = _spawner(m, docker)
    handle = _judged_handle(m, A)
    return (spawner.is_alive(handle), _raises(lambda: spawner.kill(handle)),
            _raises(lambda: spawner.kill(handle, force=True)), docker.signals, docker.targets())


def case_daemon_down(m):
    """No answer from the daemon is no verdict: every judged call raises."""
    docker = CountingDocker(daemon_down=True)
    spawner = _spawner(m, docker)
    handle = _judged_handle(m, A)
    return (_raises(lambda: spawner.is_alive(handle)), _raises(lambda: spawner.kill(handle)),
            _raises(lambda: spawner.kill(handle, force=True)), docker.targets())


def case_is_gone_by_name(m):
    """B holds the name: the name is not free, whatever became of the judged A."""
    docker = _stale(None)
    return _spawner(m, docker).is_gone(_judged_handle(m, A)), docker.targets()


def case_spawn_waits_by_name(m):
    docker = _stale(None)
    return _raises(lambda: _spawner(m, docker).spawn(RUN)), docker.targets()


def case_name_only(m):
    """No judged key: today's behaviour, the box holding the name."""
    docker = _stale(None)
    spawner = _spawner(m, docker)
    alive = spawner.is_alive(_name_handle())
    spawner.kill(_name_handle())
    return alive, docker.signals, docker.targets()


def case_spawn_handle_container_id(m):
    """A handle spawn returned carries "container_id": that is NOT a judged id; by name."""
    docker = _stale(None)
    spawner = _spawner(m, docker)
    handle = _name_handle(container_id=A, image="img")
    alive = spawner.is_alive(handle)
    spawner.kill(handle, force=True)
    return alive, docker.signals, docker.targets()


def _bad(value):
    def case(m):
        docker = _stale(None)
        spawner = _spawner(m, docker)
        handle = _judged_handle(m, value)
        return (_raises(lambda: spawner.is_alive(handle)), _raises(lambda: spawner.kill(handle)),
                _raises(lambda: spawner.kill(handle, force=True)), docker.calls)
    return case


BAD = ("error", "error", "error", [])


@dataclass(frozen=True)
class Case:
    id: str
    run: Callable[[ModuleType], tuple]
    expected: tuple


CASES = {c.id: c for c in [
    Case("HAPPY", case_happy, HAPPY),
    Case("STALE-ALIVE", case_stale_alive, (False, [("inspect", A)])),
    Case("STALE-TERM", case_stale_term, ("ok", [], [("kill", A)])),
    Case("STALE-KILL", case_stale_kill, ("ok", [], [("kill", A)])),
    Case("STALE-LIVE-A", case_stale_live_a, (True, [(A, "TERM"), (A, "KILL")], True)),
    Case("NOT-RUNNING", case_not_running,
         (False, "ok", "ok", [], [("inspect", A), ("kill", A), ("kill", A)])),
    Case("DAEMON-DOWN", case_daemon_down,
         ("error", "error", "error", [("inspect", A), ("kill", A), ("kill", A)])),
    Case("IS-GONE-NAME", case_is_gone_by_name, (False, [("inspect", NAME)])),
    Case("SPAWN-WAIT-NAME", case_spawn_waits_by_name, ("busy", [("inspect", NAME)])),
    Case("NAME-ONLY", case_name_only, (True, [(B, "TERM")], [("inspect", NAME), ("kill", NAME)])),
    Case("SPAWN-HANDLE-CID", case_spawn_handle_container_id,
         (True, [(B, "KILL")], [("inspect", NAME), ("kill", NAME)])),
    Case("BAD-NONE", _bad(None), BAD),
    Case("BAD-EMPTY", _bad(""), BAD),
    Case("BAD-NAME", _bad(NAME), BAD),
    Case("BAD-UPPER", _bad(A.upper()), BAD),
    Case("BAD-SHORT", _bad(A[:12]), BAD),   # the short id `docker ps` shows: a prefix
    Case("BAD-LONG", _bad(A + "a"), BAD),
    Case("BAD-TRAILING-LF", _bad(A + "\n"), BAD),
    Case("BAD-INT", _bad(12345678901234), BAD),
]}


def _outcome(case: Case, module: ModuleType):
    try:
        return case.run(module)
    except Exception as exc:  # noqa: BLE001 - a bitten module may fail any way; that is wrong
        return ("raised", type(exc).__name__, str(exc))


def _wrong(module: ModuleType) -> set[str]:
    return {cid for cid, case in CASES.items() if _outcome(case, module) != case.expected}


# --- The cases on the real module -----------------------------------------------

@pytest.mark.parametrize("case_id", list(CASES))
def test_each_case_gives_its_known_answer(case_id):
    case = CASES[case_id]
    assert case.run(docker_spawner) == case.expected


def test_the_judged_id_comes_from_the_row_generation_contract():
    """S1-G's snapshot keeps the dispatch's id; an absent one stays None, which the
    reaper (S1-F) refuses before any call: this module never turns it into a name."""
    assert _generation(A).container_id == A
    assert _generation(None).container_id is None
    assert _generation("").container_id is None
    assert CASES["BAD-NONE"].run(docker_spawner)[3] == []


def test_the_judged_handle_still_names_the_run_for_name_questions():
    """The judged key rides beside execution_id; name-based answers keep working."""
    handle = _judged_handle(docker_spawner, A)
    assert docker_spawner.DockerSpawner._name_for(handle) == NAME


# --- Bites: each guard reverted gets exactly its declared cases wrong ---------------

JUDGED = {"HAPPY", "STALE-ALIVE", "STALE-TERM", "STALE-KILL", "STALE-LIVE-A",
          "NOT-RUNNING", "DAEMON-DOWN"}
BAD_CASES = {"BAD-NONE", "BAD-EMPTY", "BAD-NAME", "BAD-UPPER", "BAD-SHORT", "BAD-LONG",
             "BAD-TRAILING-LF", "BAD-INT"}

BITES: dict[str, tuple[list[tuple[str, str]], set[str]]] = {
    # The id-to-name choice reverted: judged calls go to whoever holds the name.
    "M-ID-TO-NAME": ([("        return judged\n", "        return cls._name_for(handle)\n")],
                     JUDGED),
    # is_gone switched to the judged id: says "gone" while B holds the name.
    "M-IS-GONE-BY-ID": ([('"{{.State.Running}}", self._name_for(handle)],',
                          '"{{.State.Running}}", self._judged_id_or_name(handle)],')],
                        {"HAPPY", "IS-GONE-NAME"}),
    # A bad judged value quietly falls back to the name.
    "M-BAD-FALLS-BACK": ([("            raise SpawnerError(\n                f\"Judged container id",
                           "            return cls._name_for(handle)\n            raise SpawnerError(\n"
                           "                f\"Judged container id")],
                         BAD_CASES),
    # No id-shape check: an empty or name-shaped value is sent to Docker.
    "M-NO-ID-SHAPE": ([(" or not _DOCKER_ID.fullmatch(judged)", "")],
                      BAD_CASES - {"BAD-NONE", "BAD-INT"}),
    # match with $ accepts the position before one final LF, not only the whole id.
    "M-FULLMATCH-TO-MATCH": ([("_DOCKER_ID.fullmatch(judged)", "_DOCKER_ID.match(judged)")],
                            {"BAD-TRAILING-LF"}),
    # Any id prefix accepted: a short prefix that a container's name could win.
    "M-PREFIX-OK": ([('r"^[0-9a-f]{64}$"', 'r"^[0-9a-f]{12,64}$"')], {"BAD-SHORT"}),
    # The spawn handle's own "container_id" taken as the judged key.
    "M-SPAWN-KEY": ([('JUDGED_CONTAINER_ID = "judged_container_id"',
                      'JUDGED_CONTAINER_ID = "container_id"')],
                    {"SPAWN-HANDLE-CID"}),
}


def _mutant(mutations: list[tuple[str, str]], monkeypatch) -> ModuleType:
    """docker_spawner built again from its own source with one guard reverted."""
    source = inspect.getsource(docker_spawner)
    for find, replace in mutations:
        assert source.count(find) == 1, f"docker_spawner doesn't hold this once: {find!r}"
        source = source.replace(find, replace)
    mutant = ModuleType("temper_ai.spawner.docker_spawner_bitten")
    mutant.__file__ = docker_spawner.__file__
    monkeypatch.setitem(sys.modules, mutant.__name__, mutant)
    exec(compile(source, docker_spawner.__file__, "exec"), mutant.__dict__)  # noqa: S102
    return mutant


def test_the_real_module_gets_no_case_wrong():
    assert _wrong(docker_spawner) == set()


@pytest.mark.parametrize("bite", list(BITES))
def test_each_guard_has_a_bite(bite, monkeypatch):
    mutations, expected = BITES[bite]
    assert _wrong(_mutant(mutations, monkeypatch)) == expected
