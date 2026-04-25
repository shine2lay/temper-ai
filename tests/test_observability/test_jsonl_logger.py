"""Tests for JsonlNotifier — per-run JSONL log file."""

from __future__ import annotations

import json
from pathlib import Path

from temper_ai.observability.jsonl_logger import RUNNER_VERSION, JsonlNotifier


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_header_written_at_init(tmp_path):
    notif = JsonlNotifier(
        "exec-1", "test_workflow", log_dir=tmp_path,
        metadata={"k": "v"},
    )
    notif.cleanup("exec-1")

    path = tmp_path / "exec-1" / "events.jsonl"
    assert path.is_file()
    lines = _read_lines(path)
    assert len(lines) >= 2  # header + footer

    header = lines[0]
    assert header["kind"] == "header"
    assert header["execution_id"] == "exec-1"
    assert header["workflow_name"] == "test_workflow"
    assert header["runner_version"] == RUNNER_VERSION
    assert header["metadata"] == {"k": "v"}
    assert "started_at" in header
    assert "hostname" in header
    assert "pid" in header


def test_events_appended_in_order(tmp_path):
    notif = JsonlNotifier("exec-2", "wf", log_dir=tmp_path)
    notif.notify_event("exec-2", "node.started", {"node": "A"})
    notif.notify_event("exec-2", "node.completed", {"node": "A", "ok": True})
    notif.cleanup("exec-2")

    lines = _read_lines(tmp_path / "exec-2" / "events.jsonl")
    # header + 2 events + footer
    assert lines[0]["kind"] == "header"
    assert lines[1]["kind"] == "event"
    assert lines[1]["event_type"] == "node.started"
    assert lines[1]["data"] == {"node": "A"}
    assert lines[2]["kind"] == "event"
    assert lines[2]["event_type"] == "node.completed"
    assert lines[3]["kind"] == "footer"


def test_cleanup_writes_footer(tmp_path):
    notif = JsonlNotifier("exec-3", "wf", log_dir=tmp_path)
    notif.cleanup("exec-3")

    lines = _read_lines(tmp_path / "exec-3" / "events.jsonl")
    footer = lines[-1]
    assert footer["kind"] == "footer"
    assert footer["execution_id"] == "exec-3"
    assert footer["reason"] == "cleanup"


def test_cleanup_idempotent(tmp_path):
    notif = JsonlNotifier("exec-4", "wf", log_dir=tmp_path)
    notif.cleanup("exec-4")
    notif.cleanup("exec-4")  # must not raise or double-footer
    lines = _read_lines(tmp_path / "exec-4" / "events.jsonl")
    footers = [line for line in lines if line["kind"] == "footer"]
    assert len(footers) == 1


def test_log_dir_resolution_explicit_arg_wins(tmp_path, monkeypatch):
    """Explicit log_dir arg trumps $TEMPER_LOG_DIR."""
    other = tmp_path / "other"
    monkeypatch.setenv("TEMPER_LOG_DIR", str(other))
    notif = JsonlNotifier("exec-5", "wf", log_dir=tmp_path / "explicit")
    notif.cleanup("exec-5")
    assert (tmp_path / "explicit" / "exec-5" / "events.jsonl").is_file()
    assert not (other / "exec-5").exists()


def test_log_dir_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPER_LOG_DIR", str(tmp_path / "env"))
    notif = JsonlNotifier("exec-6", "wf")  # no explicit log_dir
    notif.cleanup("exec-6")
    assert (tmp_path / "env" / "exec-6" / "events.jsonl").is_file()


def test_missing_footer_marks_interrupted_run(tmp_path):
    """If cleanup never runs (worker crashed), no footer is written.
    Analytics consumers detect interruption by `kind != footer` on last line.
    """
    notif = JsonlNotifier("exec-7", "wf", log_dir=tmp_path)
    notif.notify_event("exec-7", "node.started", {})
    # Skip cleanup — simulates a worker that died

    lines = _read_lines(tmp_path / "exec-7" / "events.jsonl")
    assert lines[-1]["kind"] != "footer"


def test_resume_appends_to_existing_file(tmp_path):
    """A second JsonlNotifier with the same execution_id appends — supports
    resume semantics where later attempts add more events."""
    n1 = JsonlNotifier("exec-8", "wf", log_dir=tmp_path)
    n1.notify_event("exec-8", "first_attempt", {})
    n1.cleanup("exec-8")

    n2 = JsonlNotifier("exec-8", "wf", log_dir=tmp_path)
    n2.notify_event("exec-8", "resumed", {})
    n2.cleanup("exec-8")

    lines = _read_lines(tmp_path / "exec-8" / "events.jsonl")
    event_types = [line.get("event_type") for line in lines if line["kind"] == "event"]
    assert "first_attempt" in event_types
    assert "resumed" in event_types


def test_unhealthy_after_io_failure(tmp_path):
    """Simulated write failure → notifier degrades to no-op, doesn't crash
    callers."""
    notif = JsonlNotifier("exec-9", "wf", log_dir=tmp_path)
    # Force a write to fail by closing the underlying file out from under it
    notif._fp.close()  # noqa: SLF001
    notif.notify_event("exec-9", "after_close", {})  # must not raise
    assert notif.enabled is False


def test_path_property_exposes_target(tmp_path):
    notif = JsonlNotifier("exec-10", "wf", log_dir=tmp_path)
    assert notif.path == tmp_path / "exec-10" / "events.jsonl"
    notif.cleanup("exec-10")


def test_init_failure_does_not_raise(tmp_path):
    """If parent dir creation fails (e.g., permission error), the notifier
    runs in degraded mode — workflow still proceeds."""
    # Pass a path under a file (not a dir) — mkdir will fail
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    notif = JsonlNotifier("exec-11", "wf", log_dir=blocker / "sub")
    assert notif.enabled is False
    # All ops should be no-op safe
    notif.notify_event("exec-11", "x", {})
    notif.cleanup("exec-11")


def test_handles_unserializable_data_gracefully(tmp_path):
    """data with non-JSON-serializable values uses default=str so it
    doesn't crash the worker. Consumers see string repr instead of native."""
    notif = JsonlNotifier("exec-12", "wf", log_dir=tmp_path)

    class WeirdObj:
        def __repr__(self):
            return "<WeirdObj>"

    notif.notify_event("exec-12", "weird", {"obj": WeirdObj()})
    notif.cleanup("exec-12")

    lines = _read_lines(tmp_path / "exec-12" / "events.jsonl")
    event = next(line for line in lines if line["kind"] == "event")
    assert "WeirdObj" in event["data"]["obj"]
