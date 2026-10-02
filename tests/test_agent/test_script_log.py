"""A script attempt's log (agent/script_log.py): output saved in rows as it is printed.

The writer here is a list (or a list that fails, or one that is slow), so these tests are about
the log itself: order, labels, batching, the limit, the end note, and that writing never waits.
"""

from __future__ import annotations

import threading
import time

import pytest

from temper_ai.agent import script_log
from temper_ai.agent.script_log import (
    DEFAULT_LOG_MAX_BYTES,
    ROW_MAX_BYTES,
    ScriptLog,
    log_limit,
)


class Saved:
    """A writer that keeps the rows, optionally failing its first calls or waiting to be let go."""

    def __init__(self, fail_first: int = 0, gate: threading.Event | None = None):
        self.rows: list[tuple[int, dict]] = []
        self.calls = 0
        self.fail_first = fail_first
        self.gate = gate
        self.lock = threading.Lock()

    def __call__(self, rows):
        if self.gate is not None:
            self.gate.wait(10)
        with self.lock:
            self.calls += 1
            if self.calls <= self.fail_first:
                raise RuntimeError("database down")
            self.rows.extend(rows)

    @property
    def entries(self) -> list[dict]:
        return [e for _, data in self.rows for e in data["entries"]]

    def text(self, stream: str | None = None) -> str:
        return "".join(e["text"] for e in self.entries
                       if e["stream"] != "temper" and (stream is None or e["stream"] == stream))

    def notes(self, kind: str | None = None) -> list[dict]:
        return [e for e in self.entries if e["stream"] == "temper" and (kind is None or e["kind"] == kind)]


def _log(saved: Saved, **kw) -> ScriptLog:
    kw.setdefault("flush_interval", 0.02)
    kw.setdefault("close_wait", 5)
    return ScriptLog("attempt-1", saved, **kw)


def _wait_for(check, seconds: float = 3.0) -> None:
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.01)


def test_output_is_saved_while_the_script_runs_not_when_it_ends():
    saved = Saved()
    log = _log(saved)
    log.write("stdout", b"first line\n")
    _wait_for(lambda: saved.rows)
    assert saved.text() == "first line\n"
    assert saved.rows[0][1]["seq"] == 1 and "end" not in saved.rows[0][1]
    assert log.close("completed", exit_code=0)


def test_entries_keep_their_stream_their_time_and_the_order_they_were_read_in():
    saved = Saved()
    log = _log(saved)
    log.write("stdout", b"out 1\n")
    log.write("stderr", b"err 1\n")
    log.write("stdout", b"out 2\n")
    log.close("completed", exit_code=0)
    out = [(e["stream"], e["text"]) for e in saved.entries if e["stream"] != "temper"]
    assert out == [("stdout", "out 1\n"), ("stderr", "err 1\n"), ("stdout", "out 2\n")]
    for e in saved.entries:
        assert e["t"].endswith("+00:00") and len(e["t"].split("T")[1]) == len("12:34:56.789+00:00")


def test_pieces_of_one_stream_read_together_share_an_entry():
    saved = Saved()
    log = _log(saved, flush_interval=5)  # nothing is saved before the close
    for i in range(5):
        log.write("stdout", f"{i}".encode())
    log.close("completed", exit_code=0)
    out = [e for e in saved.entries if e["stream"] == "stdout"]
    assert len(out) == 1 and out[0]["text"] == "01234"


def test_a_character_split_across_reads_and_windows_line_ends_come_out_whole():
    saved = Saved()
    log = _log(saved)
    log.write("stdout", b"caf\xc3")
    log.write("stdout", b"\xa9\r")
    log.write("stdout", b"\nnext\rline\r\n")
    log.write("stderr", b"bad \xff byte\n")
    log.close("completed", exit_code=0)
    assert saved.text("stdout") == "café\nnext\nline\n"
    assert saved.text("stderr") == "bad \ufffd byte\n"


def test_half_a_character_left_at_the_end_is_kept_as_a_replacement():
    saved = Saved()
    log = _log(saved)
    log.write("stdout", b"tail \xe2\x82")
    log.close("failed", exit_code=1)
    assert saved.text() == "tail \ufffd"


