"""Tests for the AuditLogger and AuditEntry."""

import json
from pathlib import Path

from temper_ai.autonomy.audit import AuditEntry, AuditLogger


def _make_entry(**overrides: object) -> AuditEntry:
    """Create a test AuditEntry with sensible defaults."""
    defaults = {
        "id": "audit-001",
        "action_type": "learning_recommendation",
        "source_id": "rec-001",
        "config_path": "configs/agents/test.yaml",
        "field_path": "model.temperature",
        "old_value": "0.7",
        "new_value": "0.5",
    }
    defaults.update(overrides)
    return AuditEntry(**defaults)


class TestAuditEntry:
    """Tests for the AuditEntry schema."""

    def test_defaults(self) -> None:
        entry = _make_entry()
        assert entry.applied_by == "autonomous_loop"
        assert entry.timestamp is not None

    def test_custom_applied_by(self) -> None:
        entry = _make_entry(applied_by="manual_review")
        assert entry.applied_by == "manual_review"

    def test_serialization_roundtrip(self) -> None:
        entry = _make_entry()
        data = json.loads(entry.model_dump_json())
        restored = AuditEntry(**data)
        assert restored.id == entry.id
        assert restored.source_id == entry.source_id
        assert restored.config_path == entry.config_path


class TestAuditLogger:
    """Tests for the AuditLogger."""

    def test_log_and_retrieve(self, tmp_path: Path) -> None:
        logger = AuditLogger(base_dir=str(tmp_path / "audit"))
        entry = _make_entry()
        logger.log(entry)

        entries = logger.get_entries()
        assert len(entries) == 1
        assert entries[0].id == "audit-001"

    def test_jsonl_persistence(self, tmp_path: Path) -> None:
        audit_dir = str(tmp_path / "audit")
        logger = AuditLogger(base_dir=audit_dir)
        logger.log(_make_entry(id="a1"))
        logger.log(_make_entry(id="a2"))

        # Re-create logger to prove file persistence
        logger2 = AuditLogger(base_dir=audit_dir)
        entries = logger2.get_entries()
        assert len(entries) == 2

    def test_get_entries_newest_first(self, tmp_path: Path) -> None:
        logger = AuditLogger(base_dir=str(tmp_path / "audit"))
        logger.log(_make_entry(id="first"))
        logger.log(_make_entry(id="second"))
        logger.log(_make_entry(id="third"))

        entries = logger.get_entries()
        assert entries[0].id == "third"
        assert entries[2].id == "first"  # noqa: scanner: skip-magic

    def test_get_entries_respects_limit(self, tmp_path: Path) -> None:
        logger = AuditLogger(base_dir=str(tmp_path / "audit"))
        for i in range(10):
            logger.log(_make_entry(id=f"entry-{i}"))

        entries = logger.get_entries(limit=3)
        assert len(entries) == 3

    def test_filter_by_source_id(self, tmp_path: Path) -> None:
        logger = AuditLogger(base_dir=str(tmp_path / "audit"))
        logger.log(_make_entry(id="a1", source_id="rec-A"))
        logger.log(_make_entry(id="a2", source_id="rec-B"))
        logger.log(_make_entry(id="a3", source_id="rec-A"))

        by_a = logger.get_entries_by_source("rec-A")
        assert len(by_a) == 2
        assert all(e.source_id == "rec-A" for e in by_a)

    def test_filter_by_source_id_no_match(self, tmp_path: Path) -> None:
        logger = AuditLogger(base_dir=str(tmp_path / "audit"))
        logger.log(_make_entry(id="a1", source_id="rec-X"))

        result = logger.get_entries_by_source("nonexistent")
        assert result == []

    def test_empty_log_returns_empty(self, tmp_path: Path) -> None:
        logger = AuditLogger(base_dir=str(tmp_path / "audit"))
        assert logger.get_entries() == []

    def test_creates_directory_on_log(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "audit"
        logger = AuditLogger(base_dir=str(nested))
        logger.log(_make_entry())
        assert nested.exists()

    def test_malformed_line_skipped(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()
        log_file = audit_dir / "audit_log.jsonl"
        # Write one good entry and one bad line
        entry = _make_entry(id="good")
        log_file.write_text(
            entry.model_dump_json() + "\n" + "NOT VALID JSON\n",
            encoding="utf-8",
        )

        logger = AuditLogger(base_dir=str(audit_dir))
        entries = logger.get_entries()
        assert len(entries) == 1
        assert entries[0].id == "good"

    def test_blank_lines_ignored(self, tmp_path: Path) -> None:
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()
        log_file = audit_dir / "audit_log.jsonl"
        entry = _make_entry(id="only")
        log_file.write_text(
            "\n" + entry.model_dump_json() + "\n\n",
            encoding="utf-8",
        )

        logger = AuditLogger(base_dir=str(audit_dir))
        entries = logger.get_entries()
        assert len(entries) == 1
