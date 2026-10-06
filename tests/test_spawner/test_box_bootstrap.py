"""Box secrets BS2: the one-shot delivery's two ends (spawner/box_bootstrap.py), on the host.

The runner's side (receive) and the writer's side (deliver) meet in a folder that stands
in for the box's private tmpfs. What needs a real box (the tmpfs, docker-init, docker
exec, the real final entry) is in test_box_bootstrap_docker.py. Every value is synthetic.
"""

from __future__ import annotations

import ctypes
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from temper_ai.shared.agent_env import env_for_agent_tool
from temper_ai.spawner import box_bootstrap as bb
from temper_ai.spawner import box_guard
from temper_ai.spawner.box_view import (
    DIGEST_ENV,
    GENERATION_ENV,
    PROFILE_ENV,
    digest_of,
)
from tests.test_spawner.box_fixtures import SYNTHETIC_MARK

REPO = Path(__file__).resolve().parents[2]
EXEC = "b5200000-0000-4000-8000-000000000001"
NAMES = {"SYNTH_SERVICE_TOKEN": SYNTHETIC_MARK,
         "TEMPER_DATABASE_URL": f"postgresql://temper:{SYNTHETIC_MARK}@db:5432/temper"}


def _no_protect() -> None:
    """The real prctl would make the test process itself unreadable: tested in a child."""


@pytest.fixture(autouse=True)
def _fresh_state():
    bb.reset()
    yield
    bb.reset()


@pytest.fixture
def boot(tmp_path) -> Path:
    folder = tmp_path / "boot"
    folder.mkdir()
    folder.chmod(0o700)
    return folder


def _doc(folder: Path, *, generation: int = 2, names=NAMES, **limits) -> dict:
    section = bb.section(names=names, uid=1000, gid=1000, limits=limits or None)
    section["dir"] = str(folder)
    return {"schema_version": 2, "execution_id": EXEC, "generation": generation,
            "boundary": "sealed", "bootstrap": section}


def _env(doc: dict) -> dict[str, str]:
    return {PROFILE_ENV: json.dumps(doc), DIGEST_ENV: digest_of(doc),
            GENERATION_ENV: str(doc["generation"])}


def _tmpfs(folder: Path, *, fstype: str = "tmpfs",
           options: tuple[str, ...] = ("rw", "nosuid", "nodev", "noexec")):
    return lambda: [{"target": str(folder), "options": set(options), "fstype": fstype,
                     "super": set()}]


class Writer(threading.Thread):
    """The worker's writer, as `docker exec -i` runs it in the box (here a thread)."""

    def __init__(self, folder: Path, data: bytes | bytearray, *, execution: str = EXEC,
                 generation: int = 2, ready: int = 10, ack: int = 10,
                 max_bytes: int | None = None) -> None:
        super().__init__(daemon=True)
        self.stdin = tempfile.TemporaryFile()
        self.stdin.write(bytes(data))
        self.stdin.seek(0)
        self.args = ["--dir", str(folder), "--leaf", bb.LEAF,
                     "--max", str(max_bytes or bb.LIMITS["max_bytes"]),
                     "--ready", str(ready), "--ack", str(ack),
                     "--execution", execution, "--generation", str(generation)]
        self.out = io.StringIO()
        self.code: int | None = None

    def run(self) -> None:
        try:
            self.code = bb.deliver(self.args, stdin=self.stdin.fileno(), out=self.out,
                                   protect=_no_protect)
        finally:
            self.stdin.close()

    def status(self) -> dict:
        self.join(30)
        text = self.out.getvalue()
        assert SYNTHETIC_MARK not in text
        return json.loads(text.strip().splitlines()[-1])


class Planter(threading.Thread):
    """Something other than the writer puts a leaf there once the runner waits."""

    def __init__(self, folder: Path, plant) -> None:
        super().__init__(daemon=True)
        self.folder, self.plant = folder, plant

    def run(self) -> None:
        deadline = time.monotonic() + 10
        while not (self.folder / bb.WAITING).exists():
            if time.monotonic() > deadline:
                return
            time.sleep(0.01)
        self.plant(self.folder / bb.LEAF)


