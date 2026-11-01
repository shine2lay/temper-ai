"""The shared test CPU's host entry (docs/shared-test-cpu-host.md): its fixed cases.

- Host answer: the installed launcher's membership answer, and a clean absence told apart from a
  path that can't be ruled out.
- Conftest entry: which restart each host answer, run shape and marker gets.
- The whole pre-commit hook against a fake host whose slice is real process ancestry (a process
  the fake launcher placed, and everything below it), every phase recorded with where it ran.
- Real pytest runs through the copied conftest, the same fake host and a fake wt.
- A nested run through this host's real wt, in a scratch pool of one slot.

A child these tests start is only ever seen as a `Ran`: its exit code and fixed questions about
what it said, never its output or argv, so none of it can reach a failure's text.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest, machine_slot

ROOT = Path(__file__).resolve().parents[1]
MARKER = "TEMPER_PYTEST_MACHINE_SLOT"
RESTART = "TEMPER_TEST_CPU_RESTART"
LAUNCHER = "/usr/local/libexec/test-cpu/bin/test-cpu"
POLICY = "/etc/agent-tools/test-cpu.json"
SKIP_VARS = ("PYTEST_XDIST_WORKER", "PYTEST_CURRENT_TEST", "CI", "GITHUB_ACTIONS", MARKER)
# What an outer run could carry into the runs these tests start.
OUTER = (*SKIP_VARS, RESTART, "PYTEST_ADDOPTS", "TEMPER_TEST_DATABASE_URL", "PRECOMMIT_PG",
         "PRECOMMIT_PYTEST_WORKERS", "PYTEST_XDIST_AUTO_NUM_WORKERS")


def test_launcher_policy_exit_and_query_time_are_fixed():
    fixed = (machine_slot.TEST_CPU, machine_slot.POLICY, machine_slot.EXIT_PLACEMENT, machine_slot.QUERY_SECONDS)
    assert fixed == (LAUNCHER, POLICY, 125, 60)


# ─── Host answer ─────────────────────────────────────────────────────────────


@pytest.fixture
def paths(tmp_path, monkeypatch, request):
    """Scratch launcher and policy paths, both cleanly absent to begin with."""
    root = tmp_path / "host"
    root.mkdir()
    cli = root / "libexec/test-cpu/bin/test-cpu"
    policy = root / "etc/agent-tools/test-cpu.json"
    monkeypatch.setattr(machine_slot, "TEST_CPU", str(cli))
    monkeypatch.setattr(machine_slot, "POLICY", str(policy))
    locked = []
    request.addfinalizer(lambda: [p.chmod(0o755) for p in locked])
    return SimpleNamespace(root=root, cli=cli, policy=policy, locked=locked)


def answer(path, out, code=0, sleep=0):
    """A fixed stand-in for the installed launcher: one answer (printf %b: \\0377 is a raw byte), one exit code."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"exec sleep {sleep}\n" if sleep else f"printf '%b' '{out}'\nexit {code}\n"
    path.write_text(f"#!/bin/sh\n{body}")
    path.chmod(0o755)


def lock(p, folder):
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o600)
    p.locked.append(folder)


def test_clean_absence_is_inactive(paths):
    assert machine_slot.host_placement() == "inactive"
    paths.cli.parent.mkdir(parents=True)
    paths.policy.parent.mkdir(parents=True)
    assert machine_slot.host_placement() == "inactive"


POLICY_NOT_RULED_OUT = {
    "policy-present": lambda p: (p.policy.parent.mkdir(parents=True), p.policy.write_text("{}")),
    "policy-folder": lambda p: p.policy.mkdir(parents=True),
    "policy-dangling-link": lambda p: (p.policy.parent.mkdir(parents=True), p.policy.symlink_to(p.root / "nowhere")),
    "parent-is-a-file": lambda p: (p.root / "etc").write_text(""),
    "parent-unsearchable": lambda p: lock(p, p.root / "etc"),
    "parent-dangling-link": lambda p: (p.root / "etc").symlink_to(p.root / "nowhere"),
    "parent-link-to-folder": lambda p: ((p.root / "real/agent-tools").mkdir(parents=True), (p.root / "etc").symlink_to(p.root / "real")),
}
LAUNCHER_NOT_RULED_OUT = {
    "parent-is-a-file": lambda p: (p.root / "libexec").write_text(""),
    "parent-unsearchable": lambda p: lock(p, p.root / "libexec/test-cpu"),
    "parent-link-to-folder": lambda p: ((p.root / "real/bin").mkdir(parents=True), (p.root / "libexec").mkdir(), (p.root / "libexec/test-cpu").symlink_to(p.root / "real")),
    "launcher-dangling-link": lambda p: (p.cli.parent.mkdir(parents=True), p.cli.symlink_to(p.root / "nowhere")),
}


@pytest.mark.parametrize("make", POLICY_NOT_RULED_OUT.values(), ids=POLICY_NOT_RULED_OUT.keys())
def test_launcher_missing_with_a_policy_that_cant_be_ruled_out_fails(paths, make):
    if os.geteuid() == 0:
        pytest.skip("root searches any folder")
    make(paths)
    with pytest.raises(machine_slot.HostEntryError):
        machine_slot.host_placement()


@pytest.mark.parametrize("make", LAUNCHER_NOT_RULED_OUT.values(), ids=LAUNCHER_NOT_RULED_OUT.keys())
def test_launcher_that_cant_be_ruled_out_fails(paths, make):
    if os.geteuid() == 0:
        pytest.skip("root searches any folder")
    make(paths)
    with pytest.raises(machine_slot.HostEntryError):
        machine_slot.host_placement()


