"""A script agent's log: what its script prints, saved and shown while it is printed.

The script agent hands :meth:`ScriptLog.write` to the Bash tool as the call's output sink
(tools/bash.py, ``_output_sink``), so each piece the script writes to stdout or stderr arrives
here as soon as it is read. Pieces are kept in order, labelled with their stream and the time they
were read, and saved in batches: a background thread writes rows about every half second, or
sooner once a row's worth is waiting, so the log is saved as it grows rather than when the script
ends. When much is waiting (a script printing as fast as it can), one write saves several rows at
once, so saving keeps up. Each saved row is also sent to whoever is watching the run
(EventRecorder.record_script_log_rows),
which is how the dashboard shows output before the script finishes. The rows themselves, and how
they are read back, are described in observability/script_logs.py.

Writing never makes the script wait: ``write`` only decodes and appends under a lock, and the
saving happens on the thread. What it keeps is bounded twice over:

- the attempt's limit (``log_max_bytes`` in the agent's config, 10,000,000 UTF-8 bytes unless
  set): output past it is counted, not saved, and one note in the log says where it stopped. The
  script is still read to its end, so it never blocks on a full pipe.
- what is waiting to be saved: up to the limit itself, or PENDING_MAX_BYTES when the limit is
  larger. With the default limit nothing can be lost to a slow database; past PENDING_MAX_BYTES
  (a database that is down, with a larger limit) further output is counted as lost, and a note
  says how much once there is room again. Rows that fail to save are retried, never skipped, so
  the rows that are saved have no gaps.

:meth:`close` saves what is left and ends the log with a note saying how the attempt ended
(finished, failed with its exit code, timed out, cancelled). That note is the last entry of the
last row, so a log without one is visibly incomplete.

The final result of the script (its output and JSON hand-off) is built by the Bash tool as before
and never passes through here.
"""

from __future__ import annotations

import codecs
import io
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from temper_ai.shared.clock import utcnow

logger = logging.getLogger(__name__)

#: The default limit on one attempt's saved output, in UTF-8 bytes (``log_max_bytes``).
DEFAULT_LOG_MAX_BYTES = 10_000_000
#: How often waiting output is saved while it trickles in.
FLUSH_INTERVAL_S = 0.5
#: Output text per saved row, about (a row always takes at least one entry).
ROW_MAX_BYTES = 64 * 1024
#: Characters in one entry. Pieces of one stream read within MERGE_WINDOW_S of an entry's first
#: are added to it, so a chatty script does not make an entry (and a timestamp) per read.
ENTRY_MAX_CHARS = 8192
MERGE_WINDOW_S = 0.1
#: Output waiting to be saved, at most, when the attempt's limit is larger than this; past it,
#: output is counted as lost (see the module doc).
PENDING_MAX_BYTES = 16 * 1024 * 1024
#: Rows saved by one write, at most (about a megabyte of output).
BATCH_MAX_ROWS = 16
#: How long :meth:`ScriptLog.close` waits for the rest of the log to be saved.
CLOSE_WAIT_S = 15.0
#: The longest pause between tries at saving a row that failed.
RETRY_MAX_DELAY_S = 5.0

STREAMS = ("stdout", "stderr")

#: ``writer(rows)`` saves rows, ``[(seq, data), ...]`` in order, and sends them on; raises when
#: they were not all saved (they are then written again, so saving one twice must be harmless).
Writer = Callable[[list[tuple[int, dict[str, Any]]]], None]


