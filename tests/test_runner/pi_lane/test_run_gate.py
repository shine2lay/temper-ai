"""The run process's gate (runner/pi_lane.py check_run), before a run is marked running.

Outside the Pi lane an unmarked run passes untouched and a Pi run is refused (SW-42). In the
Pi lane only a Pi run passes, after every temper module is imported (H2), the Pi-only rule
again on the workflow as it loads now (SW-41, at claim), the preflight (ADR-M4-05), and the
commit it runs on recorded on its row (SW-16). A refused attempt fails red, says why on the
run page, and runs nothing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.runner import pi_lane, pi_preflight
from temper_ai.runner.lanes import LANE_KEY, LANE_RECORD_KEY, OUTSIDE_PI_LANE, PI_LANE
from tests.test_pi_agent import support as sup
from tests.test_runner.pi_lane import support as ls

SHA = "3" * 40
OTHER_SHA = "4" * 40


class Loader:
    """The graph loader, as the run process has it: the lane tests' workflows."""

    def __init__(self, safety=None) -> None:
        self.safety = safety
        self.loaded: list[str] = []

    def load_workflow(self, name, inputs=None, **kw):
        self.loaded.append(name)
        if name not in ls.WORKFLOWS and name not in sup.WORKFLOWS:
            raise FileNotFoundError(name)
        build = ls.WORKFLOWS.get(name) or sup.WORKFLOWS[name]
        return build(), SimpleNamespace(safety=self.safety)


@pytest.fixture
def gate(monkeypatch):
    """check_run with its slow or outside parts recorded: the eager import and the preflight,
    which hands the run record what it read (``read``: the pins and the host's Pi version)."""
    calls: list[str] = []
    failed: list = []
    read: dict = {}
    monkeypatch.setattr(pi_lane, "eager_import", lambda: calls.append("eager_import"))

    def preflight(*, record=None):
        calls.append("preflight")
        if record is not None:
            record.update(read)
        return list(failed)

    monkeypatch.setattr(pi_preflight, "preflight", preflight)
    monkeypatch.setattr(pi_lane, "read_commit", lambda root=None: (SHA, ""))
    loader = Loader()

    def check(eid: str, *, start: str | None = None):
        found = ls.row(eid)
        run_row = {"workflow_name": found.workflow_name, "inputs": found.inputs,
                   "workspace_path": found.workspace_path,
                   "spawner_metadata": found.spawner_metadata}
        return pi_lane.check_run(eid, run_row, start=start, graph_loader=loader)

    return SimpleNamespace(check=check, calls=calls, failed=failed, read=read, loader=loader)


def commits(eid: str) -> list[dict]:
    return ((ls.row(eid).spawner_metadata or {}).get(LANE_RECORD_KEY) or {}).get("commits", [])


# --- Outside the Pi lane ---------------------------------------------------------------------


def test_outside_the_pi_lane_an_ordinary_run_passes_untouched(gate):
    ls.make_row("plain", "lane_plain", pi=False)
    assert gate.check("plain") is None
    assert gate.calls == [] and gate.loader.loaded == []
    assert ls.row("plain").spawner_metadata == {}


def test_outside_the_pi_lane_a_pi_run_refuses(gate):
    ls.make_row("pi")
    assert gate.check("pi") == pi_lane.Refusal(
        "lane", f"{OUTSIDE_PI_LANE}: a worker that isn't the Pi lane claimed this Pi run, so "
                f"it didn't start")
    assert gate.calls == [] and commits("pi") == []


def test_a_lane_setting_temper_doesn_t_know_refuses_every_run(gate, monkeypatch):
    monkeypatch.setenv("TEMPER_LANE", "main")
    ls.make_row("plain", "lane_plain", pi=False)
    refusal = gate.check("plain")
    assert refusal is not None and refusal.kind == "lane"
    assert refusal.message.startswith("TEMPER_LANE='main' is not a lane temper knows")


# --- In the Pi lane --------------------------------------------------------------------------


