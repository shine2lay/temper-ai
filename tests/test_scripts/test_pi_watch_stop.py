"""pi_watch_stop: a box watch's non-PASS record cancels the run (docs/pi-watch-stop.md).

One test, many checks (owner bp-be8d76b9: happy path first, many things in one
test). The reader runs as the real script against temp records, a loopback HTTP
stub and a stub systemctl: the combined happy path first, then regressions for
reproduced unsafe inputs. No Temper copy, real systemd or outside network.
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

    def do_GET(self) -> None:
        self.calls.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": {}})
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

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
    key_file = tmp_path / "watch-stop.key"
    key_file.write_text(KEY + "\n", encoding="utf-8")
    os.chmod(key_file, 0o600)
    state = tmp_path / "unit-state"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(f"#!/bin/sh\ncat '{state}'\n", encoding="utf-8")
    os.chmod(systemctl, 0o755)
    since = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)

    def start(folder: Path, run: str, log: Path, *extra: str) -> subprocess.Popen[bytes]:
        folder.mkdir(parents=True, exist_ok=True)
        with log.open("wb") as out:
            return subprocess.Popen(
                [sys.executable, str(SCRIPT), "--records", str(folder), "--run", run,
                 "--since", _stamp(since), "--key-file", str(key_file),
                 "--server", f"http://127.0.0.1:{server.server_port}",
                 "--systemctl", str(systemctl), *FAST, *extra],
                stdout=out, stderr=subprocess.STDOUT)

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

        # 2. Replay: a COULD NOT CHECK written after --since but before the reader
        #    started (it was down) is acted on as soon as it starts.
        calls.clear()
        replay = tmp_path / "replay"
        _record(replay, "pins.json", since + timedelta(seconds=30), "COULD NOT CHECK",
                kind="pins", subject="pins", reasons=["pins read failed twice"])
        code, text = finish(start(replay, "run-2", tmp_path / "replay.log"), tmp_path / "replay.log")
        assert code == 0, text
        assert [c["body"]["reason"] for c in calls] == [
            "Security watch COULD NOT CHECK: pins: pins read failed twice"]

        # 3. A record that doesn't parse is read again, still doesn't parse, and counts
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

        # 4. The watch's own unit stuck other than active past the grace counts as
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
    finally:
        server.shutdown()
        server.server_close()
