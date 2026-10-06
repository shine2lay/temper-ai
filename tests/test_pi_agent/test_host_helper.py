"""Temper's side of the host helper (``scripts/pi_host/temper_pi_host.py``, M4 ADR-M4-02/12/15):
a worker's login hand-off asks the helper for the run's pinned slot when the box config names
the helper's socket, the box config then needs no host node or Pi, and the E10 branch client
works against the real helper. The helper runs for real as its own process, over a stub Pi CLI
and a stub Pi SDK: no real login, no model call."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

from temper_ai.llm.pi_stream import Redactor
from temper_ai.pi_agent import host_helper
from temper_ai.pi_agent.box import BoxConfig, BoxError, WorkerBox
from temper_ai.pi_agent.team_branch import make_branch
from temper_ai.pi_agent.turn import run_turn
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox
from tests.test_pi_agent.test_turn import Ledger, Recorder, _req
from tests.test_pi_host.support import (
    BASE,
    NODE,
    SLOT,
    Host,
    Served,
    branch_of,
    git,
    make_leader,
    make_source,
)

pytestmark = pytest.mark.timeout(120)

needs_node = pytest.mark.skipif(NODE is None, reason="the helper's auth bridge needs node")
TRIAL = "0123456789ab"
ROUTES = {"anthropic": {"provider": "anthropic", "host": "api.anthropic.com"}}


@pytest.fixture
def host():
    h = Host()
    yield h
    h.cleanup()


@pytest.fixture
def served(host):
    """The real helper, serving the stub SDK's slots through its bridge."""
    s = Served(host, host.config())
    assert s.wait_ready(), s.log()
    yield s
    s.stop()


def box_config(root: Path, *, drop: tuple[str, ...] = (), **over) -> BoxConfig:
    path = sup.make_box_config(root, routes=ROUTES, **over)
    raw = json.loads(path.read_text())
    for key in drop:
        raw.pop(key)
    path.write_text(json.dumps(raw))
    return BoxConfig.load(str(path))


def talk(path: Path, data: bytes) -> bytes:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(30)
    s.connect(str(path))
    s.sendall(data)
    got = b""
    while chunk := s.recv(4096):
        got += chunk
    s.close()
    return got


def handoff(cfg: BoxConfig, tmp_path: Path, slot: str, allowance: int = 1) -> tuple[bytes, dict, Redactor]:
    """One hand-off through a real WorkerBox's hand-off socket (no container); the token the
    worker got, the turn's receipt and the redactor."""
    redactor = Redactor()
    box = WorkerBox(cfg, sup.spec(tmp_path / "p", provider="anthropic", slot=slot), redactor)
    box._open_sockets()
    try:
        box.allow(allowance)
        got = talk(box.sock_dir / "handoff.sock", b"anthropic\n")
    finally:
        receipt = box.close()
    return got, receipt, redactor


# --- the box config ----------------------------------------------------------------------


def test_with_the_helper_the_box_config_needs_no_host_node_or_pi(tmp_path):
    cfg = box_config(tmp_path, drop=("host_node", "host_pi"), host_helper_socket="/run/h/h.sock")
    assert (cfg.host_node, cfg.host_pi, cfg.host_helper_socket) == ("", "", "/run/h/h.sock")


def test_without_the_helper_a_live_box_still_needs_them(tmp_path):
    with pytest.raises(BoxError) as err:
        box_config(tmp_path, drop=("host_node", "host_pi"))
    assert "host_node and host_pi are needed without host_helper_socket" in str(err.value)
    assert box_config(tmp_path / "b").host_node == "/nonexistent/node"


@pytest.mark.parametrize("path", ["relative/h.sock", "/" + "s" * 99])
def test_the_helper_socket_must_be_absolute_and_short(tmp_path, path):
    with pytest.raises(BoxError) as err:
        box_config(tmp_path, host_helper_socket=path)
    assert "host_helper_socket must be an absolute path under 100 bytes" in str(err.value)


# --- the hand-off over the helper ----------------------------------------------------------