def test_in_the_pi_lane_an_ordinary_run_refuses(gate, monkeypatch):
    ls.as_the_pi_lane(monkeypatch)
    ls.make_row("plain", "lane_plain", pi=False)
    assert gate.check("plain") == pi_lane.Refusal(
        "lane", "the Pi lane runs only Pi runs: this run isn't marked for the Pi lane, so the "
                "Pi lane didn't start it")
    assert gate.calls == []


@pytest.mark.parametrize("start", [None, "resume", "fork"])
def test_in_the_pi_lane_a_pi_run_passes_in_order_and_records_its_commit(gate, monkeypatch,
                                                                       start):
    ls.as_the_pi_lane(monkeypatch)
    ls.make_row("pi")
    assert gate.check("pi", start=start) is None
    assert gate.calls == ["eager_import", "preflight"]
    assert gate.loader.loaded == ["lane_pi"]
    (entry,) = commits("pi")
    assert (entry["start"], entry["commit"]) == (start or "new", SHA)
    assert ls.lane("pi") == PI_LANE


def test_each_attempt_records_the_pins_the_preflight_checked_and_the_host_pi(gate, monkeypatch):
    """SW-16: beside the commit, every attempt records each pin's digest as the preflight's
    pin check read it (image id, runtime, Pi version, add-ons, identity, ...) and the host's
    Pi version from the host helper."""
    ls.as_the_pi_lane(monkeypatch)
    ls.make_row("pi")
    pins = {"image": sup.IMAGE, "runtime": "a" * 64, "pi_version": sup.PI_VERSION,
            "add_ons": list(sup.ADD_ON_NAMES), "add_on:pi-image-trim": "b" * 64,
            "add_on:pi-tldr": "c" * 64, "identity_extension": "d" * 64,
            "identity_settings": "e" * 64}
    gate.read.update(pins=pins, host_pi="1.0.1")
    assert gate.check("pi") is None
    gate.read["host_pi"] = "1.0.2"
    assert gate.check("pi", start="resume") is None
    first, again = commits("pi")
    assert (first["start"], first["commit"], first["pins"], first["host_pi"]) == (
        "new", SHA, pins, "1.0.1")
    assert (again["start"], again["pins"], again["host_pi"]) == ("resume", pins, "1.0.2")


def test_each_attempt_adds_its_commit_and_the_row_keeps_the_last_twenty(gate, monkeypatch):
    ls.as_the_pi_lane(monkeypatch)
    ls.make_row("pi")
    gate.check("pi")
    monkeypatch.setattr(pi_lane, "read_commit", lambda root=None: (OTHER_SHA, ""))
    for _ in range(pi_lane.COMMITS_KEPT):
        gate.check("pi", start="resume")
    kept = commits("pi")
    assert len(kept) == pi_lane.COMMITS_KEPT
    assert {(e["start"], e["commit"]) for e in kept} == {("resume", OTHER_SHA)}
    assert ls.lane("pi") == PI_LANE


def test_the_pi_only_rule_runs_again_on_the_workflow_as_it_loads_now(gate, monkeypatch):
    """Queued as a Pi-only workflow; since then it gained a script step (SW-41, at claim)."""
    ls.as_the_pi_lane(monkeypatch)
    ls.make_row("pi", "lane_now")
    monkeypatch.setitem(ls.WORKFLOWS, "lane_now", lambda: [
        sup.pi_node(depends_on=()), sup.step("brief")])
    refusal = gate.check("pi")
    assert refusal == pi_lane.Refusal(
        "lane", "The Pi lane runs only Pi steps, team stages of Pi members and gates: step "
                "'brief' is a pi_test_step step; the Pi lane runs only Pi steps")
    assert gate.calls == ["eager_import"] and commits("pi") == []


def test_safety_policies_set_since_are_refused_at_claim_too(gate, monkeypatch):
    ls.as_the_pi_lane(monkeypatch)
    ls.make_row("pi")
    gate.loader.safety = {"policies": ["no_rm"]}
    refusal = gate.check("pi")
    assert refusal is not None and refusal.message.endswith(
        "the workflow sets safety: policies:, which the Pi lane doesn't run")