@pytest.mark.parametrize(("outcome", "kw", "text", "end"), [
    ("completed", {"exit_code": 0}, "[finished: exit code 0]", {"outcome": "completed", "exit_code": 0}),
    ("failed", {"exit_code": 3}, "[failed: exit code 3]", {"outcome": "failed", "exit_code": 3}),
    ("failed", {"detail": "ScriptRenderError: no"}, "[failed: ScriptRenderError: no]", {"outcome": "failed"}),
    ("timed_out", {"detail": "after 5s"}, "[timed out after 5s: stopped, with everything it started]",
     {"outcome": "timed_out"}),
    ("cancelled", {}, "[cancelled: the run was stopped]", {"outcome": "cancelled"}),
])
def test_the_log_ends_with_how_the_attempt_ended(outcome, kw, text, end):
    saved = Saved()
    log = _log(saved)
    log.write("stdout", b"some output\n")
    assert log.close(outcome, **kw) is True
    last_seq, last = saved.rows[-1]
    assert last["end"] == end
    note = last["entries"][-1]
    assert (note["stream"], note["kind"], note["text"]) == ("temper", "end", text)
    assert [seq for seq, _ in saved.rows] == list(range(1, last_seq + 1))
    assert log.summary()["complete"] is True
    assert saved.text() == "some output\n", "the output before the end is kept"


def test_a_log_with_no_output_still_says_how_it_ended():
    saved = Saved()
    log = _log(saved)
    assert log.close("completed", exit_code=0)
    assert [e["kind"] for e in saved.entries] == ["end"]
    assert log.summary() == {"rows": 1, "saved_bytes": 0, "dropped_bytes": 0, "lost_bytes": 0,
                             "limit": DEFAULT_LOG_MAX_BYTES, "truncated": False, "complete": True}


def test_output_after_the_close_is_ignored_and_a_second_close_changes_nothing():
    saved = Saved()
    log = _log(saved)
    log.write("stdout", b"a\n")
    assert log.close("completed", exit_code=0)
    log.write("stdout", b"late\n")
    assert log.close("failed", exit_code=1) is True
    assert saved.text() == "a\n" and len(saved.notes("end")) == 1


def test_an_unknown_stream_is_ignored():
    saved = Saved()
    log = _log(saved)
    log.write("stdin", b"what\n")
    log.close("completed", exit_code=0)
    assert saved.text() == ""


def test_the_limit_keeps_the_first_bytes_and_says_so_once():
    saved = Saved()
    log = _log(saved, limit_bytes=10)
    log.write("stdout", b"0123456789ABCDEF")
    for _ in range(3):
        log.write("stderr", b"more\n")
    log.close("completed", exit_code=0)
    assert saved.text() == "0123456789"
    assert len(saved.notes("truncated")) == 1
    assert "10 bytes of output saved" in saved.notes("truncated")[0]["text"]
    assert saved.notes("end")[0]["text"] == (
        "[finished: exit code 0. 21 bytes printed after the log limit were not saved]")
    summary = log.summary()
    assert (summary["saved_bytes"], summary["dropped_bytes"], summary["truncated"]) == (10, 21, True)
    assert summary["limit"] == 10
    last = saved.rows[-1][1]
    assert (last["saved_bytes"], last["dropped_bytes"], last["truncated"], last["limit"]) == (10, 21, True, 10)


def test_the_limit_never_cuts_a_character_in_half():
    saved = Saved()
    log = _log(saved, limit_bytes=2)
    log.write("stdout", "aé b".encode())
    log.close("completed", exit_code=0)
    assert saved.text() == "a"
    assert log.summary()["saved_bytes"] == 1


def test_a_limit_of_zero_saves_no_output_but_still_the_notes():
    saved = Saved()
    log = _log(saved, limit_bytes=0)
    log.write("stdout", b"hello\n")
    log.close("completed", exit_code=0)
    assert saved.text() == ""
    assert [n["kind"] for n in saved.notes()] == ["truncated", "end"]


def test_rows_are_bounded_and_numbered_without_gaps():
    saved = Saved()
    log = _log(saved)
    blob = ("y" * 99 + "\n") * 3000  # 300 KB in one read
    log.write("stdout", blob.encode())
    log.close("completed", exit_code=0)
    seqs = [seq for seq, _ in saved.rows]
    assert seqs == list(range(1, len(seqs) + 1)) and len(seqs) >= 5
    for _, data in saved.rows:
        assert data["bytes"] <= ROW_MAX_BYTES
        assert all(len(e["text"]) <= script_log.ENTRY_MAX_CHARS for e in data["entries"])
    assert saved.text() == blob
    assert saved.rows[-1][1]["saved_bytes"] == len(blob)