@pytest.mark.parametrize(("out", "code", "expected"), [
    ('{"cgroup":"/u","mode":"absent","inside":false}', 1, "inactive"),
    ('{"cgroup":"/u","mode":"inactive","slice":"testcpu.slice","inside":false,"parentOk":true}', 1, "inactive"),
    ('{"cgroup":"/testcpu.slice/a","mode":"inactive","slice":"testcpu.slice","inside":true,"parentOk":true}', 0, "inactive"),
    ('{"cgroup":"/testcpu.slice/a","mode":"enabled","slice":"testcpu.slice","inside":true,"parentOk":true}', 0, "inside"),
    ('{"cgroup":"/u","mode":"enabled","slice":"testcpu.slice","inside":false,"parentOk":true}', 1, "outside"),
    ('{"cgroup":"/u","mode":"enabled","slice":"testcpu.slice","inside":false,"parentOk":false}', 1, "outside"),
], ids=["absent", "inactive", "inactive-inside", "inside", "outside", "outside-parent-broken"])
def test_launcher_answer(paths, out, code, expected):
    answer(paths.cli, out, code)
    assert machine_slot.host_placement() == expected


@pytest.mark.parametrize(("out", "code"), [
    ('{"cgroup":"/u","mode":"invalid","inside":false}', 1),
    ('{"error":"cgroup-unreadable"}', 1),
    ('{"cgroup":', 1),
    ("", 1),
    ("[]", 1),
    ('{"cgroup":"/u","mode":"enabled","inside":false}', 0),
    ('{"cgroup":"/t","mode":"enabled","inside":true}', 1),
    ('{"cgroup":"/u","mode":"enabled"}', 1),
    ('{"cgroup":"/u","mode":"on","inside":false}', 1),
    ('{"cgroup":"/u","mode":"inactive","inside":false}', 2),
    ('{"cgroup":"/u","mode":"inactive","inside":false}', 125),
    ('{"cgroup":"/u","mode":"enabled","inside":false}\\0377', 1),
], ids=["invalid", "error", "malformed", "empty", "not-an-object", "exit0-outside", "exit1-inside",
        "no-inside", "unknown-mode", "usage-exit", "placement-exit", "invalid-utf8"])
def test_unusable_launcher_answer_fails(paths, out, code):
    answer(paths.cli, out, code)
    with pytest.raises(machine_slot.HostEntryError):
        machine_slot.host_placement()


def test_launcher_that_cant_run_fails(paths):
    answer(paths.cli, '{"cgroup":"/u","mode":"inactive","inside":false}', 1)
    paths.cli.chmod(0o644)
    with pytest.raises(machine_slot.HostEntryError, match="not an executable file"):
        machine_slot.host_placement()
    paths.cli.unlink()
    paths.cli.mkdir()
    with pytest.raises(machine_slot.HostEntryError, match="not an executable file"):
        machine_slot.host_placement()


def test_launcher_that_hangs_fails(paths, monkeypatch):
    monkeypatch.setattr(machine_slot, "QUERY_SECONDS", 1)
    answer(paths.cli, "", sleep=30)
    started = time.monotonic()
    with pytest.raises(machine_slot.HostEntryError, match="timed out"):
        machine_slot.host_placement()
    assert time.monotonic() - started < 15


# ─── Conftest entry ──────────────────────────────────────────────────────────


class Restart(Exception):
    """exec does not return; this stand-in must not be swallowed."""


COMMAND = ["/venv/python", "-m", "pytest", "tests/x.py"]
WT = ["wt", "slot", "--", *COMMAND]
PLACE = [LAUNCHER, "exec", "--quiet", "--", *COMMAND]
OWN = "4242:777"
PARALLEL = ["auto", "logical", 4, 1]
SERIAL = [None, 0]


@pytest.fixture
def entry(monkeypatch):
    """The entry with a pinned host answer, a fake exec and an environment of its own."""
    environ = {}
    state = SimpleNamespace(where="outside", wt="/fake/wt", parents=["1:1"], fail=None, attempts=[], environ=environ)

    def execute(program, argv):
        state.attempts.append((program, argv, environ.get(MARKER), environ.get(RESTART)))
        raise state.fail or Restart

    def host():
        if isinstance(state.where, Exception):
            raise state.where
        return state.where

    def parents():
        if isinstance(state.parents, Exception):
            raise state.parents
        yield from state.parents

    monkeypatch.setattr(machine_slot, "os", SimpleNamespace(environ=environ, execvp=execute, getpid=lambda: 4242))
    monkeypatch.setattr(machine_slot.shutil, "which", lambda name: state.wt if name == "wt" else None)
    monkeypatch.setattr(machine_slot, "host_placement", host)
    monkeypatch.setattr(machine_slot, "_ancestors", parents)
    monkeypatch.setattr(machine_slot, "_process", lambda pid: (f"{pid}:777", 1))
    monkeypatch.setattr(machine_slot, "TEST_CPU", LAUNCHER)
    monkeypatch.setattr(machine_slot.sys, "orig_argv", ["/orig/python", *COMMAND[1:]])
    monkeypatch.setattr(machine_slot.sys, "executable", COMMAND[0])
    return state


def enter(workers):
    """The entry's restart, if any: exec never returns."""
    try:
        machine_slot.enter_machine_slot(workers)
    except Restart:
        return True
    return False