def _file(data: bytes, mode: int = 0o600):
    def plant(leaf: Path) -> None:
        tmp = leaf.with_name(".planted")
        tmp.write_bytes(data)
        tmp.chmod(mode)
        os.rename(tmp, leaf)
    return plant


def _forge(doc: dict, *, header: dict | None = None, body: bytes | None = None, values=NAMES,
           digest: str | None = None, now: float | None = None, newline: bool = True) -> bytes:
    """A real envelope's bytes, then changed: the header's fields, the secret part, the end."""
    real = bb.envelope(doc, digest or digest_of(doc), values, now=now)
    head = json.loads(bytes(real[:bb.HEADER_BYTES]).decode("ascii"))
    payload = bytes(real[bb.HEADER_BYTES:]) if body is None else body
    if body is not None:
        head["length"] = len(payload)
    head.update(header or {})
    raw = json.dumps(head).encode("ascii").ljust(bb.HEADER_BYTES - 1, b" ")
    return raw + (b"\n" if newline else b" ") + payload


def _refused(boot: Path, plant, *, doc: dict | None = None, **receive_kw) -> str:
    """The runner refuses: no value taken, no tool allowed, the leaf gone, a refusal acked."""
    doc = doc or _doc(boot)
    receive_kw.setdefault("linger", 0)  # no writer here to read the refusal
    target: dict = {}
    planter = Planter(boot, plant)
    planter.start()
    with pytest.raises(bb.DeliveryRefused) as caught:
        bb.receive(_env(doc), protect=_no_protect, mounts=_tmpfs(boot), target=target,
                   **receive_kw)
    planter.join(10)
    reason = str(caught.value)
    assert target == {}
    assert not bb.tools_allowed()
    assert SYNTHETIC_MARK not in reason
    assert not os.path.lexists(boot / bb.LEAF)
    assert not (boot / bb.WAITING).exists()
    ack_text = (boot / bb.ACK).read_text()
    assert SYNTHETIC_MARK not in ack_text
    ack = json.loads(ack_text)
    assert (ack["state"], ack["reason"]) == ("refused", reason)
    return reason


# -- the whole exchange ----------------------------------------------------------------------


def test_a_delivery_is_read_once_closed_removed_and_only_then_acknowledged(boot):
    doc = _doc(boot)
    writer = Writer(boot, bb.envelope(doc, digest_of(doc), NAMES))
    writer.start()
    target: dict = {}
    taken = bb.receive(_env(doc), protect=_no_protect, mounts=_tmpfs(boot), target=target)
    status = writer.status()  # the writer is done too (it reads the ack)

    assert target == NAMES
    assert taken == {"generation": 2, "names": sorted(NAMES)}
    assert bb.tools_allowed()
    # No delivery source or destination after the ack: the folder holds the ack alone, and
    # no descriptor of this process points at the delivery any more.
    assert sorted(os.listdir(boot)) == [bb.ACK]
    held = [os.readlink(f"/proc/self/fd/{fd}") for fd in os.listdir("/proc/self/fd")
            if os.path.exists(f"/proc/self/fd/{fd}")]
    assert not any(str(boot) in target_ for target_ in held)
    ack_text = (boot / bb.ACK).read_text()
    assert SYNTHETIC_MARK not in ack_text
    ack = json.loads(ack_text)
    assert (ack["state"], ack["names"], ack["generation"]) == ("consumed", 2, 2)
    assert (writer.code, status["state"], status["names"]) == (0, "consumed", 2)


def test_a_second_take_in_the_same_process_is_the_first_one():
    bb._STATE.update(mode=bb.ONESHOT, allowed=True, taken={"generation": 2, "names": ["A"]})
    assert bb.receive({}) == {"generation": 2, "names": ["A"]}


def test_a_box_without_a_oneshot_profile_takes_nothing_and_may_start_tools(boot):
    env_section = {**_doc(boot), "bootstrap": dict(bb.ENV_SECTION)}
    assert bb.receive(_env(env_section)) is None
    assert bb.receive({}) is None
    assert bb.tools_allowed()


def test_an_unreadable_profile_is_left_to_the_box_check(boot):
    """A legacy box is never stopped by its profile (cli/run_workflow.py decides)."""
    env = {**_env(_doc(boot)), DIGEST_ENV: "sha256:" + "0" * 64}
    assert bb.oneshot_doc(env) is None
    assert bb.receive(env) is None