def test_a_workflow_with_no_pi_step_any_more_is_refused(gate, monkeypatch):
    ls.as_the_pi_lane(monkeypatch)
    ls.make_row("pi", "lane_plain")
    refusal = gate.check("pi")
    assert refusal is not None and refusal.message.endswith(
        "workflow 'lane_plain' has no Pi step any more")


def test_a_workflow_that_won_t_load_is_left_to_the_run_to_report(gate, monkeypatch):
    ls.as_the_pi_lane(monkeypatch)
    ls.make_row("pi", "gone_since")
    assert gate.check("pi") is None
    assert gate.calls == ["eager_import", "preflight"]


def test_failed_checks_refuse_naming_every_reason(gate, monkeypatch):
    ls.as_the_pi_lane(monkeypatch)
    ls.make_row("pi")
    gate.failed[:] = [("disk", "1 MiB free"), ("uid", "runs as 0:0")]
    assert gate.check("pi") == pi_lane.Refusal(
        "pi_preflight", "The Pi lane's checks before the run failed: disk: 1 MiB free; uid: "
                        "runs as 0:0")
    assert commits("pi") == []


# --- The run process -------------------------------------------------------------------------


@pytest.fixture
def run_process(srv, monkeypatch):
    """``temper run-workflow`` in this process, with the server's context (no box, no MCP)."""
    from temper_ai.cli.run_workflow import cmd_run_workflow
    from temper_ai.runner.context import RunnerContext

    st = srv.state
    ctx = RunnerContext(config_store=st.config_store, graph_loader=st.graph_loader,
                        llm_providers=st.llm_providers, memory_service=st.memory_service)
    monkeypatch.setattr("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env",
                        lambda config_dir=None: ctx)
    monkeypatch.setattr("temper_ai.cli.run_workflow._start_mcp_manager", _not_reached)
    monkeypatch.setattr("temper_ai.runner.execute.execute_workflow", _not_reached)

    def run(eid: str) -> int:
        return cmd_run_workflow(argparse.Namespace(execution_id=eid, config_dir=None,
                                                   debug=False))

    return run


def _not_reached(*args, **kwargs):
    raise AssertionError("a refused run went on")


def test_a_pi_run_a_main_worker_claimed_fails_red_and_says_why(srv, run_process):
    eid = srv.client.post("/api/runs", json={"workflow": "lane_pi", "inputs": {},
                                             "workspace_path": str(srv.ws)}).json()["execution_id"]
    assert ls.main_claims(eid) is False  # the claim filter is the first line ...
    ls.set_row(eid, spawner_kind="docker")  # ... the gate is the backstop behind it
    assert run_process(eid) == pi_lane.REFUSED_EXIT
    found = ls.row(eid)
    message = (f"{OUTSIDE_PI_LANE}: a worker that isn't the Pi lane claimed this Pi run, so it "
               f"didn't start")
    assert found.status == "failed"
    assert found.error == {"message": message, "kind": "lane"}
    assert found.spawner_metadata[LANE_KEY] == PI_LANE
    (attempt,) = sup.attempts(eid)
    assert attempt["status"] == "failed"
    assert (attempt["data"]["error"], attempt["data"]["refused"]) == (message, "lane")
    detail = srv.client.get(f"/api/workflows/{eid}").json()
    assert detail["status"] == "failed"


def test_the_commit_is_read_from_the_checkout_without_running_git():
    """The real checkout this test runs from (a worktree or a clone)."""
    root = Path(pi_lane.__file__).resolve().parents[2]
    if not (root / ".git").exists():
        pytest.skip("not a git checkout")
    expected = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], text=True,
                              capture_output=True, check=True).stdout.strip()
    assert pi_lane.temper_commit() == expected


def _git(base: Path, head: str, refs: dict[str, str] | None = None,
         packed: dict[str, str] | None = None) -> Path:
    git = base / ".git"
    git.mkdir(parents=True)
    (git / "HEAD").write_text(head + "\n")
    for ref, sha in (refs or {}).items():
        (git / ref).parent.mkdir(parents=True, exist_ok=True)
        (git / ref).write_text(sha + "\n")
    if packed:
        (git / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted\n"
            + "".join(f"{sha} {ref}\n" for ref, sha in packed.items()))
    return git


