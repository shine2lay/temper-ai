"""The provider stand-in of the Pi rehearsal: a local TLS server that plays the scripted members.

It runs beside the rig's pi-worker, in pi-worker's network namespace, on 127.0.0.1 at the box
config's ``rehearsal.upstream_port``: the Pi lane's egress relay connects there instead of the
provider (temper_ai/pi_agent/box.py, ``_connect_upstream`` in rehearsal mode). The member's
Pi runtime trusts it through the rehearsal CA (``/box-ca/ca.pem``, ``NODE_EXTRA_CA_CERTS``).

It answers ``POST /v1/messages`` with an Anthropic event stream (one tool call or a closing
text per call, from scenario.py) and refuses everything else with 404, logging the path as
``unexpected`` (no usage or token call may reach a provider in a rehearsal). The log
(``STANDIN_LOG``, JSON lines) holds metadata only: never a prompt, message body or token.

It is also the tripwire for a provider call that skips the relay: the rig maps every provider
name to 127.0.0.1 in pi-worker, so a direct call lands on 127.0.0.1:443 or :80 here. Each
connection there is logged as ``tripwire`` (port only) and closed, unread; a rehearsal run
passes only with none.

Standard library only, so it runs in the rig's worker image unchanged::

    python standin.py   # settings from STANDIN_* environment variables, see main()
"""
from __future__ import annotations

import json
import os
import secrets
import ssl
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenario  # noqa: E402 - beside this file, imported by path in the rig's image

PING_EVERY_S = 5.0


class Settings:
    def __init__(self, env: dict[str, str]):
        self.port = int(env["STANDIN_PORT"])
        self.cert = env["STANDIN_CERT"]
        self.key = env["STANDIN_KEY"]
        self.log = Path(env["STANDIN_LOG"])
        self.gates = Path(env["STANDIN_GATES"])
        self.pace_s = float(env.get("STANDIN_PACE_S", "1.5"))
        self.hold_max_s = float(env.get("STANDIN_HOLD_MAX_S", "240"))
        self.rules = scenario.SCENARIOS[env.get("STANDIN_SCENARIO", "normal")]


class Log:
    def __init__(self, path: Path):
        self.path, self.lock, self.seq = path, threading.Lock(), 0

    def write(self, **row: Any) -> int:
        with self.lock:
            self.seq += 1
            row = {"seq": self.seq, "at": time.time(), **row}
            with self.path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(row, sort_keys=True) + "\n")
            return self.seq


def decode_body(raw: bytes, encoding: str) -> bytes:
    encoding = (encoding or "identity").strip().lower()
    if encoding in ("", "identity"):
        return raw
    if encoding in ("gzip", "deflate"):
        return zlib.decompress(raw, 47)
    if encoding == "zstd":
        import zstandard  # type: ignore[import-not-found]

        return zstandard.ZstdDecompressor().decompressobj().decompress(raw)
    raise ValueError(f"unknown content encoding {encoding[:20]!r}")