def test_a_restarted_runner_in_the_same_box_is_refused(boot):
    """One consumption per box: a replacement process finds the folder used and refuses."""
    doc = _doc(boot)
    writer = Writer(boot, bb.envelope(doc, digest_of(doc), NAMES))
    writer.start()
    bb.receive(_env(doc), protect=_no_protect, mounts=_tmpfs(boot), target={})
    assert writer.status()["state"] == "consumed"
    bb.reset()  # a new process
    with pytest.raises(bb.DeliveryRefused, match="one consumption per box"):
        bb.receive(_env(doc), protect=_no_protect, mounts=_tmpfs(boot), target={})
    assert not bb.tools_allowed()
    with pytest.raises(bb.DeliveryRefused, match="has not taken one"):
        bb.require_received(_env(doc))


# -- what the runner refuses -----------------------------------------------------------------


ENVELOPES = {
    "another run": (lambda d: _forge({**d, "execution_id": "another-run"}),
                    "wrong envelope: it is for another run"),
    "another profile": (lambda d: _forge(d, digest="sha256:" + "0" * 64),
                        "wrong envelope: it is for another box profile"),
    "stale generation": (lambda d: _forge({**d, "generation": 1}, digest=digest_of(d)),
                         "stale envelope: generation 1, this box is 2"),
    "newer generation": (lambda d: _forge({**d, "generation": 3}, digest=digest_of(d)),
                         "wrong envelope: generation 3"),
    "expired": (lambda d: _forge(d, now=time.time() - 600),
                "stale envelope: it expired before it was read"),
    "issued in the future": (lambda d: _forge(d, now=time.time() + 600),
                             "wrong envelope: its times are not the profile's"),
    "lives longer than the profile allows": (
        lambda d: _forge(d, header={"expires_at": time.time() + 86400}),
        "wrong envelope: its times are not the profile's"),
    "other names": (lambda d: _forge(d, values={**NAMES, "EXTRA_TOKEN": "synthetic"}),
                    "wrong envelope: its names are not the profile's"),
    "length": (lambda d: _forge(d, header={"length": 7}),
               "malformed envelope: its length is not the leaf's"),
    "schema": (lambda d: _forge(d, header={"schema": 2}),
               "wrong envelope: schema 2, this runner knows 1"),
    "kind": (lambda d: _forge(d, header={"kind": "something-else"}),
             "malformed envelope: not a box delivery"),
    "nonce": (lambda d: _forge(d, header={"nonce": "short"}), "malformed envelope: no nonce"),
    "header not JSON": (lambda d: b"{not json".ljust(bb.HEADER_BYTES - 1) + b"\n" + b"{}",
                        "malformed envelope: the header is not JSON"),
    "no complete header": (lambda d: _forge(d, newline=False),
                           "malformed envelope: no complete header"),
    "secret part not JSON": (lambda d: _forge(d, body=b"{not json"),
                             "malformed envelope: the secret part is not JSON"),
    "secret part's names": (
        lambda d: _forge(d, body=json.dumps({"OTHER_A": "a", "OTHER_B": "b"}).encode()),
        "malformed envelope: the secret part's names are not the profile's"),
    "a value not a string": (
        lambda d: _forge(d, body=json.dumps({"SYNTH_SERVICE_TOKEN": 1,
                                             "TEMPER_DATABASE_URL": "x"}).encode()),
        "malformed envelope: a value is not a plain string"),
    "no secret part": (lambda d: _forge(d)[:bb.HEADER_BYTES],
                       "malformed envelope: no secret part"),
    "oversized": (lambda d: b"x" * (bb.HEADER_BYTES + 4096 + 1),
                  "oversized envelope: larger than the profile allows"),
}


@pytest.mark.parametrize("case", sorted(ENVELOPES))
def test_a_wrong_stale_oversized_or_malformed_envelope_is_refused(boot, case):
    make, expect = ENVELOPES[case]
    doc = _doc(boot, max_bytes=4096)
    assert expect in _refused(boot, _file(make(doc)), doc=doc)