@pytest.mark.parametrize("layout", ["loose", "packed", "detached"])
def test_the_commit_from_a_clone_s_git_folder(tmp_path, layout):
    ref = "refs/heads/master"
    if layout == "loose":
        _git(tmp_path, f"ref: {ref}", refs={ref: SHA}, packed={ref: OTHER_SHA})
    elif layout == "packed":
        _git(tmp_path, f"ref: {ref}", packed={"refs/heads/other": OTHER_SHA, ref: SHA})
    else:
        _git(tmp_path, SHA)
    assert pi_lane.temper_commit(tmp_path) == SHA


def test_the_commit_from_a_worktree(tmp_path):
    main = _git(tmp_path / "main", "ref: refs/heads/master",
                refs={"refs/heads/master": OTHER_SHA, "refs/heads/lane": SHA})
    gitdir = main / "worktrees" / "lane"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/lane\n")
    (gitdir / "commondir").write_text("../..\n")
    tree = tmp_path / "lane"
    tree.mkdir()
    (tree / ".git").write_text(f"gitdir: {gitdir}\n")
    assert pi_lane.temper_commit(tree) == SHA


@pytest.mark.parametrize("head", ["ref: refs/heads/nowhere", "not a sha", "ref: "])
def test_a_commit_that_can_t_be_read_is_unknown(tmp_path, head):
    """Outside the Pi lane (in-process, dev, CI) that is all; the Pi lane refuses instead."""
    _git(tmp_path, head)
    assert pi_lane.temper_commit(tmp_path) == pi_lane.UNKNOWN_COMMIT
    assert pi_lane.temper_commit(tmp_path / "no-checkout") == pi_lane.UNKNOWN_COMMIT


@pytest.mark.parametrize(("head", "why"), [
    ("ref: refs/heads/nowhere", "HEAD names refs/heads/nowhere, which "),
    ("not a sha", "HEAD names no commit"),
    ("ref: ", "not a branch"),
])
def test_a_commit_that_can_t_be_read_says_why(tmp_path, head, why):
    _git(tmp_path, head)
    commit, said = pi_lane.read_commit(tmp_path)
    assert commit is None and why in said
    assert pi_lane.read_commit(tmp_path / "no-checkout") == (
        None, f"there is no {tmp_path / 'no-checkout' / '.git'}")


def test_a_git_folder_that_can_t_be_read_says_so(tmp_path):
    git = _git(tmp_path, "ref: refs/heads/master", refs={"refs/heads/master": SHA})
    (git / "HEAD").unlink()
    (git / "HEAD").mkdir()  # read as a file, it fails the way an unreadable one does
    commit, why = pi_lane.read_commit(tmp_path)
    assert commit is None and "can't be read" in why


def test_the_commit_is_read_without_starting_any_process(tmp_path, monkeypatch):
    """Architecture rm-c9c941d4 1(b): nothing runs on temper's .git mount, so no git hook or
    fsmonitor and no ownership check; the files are read the way rev-parse HEAD reads them."""
    _git(tmp_path, "ref: refs/heads/master", packed={"refs/heads/master": SHA})

    def no_process(*args, **kwargs):
        raise AssertionError(f"a process was started: {args}")

    monkeypatch.setattr(subprocess, "Popen", no_process)
    monkeypatch.setattr(os, "posix_spawn", no_process)
    monkeypatch.setattr(os, "fork", no_process)
    assert pi_lane.read_commit(tmp_path) == (SHA, "")


def test_a_commit_unreadable_after_the_preflight_refuses_and_records_nothing(gate,
                                                                              monkeypatch):
    """In the Pi lane every run records its commit (SW-16): never "unknown"."""
    ls.as_the_pi_lane(monkeypatch)
    ls.make_row("pi")
    monkeypatch.setattr(pi_lane, "read_commit",
                        lambda root=None: (None, "there is no /app/.git"))
    assert gate.check("pi") == pi_lane.Refusal(
        "pi_preflight", "The Pi lane's checks before the run failed: commit_unreadable: "
                        "there is no /app/.git")
    assert commits("pi") == []