def frames(answer: scenario.Answer, model: str, tool_id: str) -> tuple[list, list]:
    """The stream as (head, rest): ``head`` is sent at once, ``rest`` after any hold."""
    start = {"type": "message_start", "message": {
        "id": "msg_" + secrets.token_hex(8), "type": "message", "role": "assistant",
        "model": model, "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 40, "output_tokens": 1, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0}}}
    step = answer.action
    if step.tool:
        rest = [("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "tool_use", "id": tool_id,
                                                           "name": step.tool, "input": {}}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {
                    "type": "input_json_delta", "partial_json": json.dumps(step.input)}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {
                    "stop_reason": "tool_use", "stop_sequence": None},
                    "usage": {"output_tokens": 3}})]
    else:
        rest = [("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": step.text}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {
                    "stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 3}})]
    rest.append(("message_stop", {"type": "message_stop"}))
    return [("message_start", start)], rest


def make_handler(settings: Settings, log: Log) -> type[BaseHTTPRequestHandler]:
    tool_prefix = "toolu_" + secrets.token_hex(3) + "_"
    counter = iter(range(1, 10**9))
    counter_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # the JSON log is the only log
            return

        def _refuse(self, status: int = 404) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            log.write(event="unexpected", method=self.command, path=self.path.split("?")[0][:80])
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            self._refuse()

        do_HEAD = do_PUT = do_DELETE = do_PATCH = do_GET  # noqa: N815

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?")[0] != "/v1/messages":
                self._refuse()
                return
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                request = json.loads(decode_body(raw, self.headers.get("Content-Encoding", "")))
                turn = scenario.read_turn(request)
            except (ValueError, scenario.NotATurn) as exc:
                log.write(event="unreadable", why=type(exc).__name__)
                self.send_response(400)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            answer = scenario.answer(turn, settings.rules)
            with counter_lock:
                tool_id = tool_prefix + str(next(counter))
            time.sleep(settings.pace_s)
            head, rest = frames(answer, turn.model, tool_id)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for event in head:
                self._frame(*event)
            held = self._hold(answer.action.hold) if answer.action.hold else None
            for event in rest:
                self._frame(*event)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            log.write(event="answer", member=turn.member, leader=turn.leader,
                      roster=list(turn.roster), kinds=sorted(turn.kinds()), rule=answer.rule,
                      step=answer.step, tool=answer.action.tool or None,
                      tool_id=tool_id if answer.action.tool else None,
                      text=not answer.action.tool, flag=answer.flag or None,
                      model=turn.model, thinking=turn.thinking, held_s=held,
                      hold_gate=answer.action.hold or None)

        def _frame(self, name: str, data: dict) -> None:
            chunk = f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.flush()

        def _hold(self, gate: str) -> dict:
            """Keep the stream alive with pings until the gate file exists (or the cap)."""
            began = last_ping = time.monotonic()
            path = settings.gates / gate
            while not path.exists() and time.monotonic() - began < settings.hold_max_s:
                time.sleep(0.5)
                if time.monotonic() - last_ping >= PING_EVERY_S:
                    self._frame("ping", {"type": "ping"})
                    last_ping = time.monotonic()
            return {"seconds": round(time.monotonic() - began, 1), "released": path.exists()}

    return Handler


class TLSServer(ThreadingHTTPServer):
    """TLS per connection, in the connection's own thread: a client that never finishes its
    handshake holds only its own thread."""
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type, context: ssl.SSLContext):
        super().__init__(address, handler)
        self.context = context

    def finish_request(self, request: Any, client_address: Any) -> None:
        try:
            request.settimeout(30)
            tls = self.context.wrap_socket(request, server_side=True)
            tls.settimeout(None)
        except (ssl.SSLError, OSError):
            return
        self.RequestHandlerClass(tls, client_address, self)


TRIPWIRE_PORTS = (443, 80)


def tripwire(port: int, log: Log) -> threading.Thread | None:
    """Log and close every connection to 127.0.0.1:<port>; None if the port can't be bound
    (logged as ``tripwire_unavailable``, so the record says the wire wasn't there)."""
    import socket

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", port))
        listener.listen(16)
    except OSError as exc:
        listener.close()
        log.write(event="tripwire_unavailable", port=port, error=type(exc).__name__)
        return None

    def watch() -> None:
        while True:
            conn, _ = listener.accept()
            log.write(event="tripwire", port=port)
            conn.close()

    thread = threading.Thread(target=watch, name=f"tripwire-{port}", daemon=True)
    thread.start()
    log.write(event="tripwire_armed", port=port)
    return thread


def main(env: dict[str, str] | None = None) -> None:
    settings = Settings(dict(os.environ if env is None else env))
    settings.log.parent.mkdir(parents=True, exist_ok=True)
    log = Log(settings.log)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(settings.cert, settings.key)
    server = TLSServer(("127.0.0.1", settings.port), make_handler(settings, log), context)
    for port in TRIPWIRE_PORTS:
        tripwire(port, log)
    log.write(event="listening", port=settings.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