def _linked(leaf: Path) -> None:
    elsewhere = leaf.with_name(".elsewhere")
    elsewhere.write_bytes(_forge(_doc(leaf.parent)))
    elsewhere.chmod(0o600)
    os.symlink(elsewhere, leaf)


def _hard_linked(leaf: Path) -> None:
    other = leaf.with_name(".other-name")
    other.write_bytes(_forge(_doc(leaf.parent)))
    other.chmod(0o600)
    os.link(other, leaf)


@pytest.mark.parametrize(("plant", "expect"), [
    (lambda leaf: _file(_forge(_doc(leaf.parent)), 0o644)(leaf), "has mode 0644, not 0600"),
    (_linked, "the delivery is a link"),
    (_hard_linked, "the delivery has other names (hard links)"),
    (lambda leaf: os.mkfifo(leaf, 0o600), "the delivery is not a regular file"),
], ids=["mode", "symlink", "hard link", "fifo"])
def test_a_delivery_of_the_wrong_mode_or_kind_is_refused_unread(boot, plant, expect):
    assert expect in _refused(boot, plant)


@pytest.mark.parametrize("problem", ["missing", "a link", "mode", "not tmpfs", "no mount",
                                     "mount options", "not empty"])
def test_a_folder_that_is_not_the_runners_own_tmpfs_is_refused(boot, tmp_path, problem):
    folder, mounts = boot, _tmpfs(boot)
    expect = {"missing": "is missing", "a link": "is not a folder (a link?)",
              "mode": "has mode 0755, not 0700", "not tmpfs": "is not its own tmpfs",
              "no mount": "is not its own tmpfs", "mount options": "is not nosuid, nodev, noexec",
              "not empty": "is not empty"}[problem]
    if problem == "missing":
        folder = tmp_path / "nowhere"
    elif problem == "a link":
        folder = tmp_path / "link"
        folder.symlink_to(boot)
    elif problem == "mode":
        boot.chmod(0o755)
    elif problem == "not tmpfs":
        mounts = _tmpfs(boot, fstype="ext4")
    elif problem == "no mount":
        mounts = list
    elif problem == "mount options":
        mounts = _tmpfs(boot, options=("rw", "nosuid"))
    else:
        (boot / "left-over").write_text("x")
    doc = _doc(folder)
    target: dict = {}
    with pytest.raises(bb.DeliveryRefused, match=re.escape(expect)):
        bb.receive(_env(doc), protect=_no_protect, mounts=mounts, target=target)
    assert target == {}
    assert not bb.tools_allowed()
    assert not (boot / bb.WAITING).exists()


def test_no_delivery_within_the_deadline_is_refused(boot):
    doc = _doc(boot, delivery=1)
    started = time.monotonic()
    assert "timeout: no delivery within 1s" in _refused(boot, lambda leaf: None, doc=doc)
    assert time.monotonic() - started < 10


def test_a_failed_prctl_refuses_before_anything_is_read(boot):
    doc = _doc(boot)
    writer = Writer(boot, bb.envelope(doc, digest_of(doc), NAMES))
    writer.start()

    def failing() -> None:
        raise bb.DeliveryRefused("prctl failed: the runner could not make itself unreadable "
                                 "(errno 22)")

    target: dict = {}
    with pytest.raises(bb.DeliveryRefused, match="prctl failed"):
        bb.receive(_env(doc), protect=failing, mounts=_tmpfs(boot), target=target)
    assert target == {}
    status = writer.status()
    assert status["state"] == "refused" and "prctl failed" in status["reason"]
    # never waited, never written to; the writer read why (the runner waits for that)
    assert sorted(os.listdir(boot)) == [bb.ACK, bb.SEEN]


@pytest.mark.parametrize("how", ["unlink fails", "unlink does nothing"])
def test_a_delivery_that_cant_be_removed_is_refused(boot, how):
    calls: list[str] = []

    def unlink(path: str) -> None:
        calls.append(path)
        if path.endswith(os.sep + bb.LEAF) and calls.count(path) == 1:
            if how == "unlink fails":
                raise PermissionError(13, "synthetic")
            return  # pretends
        os.unlink(path)

    doc = _doc(boot)
    reason = _refused(boot, _file(_forge(doc)), doc=doc, unlink=unlink)
    assert reason.startswith("cleanup failed")


