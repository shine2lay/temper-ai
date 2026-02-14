"""Event output routing for CLI: write observability events to stderr/stdout/file.

Supports text, json, and jsonl output formats.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Optional


class EventOutputHandler:
    """Routes ObservabilityEvent instances to a configurable output stream.

    Args:
        mode: "stderr", "stdout", or "file".
        fmt: "text", "json", or "jsonl".
        run_id: Optional run ID (used for file output path).
    """

    def __init__(
        self,
        mode: str = "stderr",
        fmt: str = "text",
        run_id: Optional[str] = None,
    ) -> None:
        self.mode = mode
        self.fmt = fmt
        self.run_id = run_id
        self._file_handle: Optional[IO[str]] = None

        if mode == "file":
            out_dir = Path(".meta-autonomous") / "runs" / (run_id or "unknown")
            out_dir.mkdir(parents=True, exist_ok=True)
            self._file_path = out_dir / "events.jsonl"
            self._file_handle = open(self._file_path, "a", encoding="utf-8")

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def handle_event(self, event: Any) -> None:
        """Format and write a single event."""
        line = self._format(event)
        self._write(line)

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _format(self, event: Any) -> str:
        if self.fmt in ("json", "jsonl"):
            return self._format_json(event)
        return self._format_text(event)

    @staticmethod
    def _format_json(event: Any) -> str:
        ts = getattr(event, "timestamp", datetime.now(timezone.utc))
        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        payload = {
            "type": getattr(event, "event_type", "unknown"),
            "timestamp": ts_str,
            "workflow_id": getattr(event, "workflow_id", None),
            "stage_id": getattr(event, "stage_id", None),
            "agent_id": getattr(event, "agent_id", None),
            "data": _safe_data(getattr(event, "data", {})),
        }
        return json.dumps(payload, default=str)

    @staticmethod
    def _format_text(event: Any) -> str:
        etype = getattr(event, "event_type", "event")
        ts = getattr(event, "timestamp", datetime.now(timezone.utc))
        if hasattr(ts, "strftime"):
            ts_str = ts.strftime("%H:%M:%S")
        else:
            ts_str = str(ts)

        data = getattr(event, "data", {})
        stage = getattr(event, "stage_id", None) or data.get("stage_name", "")
        agent = getattr(event, "agent_id", None) or data.get("agent_name", "")

        parts = [f"[{ts_str}]", etype]
        if stage:
            parts.append(f"stage={stage}")
        if agent:
            parts.append(f"agent={agent}")
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def _write(self, line: str) -> None:
        target = self._get_target()
        try:
            target.write(line + "\n")
            target.flush()
        except (IOError, OSError):
            pass  # Best-effort output

    def _get_target(self) -> IO[str]:
        if self.mode == "stdout":
            return sys.stdout
        if self.mode == "file" and self._file_handle is not None:
            return self._file_handle
        return sys.stderr

    def close(self) -> None:
        """Close file handle if open."""
        if self._file_handle is not None:
            self._file_handle.close()
            self._file_handle = None


def _safe_data(data: Any) -> Any:
    """Ensure data is JSON-serializable."""
    if isinstance(data, dict):
        return {k: _safe_data(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_safe_data(v) for v in data]
    if isinstance(data, (str, int, float, bool, type(None))):
        return data
    return str(data)