@pytest.mark.parametrize("workers", PARALLEL)
def test_inside_parallel_takes_a_slot_and_is_not_placed_again(entry, workers):
    entry.where = "inside"
    assert enter(workers)
    assert entry.attempts == [("wt", WT, "1", None)]


@pytest.mark.parametrize("workers", SERIAL)
def test_inside_serial_runs_where_it_is(entry, workers):
    entry.where = "inside"
    assert not enter(workers)
    assert entry.attempts == [] and entry.environ == {}


@pytest.mark.parametrize("name", SKIP_VARS)
@pytest.mark.parametrize("value", ["1", ""], ids=["set", "empty"])
def test_inside_marked_runs_where_it_is(entry, name, value):
    entry.where = "inside"
    entry.environ[name] = value
    assert not enter("auto")
    assert entry.attempts == [] and entry.environ == {name: value}


@pytest.mark.parametrize("where", ["inside", "outside"])
def test_enabled_parallel_without_wt_fails(entry, where):
    entry.where, entry.wt = where, None
    with pytest.raises(machine_slot.HostEntryError, match="wt is not on PATH"):
        enter(4)
    assert entry.attempts == [] and entry.environ == {}


@pytest.mark.parametrize("workers", PARALLEL)
def test_outside_parallel_is_admitted_and_placed_through_wt(entry, workers):
    assert enter(workers)
    assert entry.attempts == [("wt", WT, "1", OWN)]


@pytest.mark.parametrize("workers", SERIAL)
def test_outside_serial_is_placed(entry, workers):
    assert enter(workers)
    assert entry.attempts == [(LAUNCHER, PLACE, None, OWN)]


@pytest.mark.parametrize("name", SKIP_VARS)
@pytest.mark.parametrize("value", ["1", ""], ids=["set", "empty"])
def test_outside_marked_is_still_placed(entry, name, value):
    entry.environ[name] = value
    assert enter("auto")
    assert entry.attempts == [(LAUNCHER, PLACE, value if name == MARKER else None, OWN)]


@pytest.mark.parametrize(("where", "workers", "program"), [
    ("inside", "auto", "wt"), ("outside", "auto", "wt"), ("outside", None, LAUNCHER),
], ids=["inside-wt", "outside-wt", "outside-launcher"])
def test_failed_restart_fails_and_puts_the_environment_back(entry, where, workers, program):
    entry.where = where
    entry.environ[RESTART] = "9:9"
    entry.fail = OSError("gone\nbetween lookup and exec")
    with pytest.raises(machine_slot.HostEntryError, match=f"couldn't restart under {program} \\(gone between lookup and exec\\)"):
        enter(workers)
    assert len(entry.attempts) == 1
    assert entry.environ == {RESTART: "9:9"}


def test_own_restart_still_outside_fails_instead_of_looping(entry):
    entry.environ[RESTART] = "1:1"
    with pytest.raises(machine_slot.HostEntryError, match="yet still outside"):
        enter(None)
    assert entry.attempts == []


def test_own_restart_run_in_place_still_outside_fails(entry):
    # A launcher may exec its command in place: the restarted run is then the restarting process.
    entry.environ[RESTART] = OWN
    with pytest.raises(machine_slot.HostEntryError, match="yet still outside"):
        enter(None)
    assert entry.attempts == []


@pytest.mark.parametrize("record", ["5:5", "4242:1"], ids=["unrelated", "own-pid-other-start"])
def test_restart_record_of_no_parent_is_ignored(entry, record):
    # Another process that had this pid has another start time: its record isn't this run's.
    entry.environ[RESTART] = record
    assert enter(None)
    assert entry.attempts == [(LAUNCHER, PLACE, None, OWN)]


def test_restart_record_with_unreadable_parents_fails(entry):
    entry.environ[RESTART] = "1:1"
    entry.parents = OSError("no /proc")
    with pytest.raises(machine_slot.HostEntryError, match="can't be read"):
        enter(None)
    assert entry.attempts == []


@pytest.mark.parametrize("where", ["inside", "inactive"])
def test_restart_record_only_matters_outside(entry, where):
    entry.where = where
    entry.environ[RESTART] = "1:1"
    assert not enter(None)
    assert entry.attempts == []


def test_host_that_cant_be_read_stops_every_run(entry):
    entry.where = machine_slot.HostEntryError("policy there, launcher not")
    for workers in (*PARALLEL, *SERIAL):
        with pytest.raises(machine_slot.HostEntryError, match="policy there"):
            enter(workers)
    assert entry.attempts == []


class Config:
    def __init__(self, worker=False):
        if worker:
            self.workerinput = {"workerid": "gw0"}

    def getoption(self, name, default):
        assert (name, default) == ("numprocesses", None)
        return 4


def test_conftest_never_restarts_an_xdist_worker(monkeypatch):
    calls = []
    monkeypatch.setattr(conftest, "enter_machine_slot", calls.append)
    conftest.pytest_configure(Config(worker=True))
    assert calls == []
    conftest.pytest_configure(Config())
    assert calls == [4]


def test_conftest_stops_the_run_with_125(monkeypatch):
    def refuse(workers):
        raise machine_slot.HostEntryError("no way in")

    monkeypatch.setattr(conftest, "enter_machine_slot", refuse)
    with pytest.raises(pytest.exit.Exception) as stopped:
        conftest.pytest_configure(Config())
    assert (stopped.value.returncode, stopped.value.msg) == (125, "temper pytest: no way in")


