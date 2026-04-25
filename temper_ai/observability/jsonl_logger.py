"""JsonlNotifier — append every workflow event to a per-run JSONL file.

Why JSONL alongside the DB:
  - Forensic re-analysis: scripts can grep/jq an entire run history
    without standing up Postgres or replaying through a server
  - Persistence outside the DB: log files survive DB resets / migrations
  - Compatibility with existing tooling (the analytics scripts that
    already read raw output files referenced in CLAUDE memory)
  - Cheap: append-only writes, no contention with the main DB writes

Layout (per run):
    {TEMPER_LOG_DIR}/{execution_id}/events.jsonl

File structure:
    line 1: header — {"kind": "header", "execution_id": ..., "workflow_name": ...,
                       "started_at": ..., "runner_version": ..., "hostname": ...,
                       "metadata": {...}}
    line 2..N: events — {"kind": "event", "ts": ..., "event_type": ..., "data": {...}}
    line N+1: footer — {"kind": "footer", "ts": ..., "reason": "cleanup" | ...}

The footer is written by cleanup() so a truncated file (worker died mid-run)
is identifiable: missing footer → run was interrupted.

Resolution order for log_dir: explicit arg → $TEMPER_LOG_DIR → ./data/logs/
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Bumped when the file format changes — analytics readers can branch on this.
RUNNER_VERSION = "1.0"


class JsonlNotifier:
    """Append-only JSONL log of one workflow run's events.

    Thread-safe: notify_event is called from executor threads, cleanup
    from the main thread when the run terminates. Uses a lock around
    the file write rather than an OS-level lock because it's per-run
    (no cross-process contention by design).

    Best-effort: any I/O failure logs once and falls back to no-op so a
    full disk doesn't take down the workflow.
    """

    def __init__(
        self,
        execution_id: str,
        workflow_name: str,
        *,
        log_dir: str | Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._execution_id = execution_id
        self._workflow_name = workflow_name
        self._lock = threading.Lock()
        self._unhealthy = False
        self._closed = False

        self._path = self._resolve_path(log_dir, execution_id)
        self._fp: Any | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Append mode — if a worker is restarted with the same
            # execution_id (resume), we add events instead of clobbering.
            self._fp = self._path.open("a", encoding="utf-8")
            self._write_line({
                "kind": "header",
                "execution_id": execution_id,
                "workflow_name": workflow_name,
                "started_at": _now(),
                "runner_version": RUNNER_VERSION,
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "metadata": metadata or {},
            })
            logger.info("JsonlNotifier writing to %s", self._path)
        except OSError as exc:
            logger.warning(
                "JsonlNotifier init failed for %s (%s) — running degraded",
                self._path, exc,
            )
            self._unhealthy = True
            self._fp = None

    @property
    def path(self) -> Path:
        """Where this run's JSONL is being written. Useful for tests +
        log-shipping integrations."""
        return self._path

    @property
    def enabled(self) -> bool:
        return not self._unhealthy and not self._closed

    # -- EventNotifier protocol ------------------------------------------

    def notify_event(self, execution_id: str, event_type: str, data: dict) -> None:
        """Append an event line. execution_id is included even though the
        whole file is for one run — keeps each line self-describing for
        consumers that might concatenate JSONLs."""
        self._write_line({
            "kind": "event",
            "ts": _now(),
            "execution_id": execution_id,
            "event_type": event_type,
            "data": data,
        })

    def cleanup(self, execution_id: str) -> None:
        """Footer + close. Idempotent — calling twice is a no-op the
        second time so worker `finally` blocks can be defensive."""
        if self._closed:
            return
        self._write_line({
            "kind": "footer",
            "ts": _now(),
            "execution_id": execution_id,
            "reason": "cleanup",
        })
        self._close()

    # -- Internals --------------------------------------------------------

    def _write_line(self, payload: dict[str, Any]) -> None:
        if not self.enabled or self._fp is None:
            return
        try:
            line = json.dumps(payload, default=str)
            with self._lock:
                self._fp.write(line)
                self._fp.write("\n")
                self._fp.flush()  # crash-safe: every event hits disk before next
        except (OSError, TypeError, ValueError) as exc:
            # ValueError covers writes against a closed file handle
            # (Python raises ValueError, not OSError, in that case).
            self._mark_unhealthy(exc)

    def _close(self) -> None:
        with self._lock:
            if self._fp is not None:
                try:
                    self._fp.close()
                except OSError:
                    pass
            self._fp = None
            self._closed = True

    def _mark_unhealthy(self, exc: Exception) -> None:
        if not self._unhealthy:
            logger.warning(
                "JsonlNotifier write failed for %s (%s) — degrading to no-op",
                self._path, exc,
            )
            self._unhealthy = True

    @staticmethod
    def _resolve_path(log_dir: str | Path | None, execution_id: str) -> Path:
        if log_dir is None:
            log_dir = os.environ.get("TEMPER_LOG_DIR")
        if log_dir is None:
            # Default: under data/ alongside the sqlite DB
            log_dir = Path("data") / "logs"
        return Path(log_dir) / execution_id / "events.jsonl"


def _now() -> str:
    return datetime.now(UTC).isoformat()