def test_rows_that_fail_to_save_are_tried_again_in_order():
    saved = Saved(fail_first=3)
    log = _log(saved)
    for i in range(5):
        log.write("stdout", f"line {i}\n".encode())
        time.sleep(0.03)
    assert log.close("completed", exit_code=0) is True
    seqs = [seq for seq, _ in saved.rows]
    assert seqs == list(range(1, len(seqs) + 1)), "a row was skipped or saved twice"
    assert saved.text() == "".join(f"line {i}\n" for i in range(5))


def test_when_saving_never_works_the_close_gives_up_and_says_the_log_is_not_whole(caplog):
    saved = Saved(fail_first=10**9)
    log = _log(saved, close_wait=0.3)
    log.write("stdout", b"lost to a dead database\n")
    t0 = time.monotonic()
    assert log.close("completed", exit_code=0) is False
    assert time.monotonic() - t0 < 2
    assert log.summary()["complete"] is False
    assert "without its end note" in caplog.text


def test_writing_never_waits_for_saving():
    gate = threading.Event()
    saved = Saved(gate=gate)
    log = _log(saved)
    t0 = time.monotonic()
    for _ in range(200):
        log.write("stdout", b"z" * 4096)  # 800 KB while the database is stuck
    assert time.monotonic() - t0 < 1.0
    gate.set()
    assert log.close("completed", exit_code=0)
    assert saved.text() == "z" * 4096 * 200
    assert log.summary()["lost_bytes"] == 0


def test_with_the_limit_under_the_waiting_room_a_stuck_database_loses_nothing_the_limit_keeps():
    """The limit cuts first: what lies past it is dropped (and said so), never counted as lost."""
    gate = threading.Event()
    saved = Saved(gate=gate)
    log = _log(saved, limit_bytes=300_000)
    for _ in range(125):
        log.write("stdout", b"q" * 4000)  # 500 KB, all of it while nothing can be saved
    gate.set()
    assert log.close("completed", exit_code=0)
    summary = log.summary()
    assert (summary["saved_bytes"], summary["dropped_bytes"], summary["lost_bytes"]) == (300_000, 200_000, 0)
    assert saved.text() == "q" * 300_000 and not saved.notes("lost")


def test_past_the_waiting_room_output_is_counted_as_lost_and_noted(monkeypatch):
    monkeypatch.setattr(script_log, "PENDING_MAX_BYTES", 200_000)
    gate = threading.Event()
    saved = Saved(gate=gate)
    log = _log(saved, limit_bytes=10**9)
    for _ in range(150):
        # 600 KB while nothing can be saved: at most 200 KB in the stuck write, 200 KB waiting
        log.write("stdout", b"w" * 4000)
    gate.set()
    _wait_for(lambda: len(saved.text()) == log.summary()["saved_bytes"])
    log.write("stdout", b"after\n")
    assert log.close("completed", exit_code=0)
    lost = saved.notes("lost")
    assert len(lost) == 1 and lost[0]["lost_bytes"] == log.summary()["lost_bytes"] >= 200_000
    assert "could not be saved" in lost[0]["text"]
    assert saved.text().endswith("after\n")
    assert len(saved.text()) + log.summary()["lost_bytes"] == 600_000 + len("after\n")


def test_two_logs_at_once_keep_their_own_rows():
    a, b = Saved(), Saved()
    log_a, log_b = ScriptLog("attempt-a", a, flush_interval=0.02), ScriptLog("attempt-b", b, flush_interval=0.02)

    def talk(log: ScriptLog, name: str) -> None:
        for i in range(50):
            log.write("stdout", f"{name}{i}\n".encode())

    threads = [threading.Thread(target=talk, args=(log_a, "a")), threading.Thread(target=talk, args=(log_b, "b"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log_a.close("completed", exit_code=0)
    log_b.close("completed", exit_code=0)
    assert a.text() == "".join(f"a{i}\n" for i in range(50))
    assert b.text() == "".join(f"b{i}\n" for i in range(50))
    assert {data["attempt_id"] for _, data in a.rows} == {"attempt-a"}
    assert {data["attempt_id"] for _, data in b.rows} == {"attempt-b"}


def test_the_limit_setting():
    assert log_limit({}) == DEFAULT_LOG_MAX_BYTES == 10_000_000
    assert log_limit({"log_max_bytes": 5}) == 5
    assert log_limit({"log_max_bytes": 0}) == 0
    for bad in (-1, "10", True, 1.5, None):
        with pytest.raises(ValueError, match="log_max_bytes"):
            log_limit({"log_max_bytes": bad})
