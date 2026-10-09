"""pi_watch_stop: a box watch's non-PASS record cancels the run (docs/pi-watch-stop.md).

One test, many checks (owner bp-be8d76b9: happy path first, many things in one
test). The reader runs as the real script against temp records, a loopback-only
stub of the cancel and box-evidence routes, and a stub systemctl. The combined
happy path comes first; reproduced regressions stay. No Temper copy, real
systemd or outside network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pi_watch_stop.py"
KEY = "watch-stop-test-key-0123456789abcdef"
FAST = ["--poll", "0.05", "--reread", "0.2", "--retry-every", "0.05", "--retry-for", "0.3"]


class _Cancels(BaseHTTPRequestHandler):
    """temper's cancel route, as far as the reader can tell: run "gone" -> 404,
    run "down" -> 503, any other run -> 200. Every call is kept."""

    calls: list[dict[str, Any]] = []
    reads: list[dict[str, Any]] = []
    boxes: list[dict[str, Any]] = []

    def do_GET(self) -> None:
        if self.path.startswith("/api/team/runs/") and self.path.endswith("/boxes"):
            self.reads.append({"path": self.path, "auth": self.headers.get("Authorization")})
            reply = json.dumps({"boxes": self.boxes}).encode()
        else:
            self.calls.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": {}})
            reply = b""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        run = self.path.split("/")[3]
        code = {"gone": 404, "down": 503, "redirect": 302}.get(run, 200)
        reply = json.dumps({"status": "cancelling", "execution_id": run} if code == 200
                           else {"detail": f"answer {code}"}).encode()
        self.send_response(code)
        if code == 302:
            # Different origin and non-cancel path: the bearer must never follow.
            self.send_header("Location", f"http://localhost:{self.server.server_port}/not-cancel")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *_: Any) -> None:
        pass


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(folder: Path, name: str, at: datetime, verdict: str, **fields: Any) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    rec = {"checked_at": _stamp(at), "verdict": verdict, "reasons": [], "notes": [], **fields}
    (folder / name).write_text(json.dumps(rec), encoding="utf-8")


def _snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    """Every file under the folder: (size, mtime_ns). The reader must change none."""
    return {str(p.relative_to(folder)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(folder.rglob("*"))}


def _wait_for(log: Path, text: str, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if text in log.read_text(encoding="utf-8"):
            return
        assert proc.poll() is None, f"reader ended early:\n{log.read_text(encoding='utf-8')}"
        time.sleep(0.02)
    raise AssertionError(f"{text!r} never logged:\n{log.read_text(encoding='utf-8')}")


def test_watch_stop_reader_cancels_on_non_pass_records_only(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Cancels)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    calls = _Cancels.calls
    calls.clear()
    _Cancels.reads.clear()
    _Cancels.boxes.clear()
    key_file = tmp_path / "watch-stop.key"
    key_file.write_text(KEY + "\n", encoding="utf-8")
    os.chmod(key_file, 0o600)
    state = tmp_path / "unit-state"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(f"#!/bin/sh\ncat '{state}'\n", encoding="utf-8")
    os.chmod(systemctl, 0o755)
    since = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)
    processes: list[subprocess.Popen[bytes]] = []

    def start(folder: Path, run: str, log: Path, *extra: str) -> subprocess.Popen[bytes]:
        folder.mkdir(parents=True, exist_ok=True)
        with log.open("wb") as out:
            proc = subprocess.Popen(
                [sys.executable, str(SCRIPT), "--records", str(folder), "--run", run,
                 "--since", _stamp(since), "--key-file", str(key_file),
                 "--server", f"http://127.0.0.1:{server.server_port}",
                 "--systemctl", str(systemctl), *FAST, *extra],
                stdout=out, stderr=subprocess.STDOUT)
        processes.append(proc)
        return proc

    def finish(proc: subprocess.Popen[bytes], log: Path) -> tuple[int, str]:
        try:
            code = proc.wait(timeout=20)
        finally:
            proc.kill()
        text = log.read_text(encoding="utf-8")
        assert KEY not in text, "the key must never be printed"
        return code, text

    try:
        # 1. Live: the folder already holds an old STOP (before --since), a PASS with
        #    notes only, a dot-file and a subfolder. None of them acts. Then a STOP is
        #    written while the reader runs: exactly one cancel, with the key and the reason.
        state.write_text("active\n", encoding="utf-8")
        live = tmp_path / "live"
        _record(live, "old-stop.json", since - timedelta(hours=1), "STOP",
                kind="box", subject="temper-pi-old", reasons=["from the first trial"])
        _record(live, "pass-notes.json", since + timedelta(seconds=1), "PASS", kind="box",
                subject="temper-pi-a", notes=["another temper run box seen (--quiet-notes)"])
        _record(live, ".writing.json", since + timedelta(seconds=2), "STOP", reasons=["half written"])
        _record(live / "kept", "nested.json", since + timedelta(seconds=2), "STOP", reasons=["subfolder"])
        log1 = tmp_path / "live.log"
        proc = start(live, "run-1", log1)
        _wait_for(log1, "read pass-notes.json: box temper-pi-a: PASS", proc)
        assert calls == []
        _record(live, "live-stop.json", datetime.now(UTC), "STOP",
                box={"name": "temper-pi-b", "pi_run": "run-1"},
                reasons=["mount rw /w is another member's", "second reason"])
        before = _snapshot(live)
        code, text = finish(proc, log1)
        assert code == 0, text
        assert calls == [{"path": "/api/runs/run-1/cancel", "auth": f"Bearer {KEY}",
                          "body": {"reason": "Security watch STOP: box temper-pi-b: "
                                             "mount rw /w is another member's"}}]
        assert "read old-stop.json: box temper-pi-old: STOP" in text and "older than --since" in text
        assert ".writing.json" not in text and "nested.json" not in text
        assert _snapshot(live) == before, "the reader must not touch the records folder"

        # 2. A reboot gap with every overlapping ledger box PASS carries on. The
        #    continuity file sorts before its evidence: the whole batch must be read
        #    before judging it. Old/future turns and a final never-created receipt
        #    need no evidence; an ended turn that overlapped the gap still does.
        calls.clear()
        _Cancels.reads.clear()
        state.write_text("active\n", encoding="utf-8")
        complete = tmp_path / "complete-gap"
        gap_from, gap_to = since + timedelta(seconds=10), since + timedelta(seconds=30)
        _Cancels.boxes[:] = [
            {"box_name": "temper-pi-active", "turn_id": "turn-active",
             "started_at": _stamp(gap_from), "ended_at": None, "created": None},
            {"box_name": "temper-pi-ended", "turn_id": "turn-ended",
             "started_at": _stamp(since), "ended_at": _stamp(gap_to), "created": True},
            {"box_name": "temper-pi-before", "turn_id": "turn-before",
             "started_at": _stamp(since), "ended_at": _stamp(gap_from - timedelta(seconds=1))},
            {"box_name": "temper-pi-after", "turn_id": "turn-after",
             "started_at": _stamp(gap_to + timedelta(seconds=1)), "ended_at": None},
            {"box_name": "temper-pi-never", "turn_id": "turn-never",
             "started_at": _stamp(gap_from), "ended_at": _stamp(gap_to), "created": False}]
        _record(complete, "a-continuity.json", gap_to, "COULD NOT CHECK",
                kind="watch", subject="continuity", gap_from=_stamp(gap_from),
                gap_to=_stamp(gap_to), reasons=["Docker events cannot cover the gap"])
        for box in ("temper-pi-active", "temper-pi-ended"):
            _record(complete, f"z-{box}.json", gap_to, "PASS", kind="box", subject=box)
        log5 = tmp_path / "complete-gap.log"
        proc = start(complete, "run-5", log5)
        _wait_for(log5, "all gap boxes have PASS records; carrying on", proc)
        assert calls == []
        assert _Cancels.reads == [{"path": "/api/team/runs/run-5/boxes", "auth": f"Bearer {KEY}"}]
        _record(complete, "later-stop.json", datetime.now(UTC), "STOP",
                kind="box", subject="temper-pi-active", reasons=["a box's STOP still acts"])
        code, text = finish(proc, log5)
        assert code == 0, text
        assert len(calls) == 1 and calls[0]["body"]["reason"] == (
            "Security watch STOP: box temper-pi-active: a box's STOP still acts")

        # 3. Replay: a COULD NOT CHECK written after --since but before the reader
        #    started (it was down) is acted on as soon as it starts.
        calls.clear()
        replay = tmp_path / "replay"
        _record(replay, "pins.json", since + timedelta(seconds=30), "COULD NOT CHECK",
                kind="pins", subject="pins", reasons=["pins read failed twice"])
        code, text = finish(start(replay, "run-2", tmp_path / "replay.log"), tmp_path / "replay.log")
        assert code == 0, text
        assert [c["body"]["reason"] for c in calls] == [
            "Security watch COULD NOT CHECK: pins: pins read failed twice"]

        # 4. A record that doesn't parse is read again, still doesn't parse, and counts
        #    as COULD NOT CHECK. The run is gone (404): logged, exit 3, no retry.
        calls.clear()
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "torn.json").write_text('{"verdict": "PA', encoding="utf-8")
        code, text = finish(start(broken, "gone", tmp_path / "broken.log"), tmp_path / "broken.log")
        assert code == 3, text
        assert "reading it again in 0.2 s" in text and "still doesn't parse" in text
        assert len(calls) == 1 and calls[0]["path"] == "/api/runs/gone/cancel"
        assert calls[0]["body"]["reason"].startswith(
            "Security watch COULD NOT CHECK: record torn.json: record does not parse")
        assert "cancel answered 404" in text

        # 5. The watch's own unit stuck other than active past the grace counts as
        #    COULD NOT CHECK. Here the server keeps failing (503): the reader retries,
        #    then exits 1 so systemd starts it again.
        calls.clear()
        state.write_text("activating\n", encoding="utf-8")
        quiet = tmp_path / "quiet"
        code, text = finish(start(quiet, "down", tmp_path / "quiet.log", "--watch-grace", "0.5"),
                            tmp_path / "quiet.log")
        assert code == 1, text
        assert len(calls) >= 2, text
        assert {c["body"]["reason"] for c in calls} == {
            "Security watch COULD NOT CHECK: watch security-trial-watch: "
            "watch unit activating for over 0.5 s"}
        assert "cancel still failing after 0.3 s" in text

        # Malformed/date-only dates must use fresh mtime, not hide a fresh STOP
        # at an old midnight or crash forever on replay. Surrogates must be safe
        # in the record name, subject, first reason and the actual HTTP body.
        state.write_text("active\n", encoding="utf-8")
        for n, bad_time in enumerate((20261009, "2026-10-09",
                                      "0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00")):
            calls.clear()
            folder = tmp_path / f"date-{n}"
            _record(folder, "stop.json", datetime.now(UTC), "STOP", checked_at=bad_time,
                    kind="box", subject="temper-pi-a", reasons=["fresh stop"])
            log = tmp_path / f"date-{n}.log"
            code, text = finish(start(folder, f"date-{n}", log), log)
            assert code == 0, text
            assert len(calls) == 1 and calls[0]["body"]["reason"].endswith("fresh stop")

        calls.clear()
        unusual = tmp_path / "unusual"
        _record(unusual, os.fsdecode(b"\xff-stop.json"), datetime.now(UTC), "STOP",
                kind="box", subject="temper-pi-\ud800", reasons=["mount \ud800 rw\nforged line"])
        log = tmp_path / "unusual.log"
        code, text = finish(start(unusual, "unusual", log), log)
        assert code == 0, text
        assert len(calls) == 1
        assert calls[0]["body"]["reason"] == (
            r"Security watch STOP: box temper-pi-\ud800: mount \ud800 rw\x0aforged line")
        assert all(line.startswith("20") for line in text.splitlines()), "one physical log line per event"

        # Bounded/deep JSON is re-read once, then COULD NOT CHECK, never a crash.
        for name, raw in (("deep", '{"x":' + "[" * 100 + "0" + "]" * 100 + "}"),
                          ("large", '{"notes":"' + "x" * (1024 * 1024) + '"}')):
            calls.clear()
            folder = tmp_path / name
            folder.mkdir()
            (folder / "bad.json").write_text(raw, encoding="utf-8")
            log = tmp_path / f"{name}.log"
            code, text = finish(start(folder, name, log), log)
            assert code == 0, text
            assert "reading it again" in text and "still doesn't parse" in text
            assert len(calls) == 1 and "COULD NOT CHECK" in calls[0]["body"]["reason"]

        calls.clear()
        state.write_bytes(b"\xff\xfeactive\n")
        log = tmp_path / "bad-unit.log"
        code, text = finish(start(tmp_path / "bad-unit", "bad-unit", log, "--watch-grace", "0.1"), log)
        assert code == 0, text
        assert len(calls) == 1 and "unknown (UnicodeDecodeError)" in calls[0]["body"]["reason"]
        state.write_text("active\n", encoding="utf-8")

        # A redirect is a failed POST, not a successful GET with the bearer key.
        calls.clear()
        folder = tmp_path / "redirect"
        _record(folder, "stop.json", datetime.now(UTC), "STOP", reasons=["stop"])
        log = tmp_path / "redirect.log"
        code, text = finish(start(folder, "redirect", log), log)
        assert code == 1, text
        assert calls and all(c["path"] == "/api/runs/redirect/cancel" for c in calls)
        assert "cancel answered 200" not in text

        # Permanent bad setup returns 2 before any request and never prints key contents.
        for n, raw_key in enumerate(((KEY + "\nsecond-line").encode(), b"\xff", "snowman \u2603".encode())):
            calls.clear()
            key_file.write_bytes(raw_key)
            log = tmp_path / f"key-{n}.log"
            code, text = finish(start(tmp_path / "setup", "setup", log), log)
            assert code == 2 and "contents withheld" in text and not calls, text
        key_file.write_text(KEY + "\n", encoding="utf-8")
        for n, extra in enumerate((("--run", "run with space"), ("--server", "localhost:8420"),
                                   ("--server", "http://localhost:bad"),
                                   ("--since", "0001-01-01T00:00:00+01:00"),
                                   ("--poll", "nan"), ("--watch-grace", "inf"), ("--retry-for", "0"))):
            calls.clear()
            log = tmp_path / f"setup-{n}.log"
            code, text = finish(start(tmp_path / "setup", "setup", log, *extra), log)
            assert code == 2 and not calls, text

        # 6. A gap box without PASS cancels after exactly one re-check. Missing
        #    bounds use --since and checked_at, so a turn ending at --since counts.
        #    An earlier Project's PASS can't excuse it; an unknown receipt can't
        #    excuse it either. No record in either folder was changed by the reader.
        calls.clear()
        _Cancels.reads.clear()
        missing = tmp_path / "missing-gap"
        _Cancels.boxes[:] = [{"box_name": "temper-pi-missing", "turn_id": "turn-missing",
                             "started_at": _stamp(since - timedelta(seconds=1)),
                             "ended_at": _stamp(since), "created": None}]
        _record(missing, "old-pass.json", since - timedelta(seconds=1), "PASS",
                kind="box", subject="temper-pi-missing")
        _record(missing, "continuity.json", gap_to, "COULD NOT CHECK", kind="watch",
                subject="continuity", gap_from="not a time", reasons=["unproven gap"])
        before = _snapshot(missing)
        log6 = tmp_path / "missing-gap.log"
        code, text = finish(start(missing, "run-6", log6, "--continuity-wait", "0.2"), log6)
        assert code == 0, text
        assert "checking again in 0.2 s" in text
        assert _Cancels.reads == [{"path": "/api/team/runs/run-6/boxes", "auth": f"Bearer {KEY}"}] * 2
        assert calls == [{"path": "/api/runs/run-6/cancel", "auth": f"Bearer {KEY}",
                          "body": {"reason": "Security watch COULD NOT CHECK: watch continuity: "
                                             "temper-pi-missing has no PASS record"}}]
        assert _snapshot(missing) == before
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        server.shutdown()
        server.server_close()
