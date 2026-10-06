"""The Pi lane's checks before a Pi run (ADR-M4-05, SW-46, H3; runner/pi_preflight.py).

Each failed check is a named reason with plain words, every one at once; a lane that is set up
passes them all. Docker, the host helper and the pi_ tables are stand-ins: no Docker, no
socket, no model.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import tempfile
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.pi_agent import host_helper
from temper_ai.pi_agent.ledger import LedgerError
from temper_ai.runner import pi_lane
from temper_ai.runner import pi_preflight as pf
from tests.test_pi_agent import support as sup

TEMPLATE = "temper-ai-server-1"


class FakeDocker:
    """``docker`` as the preflight asks it: version, image inspect, the template's mounts."""

    def __init__(self, image: str) -> None:
        self.version = SimpleNamespace(returncode=0, stdout="27.3.1\n")
        self.image = SimpleNamespace(returncode=0, stdout=image + "\n")
        self.mounts: list[dict] = [{"Source": "/var/run/docker.sock"},
                                   {"Source": "/home/someone/temper-ai/workspaces"}]
        self.inspect_rc = 0
        self.asked: list[tuple[str, ...]] = []

    def __call__(self, *args: str, timeout: float = 0) -> SimpleNamespace:
        self.asked.append(args)
        if args[0] == "version":
            return self.version
        if args[:2] == ("image", "inspect"):
            return self.image
        if args[0] == "inspect":
            return SimpleNamespace(returncode=self.inspect_rc, stdout=json.dumps(self.mounts))
        raise AssertionError(f"unexpected docker call {args}")


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """A Pi lane that is set up: every check passes."""
    short = Path(tempfile.mkdtemp(prefix="pilane-", dir="/tmp"))  # sockets under 100 bytes
    box_root = tmp_path / "box"
    (box_root / "state").mkdir(parents=True)
    (short / "sock").mkdir()
    project = tmp_path / "projects" / "app"
    project.mkdir(parents=True)
    over = {"roots": [str(tmp_path), str(short)], "socket_root": str(short / "sock"),
            "host_helper_socket": str(short / "helper" / "host.sock"),
            "project_roots": [str(project)]}
    path = sup.make_box_config(box_root, **over)
    monkeypatch.setenv("TEMPER_PI_AGENT", "1")
    monkeypatch.setenv("TEMPER_PI_BOX_CONFIG", str(path))
    monkeypatch.setenv(pf.TEMPLATE_ENV, TEMPLATE)
    monkeypatch.setenv(pf.WORKSPACE_ENV, str(tmp_path / "workspaces"))
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "getgid", lambda: 1000)
    code = tmp_path / "code"  # the checkout pi-worker runs, with temper's .git planted
    (code / ".git").mkdir(parents=True)
    (code / ".git" / "HEAD").write_text("4ce5f9ffa985603a40c5955f84cc86afc5e5a442\n")
    monkeypatch.setattr(pi_lane, "CODE_ROOT", code)
    helper = SimpleNamespace(answer='ok {"bridge": {"state": "ready"}}', asked=[])

    def ask(socket_path, line, timeout):
        helper.asked.append((socket_path, line))
        if isinstance(helper.answer, Exception):
            raise helper.answer
        return helper.answer

    monkeypatch.setattr(host_helper, "ask", ask)
    docker = FakeDocker(sup.IMAGE)
    ledger = SimpleNamespace(error=None, ensured=0)

    def ensure():
        ledger.ensured += 1
        if ledger.error:
            raise ledger.error

    def rewrite(**changes):
        raw = json.loads(path.read_text())
        raw.update(changes)
        path.write_text(json.dumps(raw))

    yield SimpleNamespace(tmp=tmp_path, short=short, box=box_root, project=project, code=code,
                          docker=docker, helper=helper, ledger=ledger, rewrite=rewrite,
                          run=lambda: pf.preflight(docker=docker, ensure_ledger=ensure))
    shutil.rmtree(short, ignore_errors=True)


def reasons(failed):
    return [reason for reason, _ in failed]


def test_a_lane_that_is_set_up_passes_every_check(lane):
    assert lane.run() == []
    assert lane.helper.asked == [(str(lane.short / "helper" / "host.sock"), "status")]
    assert lane.ledger.ensured == 1
    assert [a[0] for a in lane.docker.asked] == ["version", "image", "inspect"]
    assert lane.docker.asked[-1][-1] == TEMPLATE