def test_a_child_started_inside_the_read_window_never_holds_the_delivery(boot, tmp_path,
                                                                         monkeypatch):
    """Close-on-exec, error path included: an error child started while the delivery is open
    gets no descriptor of it, though it does get one this process left inheritable."""
    decoy = tmp_path / "decoy"
    decoy.write_text("not secret")
    seen: dict = {}
    list_fds = ("import json, os\nout = []\nfor fd in os.listdir('/proc/self/fd'):\n"
                "    try:\n        out.append(os.readlink('/proc/self/fd/' + fd))\n"
                "    except OSError:\n        pass\nprint(json.dumps(out))")

    def failing_check(header, **kwargs):
        plain = os.open(decoy, os.O_RDONLY)
        os.set_inheritable(plain, True)
        try:
            seen["fds"] = json.loads(subprocess.run(
                [sys.executable, "-c", list_fds], capture_output=True, text=True,
                close_fds=False, check=True).stdout)
        finally:
            os.close(plain)
        raise bb.DeliveryRefused("synthetic failure inside the read window")

    monkeypatch.setattr(bb, "check_header", failing_check)
    doc = _doc(boot)
    writer = Writer(boot, bb.envelope(doc, digest_of(doc), NAMES))
    writer.start()
    with pytest.raises(bb.DeliveryRefused, match="synthetic failure"):
        bb.receive(_env(doc), protect=_no_protect, mounts=_tmpfs(boot), target={})
    assert str(decoy) in seen["fds"]  # the probe sees what a child inherits
    assert not any(t.startswith(str(boot)) for t in seen["fds"])
    assert writer.status()["state"] == "refused"
    assert sorted(os.listdir(boot)) == [bb.ACK, bb.SEEN]


# -- nothing starts before the delivery -------------------------------------------------------


def test_no_tool_or_agent_process_starts_before_the_delivery_is_taken(boot, monkeypatch):
    doc = _doc(boot)
    for name, value in _env(doc).items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TEMPER_BOX_ENV", raising=False)

    assert not bb.tools_allowed()
    with pytest.raises(box_guard.LaunchRefused, match="before the box's one-shot delivery"):
        box_guard.check("tool", "Bash")
    with pytest.raises(bb.DeliveryRefused, match="an agent tool's process can't start"):
        env_for_agent_tool()
    with pytest.raises(bb.DeliveryRefused, match="has not taken one"):
        bb.require_received()

    writer = Writer(boot, bb.envelope(doc, digest_of(doc), NAMES))
    writer.start()
    target: dict = {}
    bb.receive(protect=_no_protect, mounts=_tmpfs(boot), target=target)
    assert writer.status()["state"] == "consumed"
    assert bb.tools_allowed()
    box_guard.check("tool", "Bash")
    bb.require_received()
    assert SYNTHETIC_MARK not in json.dumps(env_for_agent_tool())


def test_a_process_that_never_asked_looks_at_its_profile_once(boot, monkeypatch):
    for name in (PROFILE_ENV, DIGEST_ENV, GENERATION_ENV):
        monkeypatch.delenv(name, raising=False)
    assert bb.tools_allowed()  # not a box: decided once, as env
    assert bb._STATE["mode"] == bb.ENV


# -- the writer's side ------------------------------------------------------------------------


def _waiting(boot: Path, *, execution: str = EXEC, generation: int = 2) -> None:
    (boot / bb.WAITING).write_text(json.dumps({"pid": 1, "execution_id": execution,
                                               "generation": generation, "profile": "x"}))


def test_cancelled_before_ready_the_writer_gives_up_and_writes_nothing(boot):
    doc = _doc(boot)
    writer = Writer(boot, bb.envelope(doc, digest_of(doc), NAMES), ready=1)
    writer.start()
    status = writer.status()
    assert (writer.code, status["state"]) == (1, "timeout")
    assert status["reason"] == "timeout: the runner was not waiting within 1s"
    assert os.listdir(boot) == []


