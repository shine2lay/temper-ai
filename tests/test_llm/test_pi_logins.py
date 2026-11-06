"""temper_ai.llm.pi_logins: the pi slots temper's Claude pools use, from the pools file, and
one slot's login per call from the host helper's pools door (docs/pools.md, "Where the
logins come from").  A fixed fake helper answers; no real login, no model call."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from temper_ai.llm import pi_logins

CANARY = "CANARY-PI-LOGIN-" + os.urandom(8).hex()


class FakeHelper:
    """A stand-in pools door: answers each ``token <slot> [<s>]`` line from ``answers`` (slot
    -> answer bytes), records every line it got."""

    def __init__(self, path: str, answers: dict[str, bytes]):
        self.path = path
        self.answers = answers
        self.lines: list[str] = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen()
        self.done = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while not self.done.is_set():
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                line = conn.recv(4096).decode().strip()
                self.lines.append(line)
                parts = line.split(" ")
                conn.sendall(self.answers.get(parts[1] if len(parts) > 1 else "", b"denied unknown\n"))

    def close(self) -> None:
        self.done.set()
        self.server.close()


@pytest.fixture
def sock_dir():
    folder = tempfile.mkdtemp(prefix="pl", dir="/tmp")  # short: a socket path must be < 108 bytes
    yield Path(folder)
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def helper(sock_dir, monkeypatch):
    fake = FakeHelper(str(sock_dir / "p.sock"), {
        "anthropic": f"ok {CANARY}\n".encode(),
        "anthropic-2": b"denied slot anthropic-2 has no stored login\n",
        "anthropic-3": b"two words here\n",
    })
    monkeypatch.setenv(pi_logins.SOCKET_ENV, fake.path)
    yield fake
    fake.close()


def write_pools(config_dir: Path, text: str, *, local: bool = False) -> Path:
    folder = config_dir / "pools" / ("local" if local else "")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "pools.yaml"
    path.write_text(text)
    return path


# --- the whole path: configured slots, then one login per call -----------------------------


def test_each_configured_slot_is_asked_for_its_own_login_per_call_and_nothing_is_kept(tmp_path, helper, caplog):
    """The pools file names the slots in order; each fetch asks the helper again (no copy is
    kept), with the call's time plus the margin as the asked validity; a refusal names its
    slot; the login is in no exception, log record or file."""
    write_pools(tmp_path, "pools:\n  week_line: 0.9\n  logins:\n    slots: [anthropic, anthropic-2]\n")
    assert pi_logins.configured_slots(tmp_path) == ["anthropic", "anthropic-2"]
    assert pi_logins.fetch("anthropic", 600) == CANARY
    assert pi_logins.fetch("anthropic") == CANARY
    with pytest.raises(pi_logins.PiLoginRefused) as refused:
        pi_logins.fetch("anthropic-2", 3600)
    assert refused.value.slot == "anthropic-2"
    assert refused.value.why == "slot anthropic-2 has no stored login"
    assert helper.lines == ["token anthropic 1800", "token anthropic 1800", "token anthropic-2 3900"]
    assert CANARY not in caplog.text
    assert [p for p in tmp_path.rglob("*") if p.is_file() and CANARY.encode() in p.read_bytes()] == []


# --- configured_slots -----------------------------------------------------------------


def test_no_logins_block_means_no_slots(tmp_path):
    write_pools(tmp_path, "pools:\n  week_line: 0.9\n")
    assert pi_logins.configured_slots(tmp_path) == []


def test_no_pools_file_means_no_slots(tmp_path):
    assert pi_logins.configured_slots(tmp_path) == []


def test_the_local_file_wins(tmp_path):
    write_pools(tmp_path, "pools:\n  logins:\n    slots: [anthropic, anthropic-2]\n")
    write_pools(tmp_path, "pools:\n  logins:\n    slots: [anthropic-2]\n", local=True)
    assert pi_logins.configured_slots(tmp_path) == ["anthropic-2"]


def test_a_slot_removed_from_the_file_leaves_on_the_next_read_without_a_restart(tmp_path):
    path = write_pools(tmp_path, "pools:\n  logins:\n    slots: [anthropic, anthropic-2]\n")
    assert pi_logins.configured_slots(tmp_path) == ["anthropic", "anthropic-2"]
    path.write_text("pools:\n  logins:\n    slots: [anthropic]\n")
    later = time.time() + 5
    os.utime(path, (later, later))  # a new mtime, as an edit seconds later has
    assert pi_logins.configured_slots(tmp_path) == ["anthropic"]


@pytest.mark.parametrize("text, expected", [
    ("pools:\n  logins: [anthropic]\n", "pools.logins must hold exactly one key, slots"),
    ("pools:\n  logins:\n    slots: [anthropic]\n    extra: 1\n", "pools.logins must hold exactly one key, slots"),
    ("pools:\n  logins:\n    slots: anthropic\n", "pools.logins.slots must be a list of pi slot names"),
    ("pools:\n  logins:\n    slots: [anthropic, 'a b']\n", "pools.logins.slots has 'a b', not a pi slot name"),
    ("pools:\n  logins:\n    slots: [anthropic, 2]\n", "pools.logins.slots has 2, not a pi slot name"),
    ("pools:\n  logins:\n    slots: [anthropic, anthropic]\n", "pools.logins.slots names a slot twice"),
    ("pools: [1]\n", "has no pools settings"),
    ("pools: {\n", "can't be read (ParserError)"),
])
def test_a_malformed_slot_list_fails_loud_every_time(tmp_path, text, expected):
    write_pools(tmp_path, text)
    for _ in range(2):  # not remembered as fine, and not remembered as empty
        with pytest.raises(pi_logins.PiLoginsMisconfigured, match=expected.replace("(", r"\(").replace(")", r"\)")):
            pi_logins.configured_slots(tmp_path)


# --- validity_for ---------------------------------------------------------------------


@pytest.mark.parametrize("call_seconds, asked", [
    (None, 1800), (0, 1800), (-5, 1800), (float("nan"), 1800), (float("inf"), 1800),
    (100, 1800), (1500, 1800), (1501, 1801), (3600, 3900), (14100, 14400), (99999, 14400),
])
def test_the_asked_validity_is_the_call_plus_a_margin_within_the_helpers_range(call_seconds, asked):
    assert pi_logins.validity_for(call_seconds) == asked


# --- fetch failures -------------------------------------------------------------------


def test_no_socket_set_fails_loud_and_names_the_setting(monkeypatch):
    monkeypatch.delenv(pi_logins.SOCKET_ENV, raising=False)
    with pytest.raises(pi_logins.PiLoginsUnreachable, match="TEMPER_PI_LOGINS_SOCKET .* is not set here"):
        pi_logins.fetch("anthropic")


def test_a_helper_that_is_not_running_fails_loud_and_names_the_socket(sock_dir, monkeypatch):
    path = str(sock_dir / "none.sock")
    monkeypatch.setenv(pi_logins.SOCKET_ENV, path)
    with pytest.raises(pi_logins.PiLoginsUnreachable) as err:
        pi_logins.fetch("anthropic")
    assert str(err.value) == (f"temper's Claude logins come from pi through temper-pi-host at {path}, "
                              f"which is not answering (slot anthropic: the host helper isn't running ({path}))")


def test_an_answer_the_client_does_not_know_is_unreachable_and_never_echoed(helper):
    with pytest.raises(pi_logins.PiLoginsUnreachable) as err:
        pi_logins.fetch("anthropic-3")
    assert "two words" not in str(err.value)
    assert "gave an answer this Temper doesn't know" in str(err.value)


@pytest.mark.parametrize("slot", ["", "a b", "anthropic\ntoken anthropic-2", "../x"])
def test_a_malformed_slot_is_refused_without_asking(helper, slot):
    with pytest.raises(pi_logins.PiLoginRefused):
        pi_logins.fetch(slot)
    assert helper.lines == []


# --- the Pi agent stays switched off ----------------------------------------------------


def test_the_pools_client_imports_nothing_of_the_pi_agent():
    """Temper's pools use the helper with the Pi agent switched off: importing the pools'
    login source loads no temper_ai.pi_agent module."""
    code = ("import sys, temper_ai.llm.pi_logins; "
            "print(sorted(m for m in sys.modules if m.startswith('temper_ai.pi_agent')))")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                          check=True, cwd=Path(__file__).resolve().parents[2])
    assert done.stdout.strip() == "[]"