class ScriptLog:
    """One script attempt's log. Thread-safe: written by the Bash tool, closed by the agent."""

    def __init__(
        self,
        attempt_id: str,
        writer: Writer,
        *,
        limit_bytes: int = DEFAULT_LOG_MAX_BYTES,
        flush_interval: float = FLUSH_INTERVAL_S,
        close_wait: float = CLOSE_WAIT_S,
    ) -> None:
        self.attempt_id = attempt_id
        self._writer = writer
        self._limit = max(0, int(limit_bytes))
        self._pending_max = max(2 * ROW_MAX_BYTES, min(self._limit, PENDING_MAX_BYTES))
        self._flush_interval = flush_interval
        self._close_wait = close_wait
        self._cond = threading.Condition()
        self._decoders = {stream: _decoder() for stream in STREAMS}
        self._pending: deque[_Entry] = deque()
        self._pending_bytes = 0
        self._accepted = 0  # output bytes taken in for saving, at most the limit
        self._dropped = 0  # bytes printed after the limit was reached
        self._lost = 0  # bytes that could not be saved for any other reason
        self._lost_unnoted = 0  # ... of which no note in the log has told yet
        self._truncated = False
        self._rowed_bytes = 0  # output bytes in the rows built so far
        self._rowed_truncated = False
        self._seq = 0  # the last row built
        self._saved_seq = 0  # the last row saved
        self._unsaved: list[tuple[int, dict[str, Any]]] | None = None
        self._failures = 0
        self._closing = False
        self._abandoned = False
        self._finished = False  # the row with the end note is saved
        self._thread = threading.Thread(
            target=self._run, name=f"script-log-{attempt_id[:8]}", daemon=True,
        )
        self._thread.start()

    # ------------------------------------------------------------------ the Bash tool's side

    def write(self, stream: str, data: bytes) -> None:
        """Take one piece of output as it was read: never blocks on saving, never raises."""
        if not data:
            return
        with self._cond:
            decoder = self._decoders.get(stream)
            if self._closing or decoder is None:
                return
            text = decoder.decode(data)
            if text:
                self._take(stream, text, len(data))
            if self._pending_bytes >= ROW_MAX_BYTES:
                self._cond.notify()

    __call__ = write

    # ------------------------------------------------------------------ the agent's side

    def close(self, outcome: str, *, exit_code: int | None = None, detail: str | None = None) -> bool:
        """End the log: save what is left, then a note on how the attempt ended.

        ``outcome`` is "completed", "failed", "timed_out" or "cancelled". Waits up to
        ``close_wait`` seconds for the saving, and says whether all of it, end note included, was
        saved. Output written after this is ignored.
        """
        with self._cond:
            if self._closing:
                return self._finished
            for stream, decoder in self._decoders.items():
                rest = decoder.decode(b"", final=True)  # a held-back "\r", or half a character
                if rest:
                    self._take(stream, rest, len(rest.encode("utf-8")))
            self._note_lost()
            end: dict[str, Any] = {"outcome": outcome}
            if exit_code is not None:
                end["exit_code"] = exit_code
            self._note("end", _end_text(outcome, exit_code, detail, self._dropped), end)
            self._closing = True
            self._cond.notify_all()
        self._thread.join(self._close_wait)
        if self._thread.is_alive():
            with self._cond:
                self._abandoned = True
                self._cond.notify_all()
            logger.warning(
                "Script log %s: the rest of the log could not be saved within %ss; it ends at row %d "
                "without its end note", self.attempt_id, self._close_wait, self._saved_seq,
            )
            return False
        return self._finished

    def summary(self) -> dict[str, Any]:
        """What was saved, for the agent's completion event (never its output or hand-off)."""
        with self._cond:
            return {
                "rows": self._saved_seq,
                "saved_bytes": self._accepted,
                "dropped_bytes": self._dropped,
                "lost_bytes": self._lost,
                "limit": self._limit,
                "truncated": self._truncated,
                "complete": self._finished,
            }

    # ------------------------------------------------------------------ taking output in

    def _take(self, stream: str, text: str, raw_bytes: int) -> None:
        if self._truncated:
            self._dropped += raw_bytes
            return
        size = len(text.encode("utf-8"))
        room = self._limit - self._accepted
        # Only what fits under the limit needs room to wait in, so with the limit at or under
        # PENDING_MAX_BYTES this never loses anything: the limit cuts the piece first.
        if self._pending_bytes + min(size, room) > self._pending_max:
            self._lost += size
            self._lost_unnoted += size
            return
        self._note_lost()
        if size <= room:
            self._append(stream, text, size)
            self._accepted += size
            return
        head = text.encode("utf-8")[:room].decode("utf-8", "ignore")  # whole characters only
        head_size = len(head.encode("utf-8"))
        if head:
            self._append(stream, head, head_size)
        self._accepted += head_size
        self._dropped += size - head_size
        self._truncated = True
        self._note("truncated", (
            f"[log limit reached: {self._limit:,} bytes of output saved for this attempt. "
            "Later output is not saved; the script keeps running.]"
        ))

    def _append(self, stream: str, text: str, size: int) -> None:
        now = time.monotonic()
        tail = self._pending[-1] if self._pending else None
        if (tail is not None and tail.stream == stream and tail.extra is None
                and now - tail.started < MERGE_WINDOW_S
                and len(tail.text) + len(text) <= ENTRY_MAX_CHARS):
            tail.text += text
            tail.size += size
        elif len(text) <= ENTRY_MAX_CHARS:
            self._pending.append(_Entry(stream, text, size, now))
        else:
            for i in range(0, len(text), ENTRY_MAX_CHARS):
                piece = text[i:i + ENTRY_MAX_CHARS]
                self._pending.append(_Entry(stream, piece, len(piece.encode("utf-8")), now))
        self._pending_bytes += size

    def _note(self, kind: str, text: str, extra: dict[str, Any] | None = None) -> None:
        self._pending.append(_Entry("temper", text, 0, time.monotonic(), {"kind": kind, **(extra or {})}))

    def _note_lost(self) -> None:
        if self._lost_unnoted:
            self._note("lost", (
                f"[{self._lost_unnoted:,} bytes of output could not be saved: saving the log fell behind]"
            ), {"lost_bytes": self._lost_unnoted})
            self._lost_unnoted = 0

    # ------------------------------------------------------------------ saving

    def _run(self) -> None:
        """The saving thread: rows in order, a batch at a time, each batch retried until saved."""
        delay = self._flush_interval
        while True:
            with self._cond:
                if self._unsaved is None:
                    if not self._closing and self._pending_bytes < ROW_MAX_BYTES:
                        self._cond.wait(delay)
                    if not self._pending:
                        if self._closing or self._abandoned:
                            return
                        continue
                    batch = [self._build_row()]
                    while self._pending and len(batch) < BATCH_MAX_ROWS:
                        batch.append(self._build_row())
                    self._unsaved = batch
                elif self._failures:
                    self._cond.wait(delay)  # before trying the failed rows again
                if self._abandoned:
                    return
                rows = self._unsaved
            first, last = rows[0][0], rows[-1][0]
            try:
                self._writer(rows)
            except Exception as exc:  # noqa: BLE001 - retried; the script is never held up by it
                self._failures += 1
                delay = min(RETRY_MAX_DELAY_S, self._flush_interval * 2 ** self._failures)
                if self._failures == 1 or self._failures % 20 == 0:
                    logger.warning(
                        "Script log %s: rows %d-%d not saved (%s: %s); trying again in %.1fs (failure %d)",
                        self.attempt_id, first, last, type(exc).__name__, exc, delay, self._failures,
                    )
                continue
            with self._cond:
                if self._failures:
                    logger.info("Script log %s: rows %d-%d saved after %d failure(s)",
                                self.attempt_id, first, last, self._failures)
                self._failures = 0
                delay = self._flush_interval
                self._unsaved = None
                self._saved_seq = last
                if "end" in rows[-1][1]:
                    self._finished = True
                    return

    def _build_row(self) -> tuple[int, dict[str, Any]]:
        entries: list[_Entry] = []
        size = 0
        while self._pending:
            entry = self._pending[0]
            if entries and size + entry.size > ROW_MAX_BYTES:
                break
            self._pending.popleft()
            entries.append(entry)
            size += entry.size
        self._pending_bytes -= size
        self._seq += 1
        self._rowed_bytes += size
        end = None
        for entry in entries:
            extra = entry.extra or {}
            kind = extra.get("kind")
            if kind == "truncated":
                self._rowed_truncated = True
            elif kind == "end":
                end = {k: v for k, v in extra.items() if k != "kind"}
        data: dict[str, Any] = {
            "attempt_id": self.attempt_id,
            "seq": self._seq,
            "entries": [entry.as_dict() for entry in entries],
            "bytes": size,
            "saved_bytes": self._rowed_bytes,
            "dropped_bytes": self._dropped,
            "lost_bytes": self._lost,
            "limit": self._limit,
            "truncated": self._rowed_truncated,
        }
        if end is not None:
            data["end"] = end
        return self._seq, data