def test_cancelled_after_ready_the_writer_takes_its_delivery_back(boot):
    doc = _doc(boot)
    _waiting(boot)
    writer = Writer(boot, bb.envelope(doc, digest_of(doc), NAMES), ack=1)
    writer.start()
    status = writer.status()
    assert (status["state"], status["reason"]) == ("timeout",
                                                   "timeout: no acknowledgement within 1s")
    assert os.listdir(boot) == [bb.WAITING]


@pytest.mark.parametrize(("setup", "writer_kw", "expect"), [
    (None, {"execution": "another-run"}, "wrong envelope: not this box's run and generation"),
    (None, {"generation": 3}, "wrong envelope: not this box's run and generation"),
    (None, {"max_bytes": 64}, "oversized envelope: larger than the profile allows"),
    ("waiting for another run", {}, "the waiting runner is another run's or generation's"),
    ("served already", {}, "the box has acknowledged a delivery already"),
    ("refused before waiting", {}, "prctl failed: synthetic"),
], ids=["another run", "another generation", "oversized", "another runner", "served",
        "runner refused"])
def test_the_writer_refuses_without_writing(boot, setup, writer_kw, expect):
    doc = _doc(boot)
    if setup == "waiting for another run":
        _waiting(boot, execution="another-run")
    elif setup == "served already":
        _waiting(boot)
        (boot / bb.ACK).write_text(json.dumps({"state": "consumed", "nonce": "0" * 16}))
    elif setup == "refused before waiting":
        (boot / bb.ACK).write_text(json.dumps({"state": "refused",
                                               "reason": "prctl failed: synthetic"}))
    writer = Writer(boot, bb.envelope(doc, digest_of(doc), NAMES), ready=2, **writer_kw)
    writer.start()
    status = writer.status()
    assert (writer.code, status["state"]) == (1, "refused")
    assert expect in status["reason"]
    assert not os.path.lexists(boot / bb.LEAF)
    assert not os.path.lexists(boot / f".{bb.LEAF}.tmp")


def test_an_acknowledgement_for_another_envelope_is_not_success(boot):
    doc = _doc(boot)
    _waiting(boot)
    writer = Writer(boot, bb.envelope(doc, digest_of(doc), NAMES))
    writer.start()
    deadline = time.monotonic() + 10
    while not (boot / bb.LEAF).exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    (boot / bb.LEAF).unlink()
    (boot / bb.ACK).write_text(json.dumps({"state": "consumed", "nonce": "0" * 16,
                                           "names": 2}))
    status = writer.status()
    assert (status["state"], status["reason"]) == (
        "refused", "the acknowledgement is for another delivery")


def test_a_writer_started_wrongly_says_so():
    out = io.StringIO()
    assert bb.deliver(["--dir"], stdin=0, out=out, protect=_no_protect) == 1
    assert json.loads(out.getvalue()) == {"state": "error",
                                          "reason": "the writer was started with bad arguments"}


def test_the_writer_runs_as_source_with_no_site_packages(boot):
    """What the worker runs: `python -I -S -c <source> --deliver ...`, envelope on stdin."""
    doc = _doc(boot)
    _waiting(boot)
    args = ["--deliver", "--dir", str(boot), "--leaf", bb.LEAF, "--max", "4096",
            "--ready", "2", "--ack", "1", "--execution", EXEC, "--generation", "2"]
    result = subprocess.run([sys.executable, "-I", "-S", "-c", bb.writer_program(), *args],
                            input=bytes(bb.envelope(doc, digest_of(doc), NAMES)),
                            capture_output=True, timeout=30, check=False)
    assert SYNTHETIC_MARK.encode() not in result.stdout + result.stderr
    assert json.loads(result.stdout) == {"state": "timeout",
                                         "reason": "timeout: no acknowledgement within 1s"}
    assert os.listdir(boot) == [bb.WAITING]


# -- the envelope and the profile's section ------------------------------------------------------


def test_the_envelope_header_is_fixed_size_and_holds_no_value(boot):
    doc = _doc(boot)
    data = bb.envelope(doc, digest_of(doc), NAMES)
    header = bb.header_of(data)
    assert data[bb.HEADER_BYTES - 1:bb.HEADER_BYTES] == b"\n"
    assert SYNTHETIC_MARK.encode() not in bytes(data[:bb.HEADER_BYTES])
    assert header["names"] == sorted(NAMES)
    assert header["length"] == len(data) - bb.HEADER_BYTES
    lifetime = header["expires_at"] - header["issued_at"]
    assert lifetime == pytest.approx(doc["bootstrap"]["expires_after"])
    bb.zero(data)
    assert set(data) == {0}