def test_switched_off_it_says_so_and_checks_nothing_else(lane, monkeypatch):
    monkeypatch.setenv("TEMPER_PI_AGENT", "0")
    assert reasons(lane.run()) == ["pi_switched_off"]
    assert lane.docker.asked == [] and lane.ledger.ensured == 0


@pytest.mark.parametrize("config", ["", "/nonexistent/box.json"])
def test_a_box_config_that_can_t_be_read_says_so(lane, monkeypatch, config):
    monkeypatch.setenv("TEMPER_PI_BOX_CONFIG", config)
    assert reasons(lane.run()) == ["box_config"]


def test_a_commit_that_can_t_be_read_is_a_named_reason(lane):
    """Every Pi run records its commit (SW-16): a dropped .git mount, say, refuses the run
    rather than recording "unknown" (Architecture rm-c9c941d4 1(a))."""
    shutil.rmtree(lane.code / ".git")
    (failed,) = lane.run()
    assert failed == ("commit_unreadable",
                      f"the temper commit this worker runs can't be read (there is no "
                      f"{lane.code / '.git'}); every Pi run records it (SW-16)")


def test_the_commit_is_named_beside_a_box_config_that_can_t_be_read(lane, monkeypatch):
    shutil.rmtree(lane.code / ".git")
    monkeypatch.setenv("TEMPER_PI_BOX_CONFIG", "")
    assert reasons(lane.run()) == ["commit_unreadable", "box_config"]


def test_the_pins_and_identity_checks_sit_behind_the_one_function_53_replaces(lane,
                                                                              monkeypatch):
    """Architecture rm-c9c941d4 item 6: until #53, the box config's own checks stand in."""
    cfg, problems = pf.pins_and_identity()
    assert cfg is not None and problems == []
    monkeypatch.setattr(pf, "pins_and_identity",
                        lambda: (cfg, [("pins", "add-on x differs from its pin")]))
    assert lane.run() == [("pins", "add-on x differs from its pin")]
    assert "BoxConfig" not in inspect.getsource(pf.preflight)


def test_a_box_config_that_fails_its_own_checks_says_which(lane):
    lane.rewrite(pi_version="0.0.1")
    (failed,) = lane.run()
    assert failed == ("box_config", "Pi worker box config: installed Pi version differs from "
                                    "pi_version")


def test_no_roots_is_a_reason(lane):
    lane.rewrite(roots=[], project_roots=[])
    assert lane.run() == [("roots", "the box config names no roots; the Pi lane mounts each "
                                    "of its folders at its own host path and binds nothing "
                                    "from elsewhere")]


def test_a_state_root_this_worker_can_t_write_is_a_reason(lane):
    state = lane.box / "state"
    state.chmod(0o500)
    try:
        assert lane.run() == [("roots", "the state_root is not a writable folder here")]
    finally:
        state.chmod(0o700)


def test_a_worker_that_isn_t_1000_is_a_reason(lane, monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 1001)
    assert lane.run() == [("uid", "the Pi lane's worker runs as 1001:1000; its members run as "
                                  "its user, which must be 1000:1000")]


def test_a_socket_root_too_long_for_a_turn_s_sockets_is_a_reason(lane):
    long_root = lane.tmp / ("s" * 90)
    long_root.mkdir()
    lane.rewrite(socket_root=str(long_root))
    (failed,) = lane.run()
    assert failed[0] == "socket_path"
    assert failed[1].endswith("it must stay under 100 (use a shorter socket_root)")


def test_docker_not_answering_is_one_reason_and_skips_its_other_checks(lane):
    lane.docker.version = SimpleNamespace(returncode=1, stdout="")
    assert lane.run() == [("docker", "Docker doesn't answer (the socket or its group missing?)")]
    assert [a[0] for a in lane.docker.asked] == ["version"]


def test_an_image_that_isn_t_on_this_host_is_a_reason(lane):
    lane.docker.image = SimpleNamespace(returncode=1, stdout="")
    assert lane.run() == [("image", f"the pinned worker image {sup.IMAGE[:19]} is not on this "
                                    f"Docker host")]


@pytest.mark.parametrize("folder,named", [
    ("state", "state_root"),
    ("sock", "socket_root"),
    ("project", "project root 1"),
    ("pins", "runtime_dir"),
    ("above", "identities_dir, identity_config, identity_extension, project root 1, "
               "runtime_dir, state_root"),
])
def test_a_template_that_mounts_a_pi_or_project_folder_is_a_reason(lane, folder, named):
    """The main worker's run boxes copy the template's mounts: none may reach a Pi folder,
    whether the mount is the folder, inside it or above it."""
    source = {"state": lane.box / "state" / "runs", "sock": lane.short / "sock",
              "project": lane.project, "pins": lane.box / "runtime" / "node",
              "above": lane.tmp}[folder]
    lane.docker.mounts.append({"Source": str(source), "Destination": "/x"})
    assert lane.run() == [("template_mounts", f"the run-box template {TEMPLATE} mounts a Pi or "
                                              f"project folder ({named}), which every run box "
                                              f"would get")]