class _Entry:
    """A run of one stream's output (or a note), with the time its first piece was read."""

    __slots__ = ("extra", "size", "started", "stream", "t", "text")

    def __init__(self, stream: str, text: str, size: int, started: float,
                 extra: dict[str, Any] | None = None) -> None:
        self.stream = stream
        self.text = text
        self.size = size
        self.started = started
        self.t = utcnow().isoformat(timespec="milliseconds")
        self.extra = extra

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"stream": self.stream, "t": self.t, "text": self.text}
        if self.extra:
            out.update(self.extra)
        return out


def _decoder() -> io.IncrementalNewlineDecoder:
    """UTF-8, a character split across two reads put back together, a bad byte shown as U+FFFD,
    and line ends as the final result has them (``\\r\\n`` and ``\\r`` become ``\\n``)."""
    return io.IncrementalNewlineDecoder(codecs.getincrementaldecoder("utf-8")("replace"), translate=True)


def _end_text(outcome: str, exit_code: int | None, detail: str | None, dropped: int) -> str:
    if outcome == "completed":
        text = "finished: exit code 0"
    elif outcome == "timed_out":
        text = f"timed out{f' {detail}' if detail else ''}: stopped, with everything it started"
    elif outcome == "cancelled":
        text = "cancelled: the run was stopped"
    elif exit_code is not None:
        text = f"failed: exit code {exit_code}"
    else:
        text = f"failed: {(detail or 'error').strip()[:300]}"
    if dropped:
        text += f". {dropped:,} bytes printed after the log limit were not saved"
    return f"[{text}]"


def log_limit(config: dict[str, Any]) -> int:
    """The agent's ``log_max_bytes``, or the default; an invalid value raises ValueError."""
    raw = config.get("log_max_bytes", DEFAULT_LOG_MAX_BYTES)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError(f"log_max_bytes must be a whole number of bytes, 0 or more (got {raw!r})")
    return raw