def test_an_envelope_larger_than_the_profile_allows_is_never_built(boot):
    with pytest.raises(bb.DeliveryRefused, match="larger than the profile allows"):
        bb.envelope(_doc(boot, max_bytes=16), "sha256:x", NAMES)


@pytest.mark.parametrize(("change", "expect"), [
    ({"owner": {"uid": 0, "gid": 0}}, "unprivileged"),
    ({"deadlines": {"ready": 0, "delivery": 60, "ack": 30}}, "deadlines.ready"),
    ({"protocol": "box-delivery/0"}, "bootstrap.protocol"),
    ({"consumption": "many"}, "consumption"),
    ({"leaf": "../escape"}, "fixed path"),
    ({"names": ["NOT A NAME"]}, "variable names"),
    ({"max_bytes": None}, "bootstrap.max_bytes is missing"),
])
def test_an_incomplete_or_unsafe_section_is_refused(change, expect):
    section = {**bb.section(names=["A_TOKEN"], uid=1000, gid=1000), **change}
    assert any(expect in problem for problem in bb.section_problems(section))
    with pytest.raises(bb.DeliveryRefused, match="incomplete"):
        bb.Params.of(section)


def test_the_tmpfs_is_private_to_the_runners_user():
    spec = bb.tmpfs_spec(bb.section(names=["A_TOKEN"], uid=999, gid=998))
    assert spec.startswith(f"{bb.BOOT_DIR}:rw,noexec,nosuid,nodev,")
    assert spec.endswith(",mode=0700,uid=999,gid=998")


# -- this process's own protection (in children, so the test process stays as it is) -------------


_CHILD = r"""
import ctypes, json, os, resource, sys
from temper_ai.spawner import box_bootstrap as bb
if sys.argv[1] == "protect":
    bb.protect_process()
libc = ctypes.CDLL(None)
print(json.dumps({"dumpable": libc.prctl(3, 0, 0, 0, 0),
                  "core": list(resource.getrlimit(resource.RLIMIT_CORE))}), flush=True)
sys.stdin.readline()
os.execv(sys.executable, [sys.executable, "-I", "-S", "-c",
                          "import ctypes; print(ctypes.CDLL(None).prctl(3, 0, 0, 0, 0))"])
"""


def _ptrace_scope() -> int:
    try:
        return int(Path("/proc/sys/kernel/yama/ptrace_scope").read_text())
    except (OSError, ValueError):
        return 0


def _looks(pid: int) -> dict:
    """What a same-user process (here the child's parent) can do to ``pid``."""
    out = {}
    for part in ("environ", "mem"):
        try:
            with open(f"/proc/{pid}/{part}", "rb") as fh:
                if part == "environ":
                    fh.read(1)
            out[part] = "read"
        except PermissionError:
            out[part] = "EACCES"
    libc = ctypes.CDLL(None, use_errno=True)
    libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
    seized = libc.ptrace(0x4206, pid, None, None)  # PTRACE_SEIZE: attaches without stopping
    out["ptrace"] = "attached" if seized == 0 else f"errno {ctypes.get_errno()}"
    return out


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any process: the check needs a user")
@pytest.mark.skipif(_ptrace_scope() >= 2, reason="this kernel lets no user attach at all")
@pytest.mark.parametrize("mode", ["protect", "control"])
def test_a_protected_process_refuses_reads_and_exec_resets_it(mode):
    child = subprocess.Popen([sys.executable, "-c", _CHILD, mode], cwd=REPO,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                             env={**os.environ, "PYTHONPATH": str(REPO)})
    after_exec = None
    try:
        first = json.loads(child.stdout.readline())
        looks = _looks(child.pid)
        if mode == "protect":  # (the control is being traced now: it is only killed)
            child.stdin.write("\n")
            child.stdin.flush()
            after_exec = int(child.stdout.readline())
    finally:
        child.kill()
        child.wait(10)
    if mode == "protect":
        assert first == {"dumpable": 0, "core": [0, 0]}
        assert looks == {"environ": "EACCES", "mem": "EACCES", "ptrace": "errno 1"}
        # exec resets it: a replacement interpreter has to repeat the whole protocol
        assert after_exec == 1
    else:  # the positive control: the same process, unprotected, is open to its parent
        assert first["dumpable"] == 1
        assert looks == {"environ": "read", "mem": "read", "ptrace": "attached"}