@pytest.mark.parametrize("where", ["inactive", "inside", "outside"])
def test_script_placement_prints_the_answer(entry, capsys, where):
    entry.where = where
    assert machine_slot.main(["placement"]) == 0
    assert capsys.readouterr() == (f"{where}\n", "")


def test_script_placement_failure_is_125(entry, capsys):
    entry.environ[RESTART] = "1:1"
    assert machine_slot.main(["placement"]) == 125
    out = capsys.readouterr()
    assert out.out == "" and out.err.startswith("shared test CPU: restarted by 1:1")


def test_script_enter_outside_becomes_the_launcher(entry):
    with pytest.raises(Restart):
        machine_slot.main(["enter", "--", "/bin/bash", "hook", "a b"])
    assert entry.attempts == [(LAUNCHER, [LAUNCHER, "exec", "--quiet", "--", "/bin/bash", "hook", "a b"], None, OWN)]


@pytest.mark.parametrize(("where", "record"), [("inactive", None), ("inside", OWN)])
def test_script_enter_elsewhere_runs_the_command_where_it_is(entry, where, record):
    # Told inside, it leaves its own record, so the command can't come back outside and loop.
    entry.where = where
    with pytest.raises(Restart):
        machine_slot.main(["enter", "--", "/bin/bash", "hook", "a b"])
    assert entry.attempts == [("/bin/bash", ["/bin/bash", "hook", "a b"], None, record)]


def test_script_enter_inside_that_cant_record_itself_runs_nothing(entry, capsys, monkeypatch):
    def unreadable(pid):
        raise OSError("no /proc")

    entry.where = "inside"
    monkeypatch.setattr(machine_slot, "_process", unreadable)
    assert machine_slot.main(["enter", "--", "/bin/bash"]) == 125
    assert entry.attempts == [] and entry.environ == {}
    assert capsys.readouterr().err == "shared test CPU: can't read this run's own start time for the loop guard (no /proc)\n"


@pytest.mark.parametrize(("fail", "code"), [(FileNotFoundError("gone"), 127), (PermissionError("denied"), 126)],
                         ids=["not-found", "not-executable"])
def test_script_enter_elsewhere_that_cant_start_gives_the_shells_code(entry, capsys, fail, code):
    entry.where, entry.fail = "inactive", fail
    assert machine_slot.main(["enter", "--", "/bin/missing"]) == code
    assert capsys.readouterr().err == f"shared test CPU: couldn't run /bin/missing ({fail})\n"
    assert entry.environ == {}


def test_script_enter_that_cant_be_placed_runs_nothing(entry, capsys):
    entry.where = machine_slot.HostEntryError("policy there, launcher not")
    assert machine_slot.main(["enter", "--", "/bin/bash"]) == 125
    assert entry.attempts == []
    assert capsys.readouterr().err == "shared test CPU: policy there, launcher not\n"


def test_script_enter_failure_is_125(entry, capsys):
    entry.fail = FileNotFoundError("no launcher")
    assert machine_slot.main(["enter", "--", "/bin/bash", "hook"]) == 125
    assert entry.environ == {}
    assert "couldn't restart under" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["placement", "x"], ["enter", "--"], ["enter", "bash"], ["other"]])
def test_script_usage(entry, capsys, argv):
    assert machine_slot.main(argv) == 2
    assert entry.attempts == []


# ─── A fake host: its slice is real process ancestry ────────────────────────

FAKE_HOST = r'''
"""The fake host's state and records. Placed = this process or an ancestor is one it placed."""
import json
import os

DIR = os.path.dirname(os.path.abspath(__file__))


def _process(pid):
    with open(f"/proc/{pid}/stat", "rb") as f:
        data = f.read()
    fields = data[data.rindex(b")") + 2:].split()
    return f"{pid}:{int(fields[19])}", int(fields[1])


def inside():
    try:
        with open(os.path.join(DIR, "scopes")) as f:
            scopes = set(f.read().split())
    except FileNotFoundError:
        return False
    pid = os.getpid()
    while pid > 0:
        record, pid = _process(pid)
        if record in scopes:
            return True
    return False


def place_self():
    with open(os.path.join(DIR, "scopes"), "a") as f:
        f.write(_process(os.getpid())[0] + "\n")


def host():
    with open(os.path.join(DIR, "host.json")) as f:
        return json.load(f)


def record(kind, **fields):
    with open(os.path.join(DIR, "calls.jsonl"), "a") as f:
        f.write(json.dumps({"kind": kind, "inside": inside(), **fields}) + "\n")
'''

FAKE_LAUNCHER = r'''
args = sys.argv[1:]
host = fakehost.host()
mode = host["mode"]
if args == ["membership", "--json"]:
    fakehost.record("membership")
    if host.get("membership") == "error":
        print(json.dumps({"error": "cgroup-unreadable"}))
        sys.exit(1)
    placed = mode == "enabled" and fakehost.inside()
    if host.get("membership") == "alternate":
        # A launcher that contradicts itself: outside, inside, outside, ... whatever the slice says.
        with open(os.path.join(fakehost.DIR, "answers"), "a+") as f:
            f.seek(0)
            placed = len(f.read()) % 2 == 1
            f.write("x")
    print(json.dumps({"cgroup": "/fake", "mode": mode, "slice": "testcpu.slice", "inside": placed, "parentOk": True}))
    sys.exit(0 if placed else 1)
if args[:1] == ["exec"] and "--" in args:
    fakehost.record("exec", argv=args)
    command = args[args.index("--") + 1:]
    if mode == "enabled" and not fakehost.inside():
        if host.get("exec") == "refuse":
            print("test-cpu: placement refused (fake)", file=sys.stderr)
            sys.exit(125)
        if host.get("exec") != "noplace":
            fakehost.place_self()
    os.execvp(command[0], command)
sys.exit(2)
'''

