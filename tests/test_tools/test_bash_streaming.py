"""The Bash tool with an output sink: a script agent's output, handed over as it is printed.

A script agent passes `_output_sink` (its live log, agent/script_log.py). The pipes are then read
as the script writes them, both at once, and each piece goes to the sink before the next read.
Everything else must stay as it was: the result, its JSON, the exit status, the timeout and the
cancel, and the killing of everything the script started.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from temper_ai.tools.bash import (
    _CANCELLED_ERROR,
    _MAX_OUTPUT_SIZE,
    Bash,
    _StreamText,
    _timeout_error,
)


def _run(command: str, sink=None, **params):
    if sink is not None:
        params["_output_sink"] = sink
    return Bash().execute(command=command, _skip_allowlist=True, **params)


def _same(a, b) -> None:
    assert (a.success, a.result, a.error, a.metadata) == (b.success, b.result, b.error, b.metadata)


# Each: the command, and the parameters a script agent (or a test of the old path) passes.
PARITY = [
    pytest.param("echo hello", {}, id="plain"),
    pytest.param("printf 'no newline'; printf 'err, no newline' >&2", {}, id="both-streams-unfinished-lines"),
    pytest.param(r"printf 'a\r\nb\rc\n'", {}, id="line-ends"),
    pytest.param(r"printf 'caf\303'; sleep 0.2; printf '\251 split\n'", {}, id="character-split-across-reads"),
    pytest.param("echo out; echo err >&2; exit 3", {}, id="exit-3-with-output"),
    pytest.param("exit 2", {}, id="exit-2-silent"),
    pytest.param("python3 -c 'print(\"x\" * 300000)'", {"_raw_output": True}, id="past-the-result-ceiling"),
    pytest.param("python3 -c 'print(\"x\" * 100000)'", {}, id="compacted-for-a-model"),
    pytest.param(r"printf 'ok\377bad\n'", {}, id="not-text-on-stdout"),
    pytest.param(r"printf 'fine\n'; printf 'caf\303\n' >&2", {}, id="not-text-on-stderr"),
    pytest.param("echo progress; echo warn >&2; echo '{\"a\": 1}'", {"_raw_output": True}, id="json-last"),
    pytest.param("(sleep 0.4; echo late) & echo now", {}, id="background-child-holds-the-pipe"),
    pytest.param("exec >&- 2>&-; sleep 0.3; exit 4", {}, id="closes-its-pipes-then-exits"),
]


@pytest.mark.parametrize(("command", "params"), PARITY)
def test_the_result_is_what_it_was_without_a_sink(command, params):
    pieces: list[tuple[str, bytes]] = []
    plain = _run(command, **params)
    streamed = _run(command, sink=lambda s, d: pieces.append((s, d)), **params)
    _same(plain, streamed)


def test_output_reaches_the_sink_while_the_command_runs():
    seen: list[tuple[float, str, bytes]] = []
    t0 = time.monotonic()
    r = _run("echo one; sleep 1; echo two", sink=lambda s, d: seen.append((time.monotonic() - t0, s, d)))
    ended = time.monotonic() - t0
    assert r.success and r.result == "one\ntwo\n"
    when, stream, data = seen[0]
    assert (stream, data) == ("stdout", b"one\n")
    assert ended - when >= 0.8, "the first line was only handed over when the command ended"


def test_pieces_are_handed_over_as_written_mid_line_and_mid_character():
    pieces: list[bytes] = []
    r = _run(r"printf 'abc'; sleep 0.3; printf 'def\n\303'; sleep 0.3; printf '\251\n'",
             sink=lambda s, d: pieces.append(d))
    assert r.result == "abcdef\né\n"
    assert pieces[0] == b"abc"
    assert b"".join(pieces) == "abcdef\né\n".encode()
    assert any(p.endswith(b"\xc3") for p in pieces), "the character did not arrive in two reads"


def test_both_pipes_are_read_as_they_fill():
    """A megabyte to stderr before a byte to stdout: a reader of one pipe at a time would hang."""
    got = {"stdout": 0, "stderr": 0}

    def count(stream: str, data: bytes) -> None:
        got[stream] += len(data)

    r = _run("python3 -c 'import sys; sys.stderr.write(\"e\" * 1000000); sys.stdout.write(\"o\" * 1000000)'",
             sink=count, timeout=30, _raw_output=True)
    assert r.success
    assert got == {"stdout": 1_000_000, "stderr": 1_000_000}


def test_a_timeout_still_hands_over_what_was_printed_and_kills_everything(tmp_path):
    mark = tmp_path / "survived"
    pieces: list[tuple[str, bytes]] = []
    r = _run(f"echo before; echo trouble >&2; (sleep 2; touch {mark}) & sleep 10",
             sink=lambda s, d: pieces.append((s, d)), timeout=1)
    assert (r.success, r.result, r.error) == (False, "", _timeout_error(1))
    assert r.metadata == {"stopped": "timeout"}
    assert sorted(pieces) == [("stderr", b"trouble\n"), ("stdout", b"before\n")]
    time.sleep(2.5)
    assert not mark.exists(), "a child of the timed-out command outlived it"


def test_a_cancel_still_hands_over_what_was_printed_and_kills_everything(tmp_path):
    mark = tmp_path / "survived"
    bash = Bash()
    bash.cancel_event = threading.Event()
    started = threading.Event()
    pieces: list[bytes] = []

    def sink(stream: str, data: bytes) -> None:
        pieces.append(data)
        started.set()

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(bash.execute, command=f"echo started; (sleep 2; touch {mark}) & sleep 30",
                             timeout=60, _skip_allowlist=True, _output_sink=sink)
        assert started.wait(5)
        t0 = time.monotonic()
        bash.cancel_event.set()
        r = future.result(timeout=10)
    assert time.monotonic() - t0 < 3
    assert (r.success, r.result, r.error) == (False, "", _CANCELLED_ERROR)
    assert r.metadata == {"stopped": "cancelled"}
    assert b"".join(pieces) == b"started\n"
    time.sleep(2.5)
    assert not mark.exists(), "a child of the cancelled command outlived it"


def test_a_sink_that_fails_never_stops_the_command():
    calls: list[bytes] = []

    def sink(stream: str, data: bytes) -> None:
        calls.append(data)
        raise RuntimeError("database down")

    r = _run("echo one; sleep 0.2; echo two", sink=sink)
    assert r.success and r.result == "one\ntwo\n"
    assert calls == [b"one\n"], "a failing sink is let go after its first failure"


def test_two_commands_at_once_on_one_tool_keep_their_own_output():
    """The sink travels with the call, not on the (shared) tool."""
    bash = Bash()
    got: dict[str, list[bytes]] = {"a": [], "b": []}

    def run(name: str):
        return bash.execute(command=f"for i in 1 2 3; do echo {name}$i; sleep 0.1; done",
                            _skip_allowlist=True, _output_sink=lambda s, d: got[name].append(d))

    with ThreadPoolExecutor(2) as pool:
        ra, rb = pool.map(run, ["a", "b"])
    assert (ra.result, rb.result) == ("a1\na2\na3\n", "b1\nb2\nb3\n")
    assert b"".join(got["a"]) == b"a1\na2\na3\n"
    assert b"".join(got["b"]) == b"b1\nb2\nb3\n"


def test_a_sink_that_is_not_callable_is_no_sink():
    r = _run("echo hi", _output_sink="not a function")
    assert r.success and r.result == "hi\n"


def test_the_text_kept_for_the_result_is_bounded():
    text = _StreamText("utf-8", "strict")
    for _ in range(64):
        text.feed(b"x" * 65536)
    text.feed(b"", final=True)
    assert len(text.text()) == _MAX_OUTPUT_SIZE + 1  # one more than the result keeps: there was more


@pytest.mark.parametrize("data", [
    b"ok\xe2\x82\xacgood\xff end",
    b"ab\xe2\x82x tail",
    b"caf\xc3",
    "naïve ✓".encode() + b"\x80",
])
def test_bad_bytes_are_reported_where_one_decode_would_put_them_wherever_the_reads_split(data):
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        expected = str(e)
    for cut in range(len(data) + 1):
        text = _StreamText("utf-8", "strict")
        text.feed(data[:cut])
        text.feed(data[cut:])
        text.feed(b"", final=True)
        assert text.error == expected, f"split at {cut}"
