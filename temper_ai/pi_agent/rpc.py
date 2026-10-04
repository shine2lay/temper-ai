"""Pi's RPC transport: one JSON object per line over a child process's stdin/stdout.

Ported from the P0 proof harness (contract v2) with the L1 worker's bounded stderr buffer.
The child runs in its own process group (``start_new_session``), so closing a worker can
always signal everything it started. Only static error codes leave this module -- never text
captured from the child.
"""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import threading
import time
from collections import Counter
from collections.abc import Callable

LINE_LIMIT = 4 * 1024 * 1024
QUEUE_LIMIT = 4096
STDERR_KEEP = 256 * 1024


class RpcError(Exception):
    """A transport failure, named by a static code (``protocol_eof``, ``protocol_deadline``...)."""


class JsonLines:
    """Split a byte stream into JSON objects, one per line (LF; a trailing CR is dropped)."""

    def __init__(self, limit: int = LINE_LIMIT):
        self.buffer = bytearray()
        self.limit = limit
        self.lines = 0

    def feed(self, chunk: bytes) -> list[dict]:
        self.buffer.extend(chunk)
        records = []
        while True:
            end = self.buffer.find(b"\n")
            if end < 0:
                break
            line = bytes(self.buffer[:end])
            del self.buffer[:end + 1]
            if line.endswith(b"\r"):
                line = line[:-1]
            if not line:
                continue
            try:
                value = json.loads(line.decode("utf-8", errors="strict"))
            except (ValueError, UnicodeError):
                raise RpcError("invalid_protocol_line") from None
            if not isinstance(value, dict):
                raise RpcError("protocol_record_not_object")
            self.lines += 1
            records.append(value)
        if len(self.buffer) > self.limit:
            raise RpcError("protocol_line_limit")
        return records

    def finish(self) -> None:
        if self.buffer:
            raise RpcError("incomplete_protocol_line_at_eof")