# Like wt slot: its command runs through the launcher, which places it where the host wants it.
FAKE_WT = r'''
args = sys.argv[1:]
fakehost.record("wt", argv=args, marker=os.environ.get("TEMPER_PYTEST_MACHINE_SLOT"))
assert args[:2] == ["slot", "--"], args
if fakehost.host()["mode"] == "enabled" and not fakehost.inside():
    fakehost.place_self()
os.execvp(args[2], args[2:])
'''

FAKE_GIT = r'''
args = sys.argv[1:]
fakehost.record("git", argv=args)
if args == ["rev-parse", "--show-toplevel"]:
    print(os.getcwd())
elif args == ["rev-parse", "--local-env-vars"]:
    print("GIT_DIR\nGIT_INDEX_FILE")
elif args[:2] == ["diff", "--cached"]:
    unrelated = [f"notes/n{i:05d}.md" for i in range(fakehost.host().get("unrelated", 0))]
    staged = ["temper_ai/tools/registry.py", "temper_ai/database/models.py", *unrelated, "frontend/src/app.ts"]
    print("\n".join(p for p in staged if args[-2:] != ["--", "frontend/*"] or p.startswith("frontend/")))
'''

FAKE_TOOL = r'''
fakehost.record(os.path.basename(sys.argv[0]), argv=sys.argv[1:])
'''


def program(path, body, fake):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\nimport json, os, sys\nsys.path.insert(0, {str(fake)!r})\nimport fakehost\n{body}")
    path.chmod(0o755)


def entry_copy(target, host):
    """tests/machine_slot.py with the launcher and policy moved to the scratch host."""
    text = (ROOT / "tests/machine_slot.py").read_text()
    for line, moved in ((f'TEST_CPU = "{LAUNCHER}"', f'TEST_CPU = "{host.cli}"'), (f'POLICY = "{POLICY}"', f'POLICY = "{host.policy}"')):
        text = text.replace(line, moved)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


@pytest.fixture
def host(tmp_path):
    """A scratch repo, tools and host. mode: absent (nothing installed), inactive, enabled, invalid."""
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "fakehost.py").write_text(FAKE_HOST)
    bin_ = tmp_path / "bin"
    repo = tmp_path / "repo"
    h = SimpleNamespace(dir=fake, bin=bin_, repo=repo, cli=tmp_path / "libexec/test-cpu/bin/test-cpu",
                        policy=tmp_path / "etc/agent-tools/test-cpu.json")
    program(bin_ / "wt", FAKE_WT, fake)
    for name in ("uv", "npx", "docker"):
        program(bin_ / name, FAKE_TOOL, fake)
    program(bin_ / "git", FAKE_GIT, fake)
    program(repo / "scripts/generate_docs.py", FAKE_TOOL, fake)
    program(repo / "scripts/select_tests.py", FAKE_TOOL + 'print("python tests/test_probe.py\\nfrontend")\n', fake)
    program(repo / "scripts/test-postgres.sh", FAKE_TOOL + 'print("postgresql://fake:fake@127.0.0.1:5999/fake")\n', fake)
    (repo / "frontend/node_modules").mkdir(parents=True)
    (repo / "scripts/git-hooks").mkdir(parents=True)
    (repo / "scripts/git-hooks/pre-commit").write_text((ROOT / "scripts/git-hooks/pre-commit").read_text())
    entry_copy(repo / "tests/machine_slot.py", h)
    for relative in ("tests/__init__.py", "tests/conftest.py", "tests/pgtier.py"):
        (repo / relative).write_text((ROOT / relative).read_text())
    (repo / "pytest.ini").write_text("[pytest]\n")
    (repo / "tests/test_probe.py").write_text(
        "import os\nimport fakehost\n\ndef test_probe():\n"
        "    fakehost.record('probe', worker=os.environ.get('PYTEST_XDIST_WORKER'),"
        " marker=os.environ.get('TEMPER_PYTEST_MACHINE_SLOT'))\n"
    )

    def install(mode, **behaviour):
        (fake / "host.json").write_text(json.dumps({"mode": mode, **behaviour}))
        if mode != "absent":
            program(h.cli, FAKE_LAUNCHER, fake)
            h.policy.parent.mkdir(parents=True, exist_ok=True)
            h.policy.write_text("{}\n")

    def calls():
        log = fake / "calls.jsonl"
        lines = log.read_text().splitlines() if log.exists() else []
        return [json.loads(line) for line in lines]

    h.install, h.calls = install, calls
    return h


def environment(h, *, path=None):
    env = {k: v for k, v in os.environ.items() if k not in OUTER and not k.startswith("GIT_")}
    env.update(PATH=path or f"{h.bin}:{os.environ['PATH']}", PYTHONPATH=f"{h.repo}:{ROOT}:{h.dir}")
    return env


def clean(env, argv):
    """argv under env -i: only PATH, PYTHONPATH and HOME, so no marker or record comes along."""
    return ["env", "-i", *(f"{k}={env[k]}" for k in ("PATH", "PYTHONPATH", "HOME") if k in env), *argv]