def test_a_template_that_can_t_be_read_is_a_reason(lane, monkeypatch):
    lane.docker.inspect_rc = 1
    assert reasons(lane.run()) == ["template_mounts"]
    monkeypatch.delenv(pf.TEMPLATE_ENV)
    assert lane.run() == [("template_mounts", f"{pf.TEMPLATE_ENV} is not set, so the run-box "
                                              "template's mounts can't be checked")]


@pytest.mark.parametrize("answer,text", [
    (host_helper.HelperUnreachable("the host helper isn't running (/x)"),
     "the host helper isn't running (/x)"),
    ("denied uid", "the host helper didn't answer ok to status"),
    ("ok not-json", "the host helper's status could not be read"),
    ('ok {"bridge": {"state": "sdk_changed"}}',
     "the host helper's login bridge is sdk_changed, not ready"),
])
def test_a_host_helper_that_isn_t_ready_is_a_reason(lane, answer, text):
    lane.helper.answer = answer
    assert lane.run() == [("host_helper", text)]


def test_a_bridge_not_set_up_is_fine(lane):
    lane.helper.answer = 'ok {"bridge": {"state": "not_configured"}}'
    assert lane.run() == []


def test_live_mode_without_a_host_helper_is_a_reason(lane):
    lane.rewrite(host_helper_socket="")
    assert lane.run() == [("host_helper", "live mode needs the host helper (host_helper_socket)")]
    assert lane.helper.asked == []


def test_a_pi_folder_inside_the_run_workspaces_is_a_reason(lane, monkeypatch):
    """H3: with TEMPER_DOCKER_WORKSPACES=all every run box may mount WORKSPACE_DIR."""
    monkeypatch.setenv(pf.WORKSPACE_ENV, str(lane.box))
    assert lane.run() == [("workspace_overlap", "identities_dir, identity_config, "
                                                "identity_extension, runtime_dir, state_root "
                                                "inside WORKSPACE_DIR, which every run box may "
                                                "mount read-write")]
    monkeypatch.setenv(pf.WORKSPACE_ENV, str(lane.project.parent))
    assert lane.run() == [("workspace_overlap", "project root 1 inside WORKSPACE_DIR, which "
                                                "every run box may mount read-write")]
    monkeypatch.delenv(pf.WORKSPACE_ENV)
    assert lane.run() == [("workspace_overlap", "WORKSPACE_DIR is not set, so the Pi folders "
                                                "can't be checked against the run workspaces")]


@pytest.mark.parametrize("error,text", [
    (LedgerError("pi_ schema v3 is newer than this build (v2)"),
     "pi_ schema v3 is newer than this build (v2)"),
    (RuntimeError("connection refused"), "the pi_ tables could not be checked (RuntimeError)"),
])
def test_pi_tables_that_can_t_be_brought_to_this_build_are_a_reason(lane, error, text):
    lane.ledger.error = error
    assert lane.run() == [("pi_schema", text)]


def test_too_little_disk_under_the_state_root_is_a_reason(lane, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(pf.shutil, "disk_usage", lambda p: usage(10 * 2**30, 9 * 2**30, 2**30))
    assert lane.run() == [("disk", "1024 MiB free under the state root; the Pi lane needs 2 GiB")]


def test_every_failed_check_is_named_at_once_in_order(lane, monkeypatch):
    monkeypatch.setattr(os, "getgid", lambda: 0)
    lane.docker.image = SimpleNamespace(returncode=1, stdout="")
    lane.helper.answer = "denied uid"
    monkeypatch.setenv(pf.WORKSPACE_ENV, str(lane.tmp))
    lane.ledger.error = LedgerError("locked")
    assert reasons(lane.run()) == ["uid", "image", "host_helper", "workspace_overlap",
                                   "pi_schema"]


def test_the_overlap_rule_reads_paths_both_ways():
    assert pf.overlap("/a/b", "/a/b/") and pf.overlap("/a/b/c", "/a/b")
    assert pf.overlap("/a", "/a/b/c")
    assert not pf.overlap("/a/bc", "/a/b") and not pf.overlap("/x", "/a")