@needs_node
def test_the_handoff_serves_the_pinned_slot_from_the_helper(tmp_path, host, served):
    cfg = box_config(tmp_path, drop=("host_node", "host_pi"), host_helper_socket=served.socket)
    got, receipt, redactor = handoff(cfg, tmp_path, SLOT)
    assert got == host.canary.encode()
    assert host.canary in redactor.secrets, "the redactor knew the token before the worker"
    assert receipt["handoff_slot"] == SLOT and receipt["handoffs"] == 1
    assert receipt["handoffs_denied"] == 0 and "handoff_refused" not in receipt
    served.stop()
    log = served.log()
    assert f"verb=token slot={SLOT} result=ok" in log
    assert host.canary not in log and host.canary not in json.dumps(receipt)


@needs_node
@pytest.mark.parametrize("slot, words", [
    (BASE, f"slot {BASE} is account 1 and is never served"),
    (f"{BASE}-9", f"slot {BASE}-9"),
])
def test_a_refusal_hands_over_nothing_and_names_the_slot(tmp_path, host, served, slot, words):
    cfg = box_config(tmp_path, host_helper_socket=served.socket)
    got, receipt, redactor = handoff(cfg, tmp_path, slot)
    assert got == b"" and redactor.secrets == []
    assert receipt["handoff_slot"] == slot and receipt["handoffs_denied"] == 1
    assert words in receipt["handoff_refused"]
    assert host.canary not in json.dumps(receipt)


@needs_node
def test_no_pinned_slot_means_the_helper_is_not_asked(tmp_path, served):
    cfg = box_config(tmp_path, host_helper_socket=served.socket)
    got, receipt, _ = handoff(cfg, tmp_path, "")
    assert got == b"" and receipt["handoff_slot"] == "anthropic"
    assert receipt["handoff_refused"].startswith("no account slot is pinned for this run")
    served.stop()
    assert "verb=token" not in served.log()


def test_a_helper_that_is_down_is_a_plain_refusal(tmp_path, host):
    sock = str(host.sock_dir / "h.sock")
    cfg = box_config(tmp_path, host_helper_socket=sock)
    got, receipt, _ = handoff(cfg, tmp_path, SLOT)
    assert got == b""
    assert receipt["handoff_refused"] == f"slot {SLOT}: the host helper isn't running ({sock})"


def test_a_rehearsal_never_asks_the_helper(tmp_path, host):
    cfg = box_config(tmp_path, host_helper_socket=str(host.sock_dir / "h.sock"), mode="rehearsal",
                     rehearsal={"upstream_port": 9, "tokens": {"anthropic": "synthetic-token"}})
    got, receipt, _ = handoff(cfg, tmp_path, SLOT)
    assert got == b"synthetic-token" and "handoff_refused" not in receipt


# --- the client against odd helpers ----------------------------------------------------------


class OneAnswer:
    """A stand-in helper that answers every request with ``answer`` (or nothing, slowly)."""

    def __init__(self, path: Path, answer: bytes | None):
        self.path = str(path)
        self.lines: list[bytes] = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen()
        self.answer = answer
        self.done = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.done.is_set():
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                self.lines.append(conn.recv(4096))
                if self.answer is None:
                    self.done.wait(5)
                else:
                    conn.sendall(self.answer)

    def close(self):
        self.done.set()
        self.server.close()


@pytest.mark.parametrize("answer, expected", [
    (b"ok tok-123\n", ("tok-123", "")),
    (b"denied slot acme-2: no stored login\n", ("", "slot acme-2: no stored login")),
    (b"denied uid 7 is not served\n", ("", "slot acme-2: uid 7 is not served")),
    (b"denied\n", ("", "slot acme-2: no reason given")),
    (b"ok two words\n", ("", "slot acme-2: the host helper gave an answer this Temper doesn't know")),
    (b"secret-looking-text\n", ("", "slot acme-2: the host helper gave an answer this Temper doesn't know")),
    (b"", ("", "slot acme-2: the host helper gave no answer")),
])
def test_the_client_reads_each_answer_plainly(host, answer, expected):
    fake = OneAnswer(host.sock_dir / "fake.sock", answer)
    try:
        assert host_helper.token(fake.path, "acme-2") == expected
        assert fake.lines == [b"token acme-2\n"]
    finally:
        fake.close()