class Ran:
    """A finished child as these tests' asserts see it: its exit code, and fixed questions about what
    it said. Its output and argv stay in here (CWE-532): a failure's text shows an assert's operands
    and a frame's arguments by repr, and a TimeoutExpired's or a failed start's traceback shows the
    child's argv and environment. A child that hangs or can't start has no exit code."""

    def __init__(self, argv, *, timeout, **options):
        self.code, self._out, self._err = None, "", ""
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **options)
        except subprocess.TimeoutExpired:
            self._why = f"no exit within {timeout} s"
        except OSError:
            self._why = "couldn't start"
        else:
            self.code, self._out, self._err = done.returncode, done.stdout, done.stderr

    def __repr__(self):
        return f"<ran: exit {self.code}>" if self.code is not None else f"<ran: {self._why}>"

    def said(self, text):
        """Whether its stdout holds ``text``."""
        return text in self._out

    def warned(self, text):
        """How many times its stderr holds ``text``."""
        return self._err.count(text)


# ─── The whole pre-commit hook ───────────────────────────────────────────────


def phases(repo):
    """The original hook's phase vector for these staged paths: docs, PG, Python and the dashboard."""
    return [
        ("git", ["rev-parse", "--show-toplevel"]),
        ("git", ["diff", "--cached", "--name-only"]),
        ("generate_docs.py", []),
        ("git", ["add", f"{repo}/docs/reference/"]),
        ("uv", ["sync", "--frozen", "--extra", "dev", "--quiet"]),
        ("uv", ["run", "--quiet", "python", "scripts/show_versions.py", "--check"]),
        ("uv", ["run", "--quiet", "ruff", "check", "."]),
        ("uv", ["run", "--quiet", "mypy", "temper_ai/", "--ignore-missing-imports"]),
        ("select_tests.py", ["--explain"]),
        ("git", ["diff", "--cached", "--name-only", "--diff-filter=ACM"]),
        ("test-postgres.sh", ["url"]),
        ("git", ["rev-parse", "--local-env-vars"]),
        ("uv", ["run", "--quiet", "pytest", "tests/test_probe.py", "-m", "not heavy", "--timeout=120", "-q", "--no-header", "-n", "auto"]),
        ("git", ["diff", "--cached", "--name-only", "--diff-filter=ACM", "--", "frontend/*"]),
        ("npx", ["--no-install", "tsc", "-b"]),
        ("npx", ["--no-install", "vitest", "run", "--silent"]),
    ]


def run_hook(h, *, placed=False, clean_env=False, relative=False, extra=None, timeout=120):
    env = environment(h)
    env.update(extra or {})
    hook = "scripts/git-hooks/pre-commit"
    argv = ["bash", hook if relative else str(h.repo / hook)]
    if clean_env:
        argv = clean(env, argv)
    if placed:
        argv = [str(h.cli), "exec", "--", *argv]
    return Ran(argv, cwd=h.repo, env=env, timeout=timeout)


def split(calls):
    """(launcher calls, phases) as (kind, inside) and (kind, argv, inside)."""
    launcher = [(c["kind"], c["inside"]) for c in calls if c["kind"] in ("membership", "exec")]
    rest = [(c["kind"], c.get("argv"), c["inside"]) for c in calls if c["kind"] not in ("membership", "exec")]
    return launcher, rest


@pytest.mark.parametrize("mode", ["absent", "inactive"])
def test_hook_without_an_enabled_policy_runs_the_original_phases_unplaced(host, mode):
    host.install(mode)
    ran = run_hook(host)
    assert ran.code == 0
    launcher, rest = split(host.calls())
    assert launcher == ([] if mode == "absent" else [("membership", False)])
    assert rest == [(*phase, False) for phase in phases(host.repo)]
    assert (ran.said("shared test CPU"), ran.warned("shared test CPU")) == (False, 0)


def test_hook_with_a_long_staged_list_keeps_every_phase(host):
    # grep -q stops at its first match: fed by a pipe under pipefail, the writer's SIGPIPE on a list
    # longer than the pipe holds would read as "no match" and drop the docs and Postgres phases.
    host.install("absent", unrelated=20000)
    ran = run_hook(host)
    assert ran.code == 0
    assert split(host.calls()) == ([], [(*phase, False) for phase in phases(host.repo)])


def test_hook_whose_launcher_contradicts_itself_stops_with_125(host):
    # The hook hears outside, enter hears inside and runs it in place, the hook hears outside again:
    # enter's record stops it there instead of handing it back and forth without end.
    host.install("enabled", membership="alternate")
    ran = run_hook(host, timeout=30)
    assert ran.code == 125
    assert split(host.calls()) == ([("membership", False)] * 3, [])
    assert (ran.said("Commit aborted"), ran.warned("yet still outside")) == (True, 1)


@pytest.mark.parametrize("cdpath", [".:/nonexistent", "/nonexistent:."])
def test_hook_by_its_relative_path_under_an_exported_cdpath_is_unchanged(host, cdpath):
    # git starts it as scripts/git-hooks/pre-commit (core.hooksPath is relative). With a CDPATH entry
    # that matches, a bare cd prints where it went, which must not end up in the hook's own path.
    host.install("absent")
    ran = run_hook(host, relative=True, extra={"CDPATH": cdpath})
    assert ran.code == 0
    assert split(host.calls()) == ([], [(*phase, False) for phase in phases(host.repo)])