class Rpc:
    """A child process speaking Pi's RPC protocol.

    ``event_sink`` sees every record in order, on the thread that calls :meth:`next`.
    """

    def __init__(self, argv: list[str], cwd: str, env: dict[str, str],
                 event_sink: Callable[[dict], None]):
        self.process = subprocess.Popen(
            argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, bufsize=0)
        self.event_sink = event_sink
        self.decoder = JsonLines()
        self.queue: queue.Queue[dict] = queue.Queue(maxsize=QUEUE_LIMIT)
        self.pending: dict[str, str] = {}
        self.responses: dict[str, dict] = {}
        self.counts: Counter[str] = Counter()
        self.stderr_buf = bytearray()
        self.stderr_bytes = 0
        self.reader_error: str | None = None
        self.stderr_error: str | None = None
        self.last_cleanup: dict | None = None
        self.eof = threading.Event()
        self.stderr_eof = threading.Event()
        self._seq = 0
        self.threads = [threading.Thread(target=self._stdout, daemon=True),
                        threading.Thread(target=self._stderr, daemon=True)]
        for thread in self.threads:
            thread.start()

    def _stdout(self) -> None:
        try:
            assert self.process.stdout is not None
            while chunk := os.read(self.process.stdout.fileno(), 65536):
                for record in self.decoder.feed(chunk):
                    try:
                        self.queue.put_nowait(record)
                    except queue.Full:
                        raise RpcError("protocol_queue_limit") from None
            self.decoder.finish()
        except RpcError as exc:
            self.reader_error = str(exc)
        except Exception:
            self.reader_error = "stdout_reader_failure"
        finally:
            self.eof.set()

    def _stderr(self) -> None:
        try:
            assert self.process.stderr is not None
            while chunk := os.read(self.process.stderr.fileno(), 65536):
                self.stderr_bytes += len(chunk)
                room = STDERR_KEEP - len(self.stderr_buf)
                if room > 0:
                    self.stderr_buf.extend(chunk[:room])
        except Exception:
            self.stderr_error = "stderr_reader_failure"
        finally:
            self.stderr_eof.set()

    def stderr_summary(self) -> dict:
        """Counts and keyword classes only: stderr text never leaves memory."""
        text = bytes(self.stderr_buf).decode("utf-8", "replace")
        lines = [line for line in text.splitlines() if line.strip()]
        return {"bytes": self.stderr_bytes, "lines": len(lines),
                "error_lines": sum(1 for line in lines if re.search(r"error|fail", line, re.I))}

    def send(self, command: str, **fields) -> str:
        self._seq += 1
        request_id = f"t{self._seq}"
        self.pending[request_id] = command
        raw = (json.dumps({"id": request_id, "type": command, **fields}, ensure_ascii=False,
                          separators=(",", ":")) + "\n").encode()
        try:
            assert self.process.stdin is not None
            view = memoryview(raw)
            while view:
                written = os.write(self.process.stdin.fileno(), view)
                view = view[written:]
        except (BrokenPipeError, OSError, ValueError):  # ValueError: stdin already closed
            raise RpcError("command_pipe_closed") from None
        return request_id

    def reply(self, record: dict) -> None:
        """Write a record that is not a command (``extension_ui_response``)."""
        raw = (json.dumps(record, separators=(",", ":")) + "\n").encode()
        try:
            assert self.process.stdin is not None
            os.write(self.process.stdin.fileno(), raw)
        except (BrokenPipeError, OSError, ValueError):
            raise RpcError("command_pipe_closed") from None

    def next(self, deadline: float) -> dict:
        while True:
            if self.reader_error:
                raise RpcError(self.reader_error)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RpcError("protocol_deadline")
            try:
                record = self.queue.get(timeout=min(remaining, 0.1))
            except queue.Empty:
                if self.eof.is_set() and self.queue.empty():
                    raise RpcError("protocol_eof") from None
                continue
            kind = str(record.get("type", "unknown"))
            self.counts[kind] += 1
            if kind == "response":
                rid = record.get("id")
                if rid not in self.pending:
                    raise RpcError("unexpected_or_duplicate_response_id")
                if self.pending.pop(rid) != record.get("command"):
                    raise RpcError("response_command_mismatch")
                self.responses[rid] = record
            self.event_sink(record)
            return record

    def response(self, request_id: str, timeout: float = 60) -> dict:
        deadline = time.monotonic() + timeout
        while request_id not in self.responses:
            self.next(deadline)
        return self.responses[request_id]

    def command(self, command: str, timeout: float = 60, **fields) -> dict:
        return self.response(self.send(command, **fields), timeout)

    def close(self, wait: float = 8.0) -> dict:
        """Close stdin, wait, then signal the whole process group. Idempotent."""
        if self.last_cleanup is not None:
            return self.last_cleanup
        errors: list[str] = []
        escalation: list[str] = []
        code = None
        try:
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()
        except Exception:
            errors.append("stdin_close_failed")
        try:
            code = self.process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            for sig, name in ((signal.SIGTERM, "SIGTERM"), (signal.SIGKILL, "SIGKILL")):
                escalation.append(name)
                try:
                    os.killpg(self.process.pid, sig)
                except ProcessLookupError:
                    pass
                except Exception:
                    errors.append("process_group_signal_failed")
                try:
                    code = self.process.wait(timeout=3)
                    break
                except subprocess.TimeoutExpired:
                    errors.append("process_wait_timeout")
        # Whatever the child started in its group and left behind goes with it.
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
            escalation.append("group_leftovers_killed")
        except ProcessLookupError:
            pass
        except Exception:
            errors.append("process_group_signal_failed")
        for thread in self.threads:
            thread.join(timeout=3)
        for stream in (self.process.stdout, self.process.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:
                errors.append("output_close_failed")
        if self.reader_error:
            errors.append(self.reader_error)
        if self.stderr_error:
            errors.append(self.stderr_error)
        self.last_cleanup = {
            "exit_code": code, "escalation": escalation,
            "reader_threads_stopped": all(not t.is_alive() for t in self.threads),
            "unanswered_commands": len(self.pending), "protocol_lines": self.decoder.lines,
            "events_by_type": dict(self.counts), "stderr": self.stderr_summary(),
            "errors": sorted(set(errors)),
        }
        return self.last_cleanup
