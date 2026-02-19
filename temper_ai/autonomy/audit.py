"""Audit logger for tracking auto-applied configuration changes."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field

from temper_ai.storage.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)

AUDIT_DIR = ".meta-autonomous"
AUDIT_FILE = "audit_log.jsonl"
DEFAULT_ENTRY_LIMIT = 50


class AuditEntry(BaseModel):
    """A single auditable change record."""

    id: str
    timestamp: datetime = Field(default_factory=utcnow)
    action_type: str  # "learning_recommendation" | "goal_application"
    source_id: str  # recommendation or goal ID
    config_path: str
    field_path: str
    old_value: str
    new_value: str
    applied_by: str = "autonomous_loop"


class AuditLogger:
    """Append-only JSONL logger for auto-applied changes.

    Persists entries to ``.meta-autonomous/audit_log.jsonl`` so that
    every autonomous configuration change is traceable.
    """

    def __init__(self, base_dir: str = AUDIT_DIR) -> None:
        self._dir = Path(base_dir)
        self._path = self._dir / AUDIT_FILE

    def log(self, entry: AuditEntry) -> None:
        """Append an audit entry to the JSONL file."""
        self._dir.mkdir(parents=True, exist_ok=True)
        line = entry.model_dump_json() + "\n"
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(line)
        logger.info(
            "Audit: %s applied %s → %s (%s)",
            entry.action_type,
            entry.field_path,
            entry.new_value,
            entry.source_id,
        )

    def get_entries(self, limit: int = DEFAULT_ENTRY_LIMIT) -> List[AuditEntry]:
        """Return the most recent *limit* entries (newest first)."""
        entries = self._read_all()
        entries.reverse()
        return entries[:limit]

    def get_entries_by_source(self, source_id: str) -> List[AuditEntry]:
        """Return all entries associated with a given source ID."""
        return [e for e in self._read_all() if e.source_id == source_id]

    def _read_all(self) -> List[AuditEntry]:
        """Read every entry from the JSONL file."""
        if not self._path.exists():
            return []
        entries: List[AuditEntry] = []
        with open(self._path, encoding="utf-8") as fh:
            for line_number, raw in enumerate(fh, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    entries.append(AuditEntry(**json.loads(stripped)))
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.warning(
                        "Skipping malformed audit entry on line %d: %s",
                        line_number,
                        exc,
                    )
        return entries