def test_hook_outside_restarts_whole_inside_before_any_phase(host):
    host.install("enabled")
    ran = run_hook(host)
    assert ran.code == 0
    calls = host.calls()
    # The hook asks, then `machine_slot.py enter` asks again before it hands over to the launcher.
    assert [(c["kind"], c["inside"]) for c in calls[:4]] == [
        ("membership", False), ("membership", False), ("exec", False), ("membership", True)]
    shell, hook = calls[2]["argv"][3:]
    assert calls[2]["argv"][:3] == ["exec", "--quiet", "--"] and Path(shell).name == "bash"
    assert hook == str(host.repo / "scripts/git-hooks/pre-commit")
    assert split(calls[4:]) == ([], [(*phase, True) for phase in phases(host.repo)])
    assert ran.said("Entering the shared test CPU...")


@pytest.mark.parametrize("clean_env", [False, True], ids=["inherited", "env-i"])
def test_hook_inside_runs_in_place(host, clean_env):
    host.install("enabled")
    ran = run_hook(host, placed=True, clean_env=clean_env)
    assert ran.code == 0
    launcher, rest = split(host.calls())
    assert launcher == [("exec", False), ("membership", True)]
    assert rest == [(*phase, True) for phase in phases(host.repo)]


@pytest.mark.parametrize(("setup", "launcher_calls"), [
    ("policy-without-launcher", []),
    ("invalid", [("membership", False)]),
    ("unreadable", [("membership", False)]),
    ("refused", [("membership", False), ("membership", False), ("exec", False)]),
    ("still-outside", [("membership", False), ("membership", False), ("exec", False), ("membership", False)]),
])
def test_hook_that_cant_be_placed_stops_with_125_before_any_phase(host, setup, launcher_calls):
    if setup == "policy-without-launcher":
        host.install("absent")
        host.policy.parent.mkdir(parents=True)
        host.policy.write_text("{}\n")
    elif setup == "invalid":
        host.install("invalid")
    else:
        host.install("enabled", **{"unreadable": {"membership": "error"}, "refused": {"exec": "refuse"},
                                   "still-outside": {"exec": "noplace"}}[setup])
    ran = run_hook(host, timeout=60)
    assert ran.code == 125
    assert split(host.calls()) == (launcher_calls, [])
    if setup == "refused":
        # The hook has already handed itself over to the launcher, which says why on its own.
        assert (ran.said("Entering the shared test CPU..."), ran.said("Commit aborted")) == (True, False)
        assert (ran.warned("test-cpu: placement refused (fake)"), ran.warned("shared test CPU: ")) == (1, 0)
    else:
        assert ran.said("Commit aborted")
        assert ran.warned("shared test CPU: ") == 1


# ─── Real pytest runs through the copied conftest ────────────────────────────