_INSTALL_CHILD = r"""
import asyncio, io, json, os, subprocess, sys, tempfile, threading
from temper_ai.spawner import box_bootstrap as bb
from temper_ai.spawner import box_view as bv
folder, mark = sys.argv[1], sys.argv[2]
names = {"SYNTH_SERVICE_TOKEN": mark, "TEMPER_DATABASE_URL": "postgresql://t:" + mark + "@db/x"}
section = bb.section(names=names, uid=1000, gid=1000)
section["dir"] = folder
doc = {"schema_version": 2, "execution_id": "exec-c", "generation": 1, "boundary": "sealed",
       "bootstrap": section}
env = {bv.PROFILE_ENV: json.dumps(doc), bv.DIGEST_ENV: bv.digest_of(doc), bv.GENERATION_ENV: "1"}
stdin = tempfile.TemporaryFile()
stdin.write(bytes(bb.envelope(doc, env[bv.DIGEST_ENV], names)))
stdin.seek(0)
args = ["--dir", folder, "--leaf", bb.LEAF, "--max", "4096", "--ready", "10", "--ack", "10",
        "--execution", "exec-c", "--generation", "1"]
out = io.StringIO()
writer = threading.Thread(target=bb.deliver, args=(args,),
                          kwargs={"stdin": stdin.fileno(), "out": out, "protect": lambda: None})
writer.start()
mounts = lambda: [{"target": folder, "options": {"nosuid", "nodev", "noexec"},
                   "fstype": "tmpfs", "super": set()}]
bb.receive(env, protect=lambda: None, mounts=mounts)
writer.join()
os.environ["SYNTH_CONTROL"] = "SYNTHETIC-CONTROL-VALUE"  # set the ordinary way: children get it
seen = {}
def child(key, **kw):
    seen[key] = subprocess.run(["env"], capture_output=True, text=True, **kw).stdout
child("default")
child("close_fds False", close_fds=False)
child("posix_spawn shape", close_fds=False, executable="/usr/bin/env")
fd, path = tempfile.mkstemp()
os.close(fd)
os.system("env > " + path)
seen["os.system"] = open(path).read()
async def aio():
    proc = await asyncio.create_subprocess_exec("env", stdout=asyncio.subprocess.PIPE)
    return (await proc.communicate())[0].decode()
seen["asyncio"] = asyncio.run(aio())
seen["own environ"] = open("/proc/self/environ", "rb").read().decode("utf-8", "replace")
print(json.dumps({
    "mapping": os.environ.get("SYNTH_SERVICE_TOKEN") == mark,
    "getenv": os.getenv("TEMPER_DATABASE_URL") == names["TEMPER_DATABASE_URL"],
    "posix_spawn": subprocess._USE_POSIX_SPAWN,
    "leaks": sorted(k for k, v in seen.items() if mark in v),
    "control": sorted(k for k, v in seen.items() if "SYNTHETIC-CONTROL-VALUE" in v),
    "writer": json.loads(out.getvalue())["state"],
}))
"""


def test_values_live_in_the_runners_mapping_and_no_child_starts_with_them(boot):
    result = subprocess.run([sys.executable, "-c", _INSTALL_CHILD, str(boot), SYNTHETIC_MARK],
                            cwd=REPO, capture_output=True, text=True, timeout=60,
                            env={**os.environ, "PYTHONPATH": str(REPO)}, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout)
    assert report["writer"] == "consumed"
    assert report["mapping"] and report["getenv"]  # Python readers find them as before
    assert report["posix_spawn"] is False
    assert report["leaks"] == []
    # The probe would have seen a value set the usual way in every child (a process's own
    # /proc environ is the block it started with, so there only the mark is looked for).
    assert report["control"] == ["asyncio", "close_fds False", "default", "os.system",
                                 "posix_spawn shape"]
