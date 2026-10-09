"""pi_watch_stop: a box watch's non-PASS record cancels the run (docs/pi-watch-stop.md).

One test, many checks (owner bp-be8d76b9: happy path first, many things in one
test). The reader runs as the real script, in a subprocess, four times: against a
temp records folder, a stub HTTP server standing in for temper's cancel route and
a stub systemctl. No temper, no systemd, no network.
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
        code = {"gone": 404, "down": 503}.get(run, 200)
        reply = json.dumps({"status": "cancelling", "execution_id": run} if code == 200
                           else {"detail": f"answer {code}"}).encode()
        self.send_response(code)
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
    finally:
        server.shutdown()
        server.server_close()