def test_the_client_gives_up_on_a_silent_helper(host):
    fake = OneAnswer(host.sock_dir / "fake.sock", None)
    try:
        assert host_helper.token(fake.path, "acme-2", timeout=0.5) == (
            "", "slot acme-2: the host helper gave no answer within 0.5 s")
    finally:
        fake.close()


@pytest.mark.parametrize("slot", ["", "acme 2", "acme-2\ntoken acme-3", "../x"])
def test_the_client_never_sends_a_malformed_slot(host, slot):
    fake = OneAnswer(host.sock_dir / "fake.sock", b"ok tok\n")
    try:
        token, why = host_helper.token(fake.path, slot)
        assert token == "" and "malformed" in why and fake.lines == []
    finally:
        fake.close()


# --- the turn shows the refusal --------------------------------------------------------------


def test_a_refused_handoff_leads_the_failed_turns_errors(tmp_path):
    refusal = f"slot {SLOT}: no stored login for this slot"

    class Refused(FakeBox):
        def close(self):
            return {**super().close(), "handoff_slot": SLOT, "handoff_refused": refusal}

    FakeBox.behaviour = "provider_error"
    cfg = sup.box_config(tmp_path / "box")
    report = run_turn(cfg, _req(tmp_path, Recorder()), Ledger(), box_factory=Refused)
    assert report.state == "failed"
    assert report.outcome.errors[0] == refusal and report.error.startswith(refusal)
    assert report.worker["handoff_slot"] == SLOT


# --- E10: the branch client against the real helper -----------------------------------------


def branch_helper(host: Host, projects: Path, **over) -> Served:
    raw = host.config(**{"project_roots": [f"{projects}/*"], "branch_enabled": True, **over})
    raw.pop("bridge")  # the branch verb needs no bridge
    served = Served(host, raw, name="branch")
    assert served.wait_ready(), served.log()
    return served


def test_e10_makes_the_branch_through_the_real_helper(host):
    projects = host.root / "projects"
    source = projects / "app"
    make_source(source)
    leader, commit = make_leader(host.state, source)
    served = branch_helper(host, projects)
    try:
        ask = dict(source=str(source), leader_git_dir=str(leader), commit=commit, trial_id=TRIAL,
                   roots=[], helper_socket=served.socket)
        assert make_branch(**ask) == {"name": f"team/{TRIAL}", "made": True, "why": None}
        assert branch_of(source, TRIAL) == commit
        assert git("-C", str(source), "status", "--porcelain") == "", "never checked out"
        assert make_branch(**ask)["made"] is True, "a branch already at the commit counts as made"
        older = git("-C", str(source), "rev-parse", "HEAD")
        git("-C", str(source), "update-ref", f"refs/heads/team/{'b' * 12}", older)
        assert make_branch(**{**ask, "trial_id": "b" * 12}) == {
            "name": f"team/{'b' * 12}", "made": False, "why": "exists"}
        outside = host.root / "elsewhere"
        make_source(outside)
        denied = make_branch(**{**ask, "source": str(outside), "trial_id": "c" * 12})
        assert denied["made"] is False and denied["why"].startswith("denied: ")
        assert branch_of(outside, "c" * 12) == ""
    finally:
        served.stop()
    assert make_branch(**ask) == {"name": f"team/{TRIAL}", "made": False,
                                  "why": f"the host helper isn't running ({served.socket})"}
    log = served.log()
    assert "verb=branch" in log and "result=made" in log and "result=exists" in log


def test_e10_with_the_branch_verb_off(host):
    projects = host.root / "projects"
    source = projects / "app"
    make_source(source)
    leader, commit = make_leader(host.state, source)
    served = branch_helper(host, projects, branch_enabled=False)
    try:
        got = make_branch(source=str(source), leader_git_dir=str(leader), commit=commit,
                          trial_id=TRIAL, roots=[], helper_socket=served.socket)
    finally:
        served.stop()
    assert got == {"name": f"team/{TRIAL}", "made": False, "why": "denied: the branch verb is off"}
    assert branch_of(source, TRIAL) == ""