def run_pytest(h, *args, path=None, extra=None, placed=False, clean_env=False, outer=None, timeout=180):
    env = environment(h, path=path)
    env.update(extra or {})
    argv = outer or [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_probe.py", *args]
    if clean_env:
        argv = clean(env, argv)
    if placed:
        argv = [str(h.cli), "exec", "--", *argv]
    return Ran(argv, cwd=h.repo, env=env, timeout=timeout)


def contract(calls):
    """The calls the entry's contract is about. Other tools are left out: pytest-benchmark, for one,
    runs `git rev-parse --git-dir` as pytest starts, before any conftest hook."""
    return [c for c in calls if c["kind"] in ("membership", "exec", "wt", "probe")]


def kinds(calls):
    return [(c["kind"], c["inside"]) for c in calls]


def test_pytest_without_a_policy_is_unchanged(host):
    host.install("absent")
    ran = run_pytest(host)
    assert (ran.code, ran.said("1 passed")) == (0, True)
    ran = run_pytest(host, "-n", "2")
    assert (ran.code, ran.said("1 passed")) == (0, True)
    calls = contract(host.calls())
    assert kinds(calls) == [("probe", False), ("wt", False), ("probe", False)]
    assert calls[1]["marker"] == "1" and calls[2]["worker"] in ("gw0", "gw1")


def test_serial_pytest_outside_is_placed(host):
    host.install("enabled")
    ran = run_pytest(host)
    assert (ran.code, ran.said("1 passed")) == (0, True)
    calls = contract(host.calls())
    assert kinds(calls) == [("membership", False), ("exec", False), ("membership", True), ("probe", True)]
    assert calls[1]["argv"][:4] == ["exec", "--quiet", "--", sys.executable]
    assert calls[3]["worker"] is None


def test_serial_pytest_restarted_in_place_yet_outside_stops_after_one_restart(host):
    # This launcher execs its command in place without placing it, so the restarted run is the very
    # process that restarted: the loop guard must count it, not only its parents.
    host.install("enabled", exec="noplace")
    ran = run_pytest(host, timeout=60)
    assert ran.code == 125
    assert ran.warned("yet still outside") > 0
    assert kinds(contract(host.calls())) == [("membership", False), ("exec", False), ("membership", False)]


def test_parallel_pytest_outside_goes_through_wt_and_workers_stay_put(host):
    host.install("enabled")
    ran = run_pytest(host, "-n", "2")
    assert (ran.code, ran.said("1 passed")) == (0, True)
    calls = contract(host.calls())
    assert kinds(calls) == [("membership", False), ("wt", False), ("membership", True), ("probe", True)]
    assert calls[3]["worker"] in ("gw0", "gw1") and calls[3]["marker"] == "1"


def test_ci_pytest_on_an_enabled_host_is_placed_not_skipped(host):
    host.install("enabled")
    ran = run_pytest(host, "-n", "2", extra={"CI": "1"})
    assert (ran.code, ran.said("1 passed")) == (0, True)
    calls = contract(host.calls())
    assert kinds(calls) == [("membership", False), ("exec", False), ("membership", True), ("probe", True)]
    assert calls[3]["worker"] in ("gw0", "gw1") and calls[3]["marker"] is None


def test_clean_env_nested_pytest_inside_takes_no_second_placement(host):
    host.install("enabled")
    ran = run_pytest(host, "-n", "2", placed=True, clean_env=True)
    assert (ran.code, ran.said("1 passed")) == (0, True)
    calls = contract(host.calls())
    assert kinds(calls) == [("exec", False), ("membership", True), ("wt", True), ("membership", True), ("probe", True)]


def test_parallel_pytest_without_wt_on_an_enabled_host_fails_visibly(host):
    host.install("enabled")
    path = os.pathsep.join(d for d in os.environ["PATH"].split(os.pathsep) if not os.path.exists(os.path.join(d, "wt")))
    ran = run_pytest(host, "-n", "2", path=path)
    assert ran.code == 125
    assert ran.warned("temper pytest: wt is not on PATH") > 0
    assert kinds(contract(host.calls())) == [("membership", False)]


def test_pytest_with_a_launcher_that_cant_run_fails_visibly(host):
    host.install("enabled")
    host.cli.chmod(0o644)
    ran = run_pytest(host)
    assert ran.code == 125
    assert ran.warned("is not an executable file") > 0
    assert contract(host.calls()) == []


# ─── This host's real wt, a scratch pool of one slot ────────────────────────


@pytest.mark.skipif(shutil.which("wt") is None, reason="needs agent-tools' wt on PATH, as on the host; GitHub CI has none")
@pytest.mark.parametrize("mode", ["absent", "enabled"])
def test_nested_run_through_real_wt_never_waits_for_its_own_slot(host, tmp_path, mode):
    # wt owns nesting (an ancestor's slot counts); with one slot, waiting for a second would show.
    host.install(mode)
    pool = tmp_path / "pool"
    config = tmp_path / "wt.yaml"
    config.write_text("land_slots: 1\nslot_wait_minutes: 1\n")
    command = [shutil.which("wt"), "slot", "--", sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "tests/test_probe.py", "-n", "2"]
    ran = run_pytest(host, path=os.environ["PATH"], extra={"WT_LAND_SLOTS_DIR": str(pool), "WT_CONFIG": str(config)},
                     outer=command, placed=mode == "enabled")
    assert (ran.code, ran.said("1 passed")) == (0, True)
    assert ran.warned("wt slot: machine slot 1 of 1") == 1
    assert ran.warned("wt slot: already inside machine slot 1 ") == 1
    assert (ran.warned("Waiting up to"), ran.warned("no machine slot came free")) == (0, 0)
    calls = contract(host.calls())
    expected = [("probe", False)] if mode == "absent" else [("exec", False), ("membership", True), ("membership", True), ("probe", True)]
    assert kinds(calls) == expected
    assert calls[-1]["marker"] == "1" and calls[-1]["worker"] in ("gw0", "gw1")
    assert sorted(p.name for p in pool.iterdir() if p.name.startswith("slot-")) == []
    assert sorted(pool.glob("waiting/*.json")) == []


# ─── A failure's text holds nothing a child said ─────────────────────────────


def _exited_cleanly(ran):
    assert ran.code == 0


def _said_passed(ran):
    assert (ran.code, ran.said("1 passed")) == (0, True)


def _warned_once(ran):
    assert ran.warned("wt slot: machine slot 1 of 1") == 1


@pytest.mark.parametrize(("check", "child"), [
    (_exited_cleanly, "exits"), (_said_passed, "exits"), (_warned_once, "exits"), (_exited_cleanly, "hangs"),
    (_exited_cleanly, "missing"),
], ids=["exit", "said", "warned", "timed-out", "cant-start"])
def test_failure_text_carries_no_child_output_or_argv(request, monkeypatch, check, child):
    # Fresh tokens, so no source line shown in the report can hold them.
    canary = {stream: f"{stream}-canary-{uuid.uuid4().hex}" for stream in ("stdout", "stderr", "argv", "env")}
    code = (f"import sys, time; print({canary['stdout']!r}, flush=True); "
            f"print({canary['stderr']!r}, file=sys.stderr, flush=True); "
            f"time.sleep({30 if child == 'hangs' else 0}); sys.exit(3)")
    program = f"/nonexistent/{canary['argv']}" if child == "missing" else sys.executable
    ran = Ran([program, "-c", code, canary["argv"]], timeout=3, env={**os.environ, "CANARY": canary["env"]})
    # Below verbosity 2 pytest shortens an assert's operands (and below 3 a frame's arguments): check
    # the longest text it can show. Only around the check, so this test's own report is unchanged.
    with monkeypatch.context() as verbose:
        verbose.setattr(request.config.option, "verbose", 3)
        with pytest.raises(AssertionError) as failed:
            check(ran)
        # The text pytest reports: the message, each frame with its arguments, chained exceptions.
        text = str(failed.value) + str(failed.getrepr(funcargs=True, style="long", chain=True,
                                                      truncate_args=False, truncate_locals=False))
    assert sorted(stream for stream, token in canary.items() if token in text) == []
