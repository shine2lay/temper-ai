"""Tests for PipelinePhaseTracker and pipeline phase observability.

Covers:
- PipelinePhaseTracker.start_phase / end_phase / fail_phase / fail_current
- Phase timing and metadata recording
- Serialization via .phases property
- replay_to_event_bus (with/without event bus)
- ExecutionTracker.record_pipeline_phases
- Integration: run_pipeline phases flow
"""

from __future__ import annotations

from unittest.mock import MagicMock

from temper_ai.workflow.pipeline_phases import PipelinePhaseTracker

# ---------------------------------------------------------------------------
# PipelinePhaseTracker — start / end / fail
# ---------------------------------------------------------------------------


class TestStartPhase:

    def test_records_phase_with_running_status(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("config_loading")
        assert len(tracker._phases) == 1
        assert tracker._phases[0]["name"] == "config_loading"
        assert tracker._phases[0]["status"] == "running"
        assert tracker._phases[0]["started_at"] is not None
        assert tracker._phases[0]["completed_at"] is None

    def test_records_metadata(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("config_loading", {"path": "/tmp/wf.yaml"})
        assert tracker._phases[0]["metadata"]["path"] == "/tmp/wf.yaml"

    def test_sets_current_phase(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("validation")
        assert tracker._current_phase == "validation"

    def test_multiple_phases_tracked(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("phase_a")
        tracker.end_phase("phase_a")
        tracker.start_phase("phase_b")
        tracker.end_phase("phase_b")
        assert len(tracker._phases) == 2
        assert tracker._phases[0]["name"] == "phase_a"
        assert tracker._phases[1]["name"] == "phase_b"


class TestEndPhase:

    def test_marks_completed_with_timing(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("config_loading")
        tracker.end_phase("config_loading")
        phase = tracker._phases[0]
        assert phase["status"] == "completed"
        assert phase["completed_at"] is not None
        assert phase["duration_ms"] is not None
        assert phase["duration_ms"] >= 0

    def test_merges_end_metadata(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("config_loading", {"path": "/tmp/wf.yaml"})
        tracker.end_phase("config_loading", {"stage_count": 5})
        phase = tracker._phases[0]
        assert phase["metadata"]["path"] == "/tmp/wf.yaml"
        assert phase["metadata"]["stage_count"] == 5

    def test_clears_current_phase(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("validation")
        assert tracker._current_phase == "validation"
        tracker.end_phase("validation")
        assert tracker._current_phase is None

    def test_warns_on_unknown_phase(self, caplog):
        tracker = PipelinePhaseTracker()
        tracker.end_phase("nonexistent")
        assert "unknown/inactive" in caplog.text


class TestFailPhase:

    def test_marks_failed_with_error(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("validation")
        tracker.fail_phase("validation", "Agent 'foo' not found")
        phase = tracker._phases[0]
        assert phase["status"] == "failed"
        assert phase["error"] == "Agent 'foo' not found"
        assert phase["completed_at"] is not None
        assert phase["duration_ms"] is not None

    def test_clears_current_phase(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("compilation")
        tracker.fail_phase("compilation", "syntax error")
        assert tracker._current_phase is None

    def test_warns_on_unknown_phase(self, caplog):
        tracker = PipelinePhaseTracker()
        tracker.fail_phase("nonexistent", "error")
        assert "unknown/inactive" in caplog.text


class TestFailCurrent:

    def test_fails_current_phase(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("infra_setup")
        tracker.fail_current("DB connection failed")
        assert tracker._phases[0]["status"] == "failed"
        assert tracker._phases[0]["error"] == "DB connection failed"

    def test_no_op_when_no_current_phase(self):
        tracker = PipelinePhaseTracker()
        tracker.fail_current("no current phase")
        # Should not raise, no phases recorded
        assert len(tracker._phases) == 0

    def test_only_fails_current_not_completed(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("config_loading")
        tracker.end_phase("config_loading")
        tracker.start_phase("validation")
        tracker.fail_current("validation error")
        assert tracker._phases[0]["status"] == "completed"
        assert tracker._phases[1]["status"] == "failed"


# ---------------------------------------------------------------------------
# Serialization (.phases property)
# ---------------------------------------------------------------------------


class TestPhaseSerialization:

    def test_converts_datetimes_to_iso_strings(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("config_loading")
        tracker.end_phase("config_loading")
        phases = tracker.phases
        assert isinstance(phases[0]["started_at"], str)
        assert isinstance(phases[0]["completed_at"], str)
        # ISO format check
        assert "T" in phases[0]["started_at"]

    def test_handles_none_completed_at(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("running_phase")
        phases = tracker.phases
        assert phases[0]["completed_at"] is None

    def test_returns_all_phases(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("a")
        tracker.end_phase("a")
        tracker.start_phase("b")
        tracker.end_phase("b")
        tracker.start_phase("c")
        tracker.fail_phase("c", "boom")
        phases = tracker.phases
        assert len(phases) == 3
        assert phases[0]["status"] == "completed"
        assert phases[1]["status"] == "completed"
        assert phases[2]["status"] == "failed"

    def test_does_not_mutate_internal_state(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("a")
        tracker.end_phase("a")
        phases = tracker.phases
        # Mutating returned phases should not affect internal state
        phases[0]["name"] = "mutated"
        assert tracker._phases[0]["name"] == "a"


# ---------------------------------------------------------------------------
# replay_to_event_bus
# ---------------------------------------------------------------------------


class TestReplayToEventBus:

    def test_no_op_when_event_bus_is_none(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("a")
        tracker.end_phase("a")
        # Should not raise
        tracker.replay_to_event_bus(None, "wf-123")

    def test_emits_start_and_end_events_for_completed_phase(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("config_loading", {"path": "/tmp/wf.yaml"})
        tracker.end_phase("config_loading", {"stage_count": 3})

        event_bus = MagicMock()
        tracker.replay_to_event_bus(event_bus, "wf-abc")

        assert event_bus.emit.call_count == 2
        events = [c.args[0] for c in event_bus.emit.call_args_list]

        assert events[0].event_type == "pipeline.phase_start"
        assert events[0].data["phase"] == "config_loading"
        assert events[0].workflow_id == "wf-abc"

        assert events[1].event_type == "pipeline.phase_end"
        assert events[1].data["phase"] == "config_loading"
        assert events[1].data["duration_ms"] is not None

    def test_emits_start_and_fail_events_for_failed_phase(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("validation")
        tracker.fail_phase("validation", "Agent 'bad' not found")

        event_bus = MagicMock()
        tracker.replay_to_event_bus(event_bus, "wf-def")

        assert event_bus.emit.call_count == 2
        events = [c.args[0] for c in event_bus.emit.call_args_list]

        assert events[0].event_type == "pipeline.phase_start"
        assert events[1].event_type == "pipeline.phase_fail"
        assert events[1].data["error"] == "Agent 'bad' not found"

    def test_emits_only_start_for_running_phase(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("compilation")
        # Phase still running — no end/fail

        event_bus = MagicMock()
        tracker.replay_to_event_bus(event_bus, "wf-ghi")

        assert event_bus.emit.call_count == 1
        assert event_bus.emit.call_args[0][0].event_type == "pipeline.phase_start"

    def test_replays_multiple_phases_in_order(self):
        tracker = PipelinePhaseTracker()
        tracker.start_phase("config_loading")
        tracker.end_phase("config_loading")
        tracker.start_phase("validation")
        tracker.end_phase("validation")
        tracker.start_phase("compilation")
        tracker.fail_phase("compilation", "error")

        event_bus = MagicMock()
        tracker.replay_to_event_bus(event_bus, "wf-jkl")

        # 3 phases × 2 events each = 6
        assert event_bus.emit.call_count == 6
        event_types = [c.args[0].event_type for c in event_bus.emit.call_args_list]
        assert event_types == [
            "pipeline.phase_start",
            "pipeline.phase_end",
            "pipeline.phase_start",
            "pipeline.phase_end",
            "pipeline.phase_start",
            "pipeline.phase_fail",
        ]


# ---------------------------------------------------------------------------
# ExecutionTracker.record_pipeline_phases
# ---------------------------------------------------------------------------


class TestRecordPipelinePhases:

    def test_calls_backend_update_workflow_metadata(self):
        from temper_ai.observability.tracker import ExecutionTracker

        backend = MagicMock()
        tracker = ExecutionTracker(backend=backend)

        phases = [
            {"name": "config_loading", "status": "completed", "duration_ms": 120},
            {"name": "validation", "status": "completed", "duration_ms": 45},
        ]
        tracker.record_pipeline_phases("wf-123", phases)

        backend.update_workflow_metadata.assert_called_once_with(
            "wf-123", {"pipeline_phases": phases}
        )

    def test_does_not_raise_on_backend_error(self):
        from temper_ai.observability.tracker import ExecutionTracker

        backend = MagicMock()
        backend.update_workflow_metadata.side_effect = RuntimeError("DB error")
        tracker = ExecutionTracker(backend=backend)

        # Should not raise, just log warning
        tracker.record_pipeline_phases("wf-456", [])


# ---------------------------------------------------------------------------
# Integration: full pipeline phase flow
# ---------------------------------------------------------------------------


class TestPipelinePhaseFlow:

    def test_full_pipeline_records_all_phases(self):
        """Simulate the run_pipeline phase flow."""
        phases = PipelinePhaseTracker()

        # Phase 1: config loading
        phases.start_phase("config_loading", {"path": "workflows/test.yaml"})
        phases.end_phase("config_loading", {"stage_count": 3})

        # Phase 2: lifecycle adaptation
        phases.start_phase("lifecycle_adaptation")
        phases.end_phase("lifecycle_adaptation")

        # Phase 3: infrastructure setup
        phases.start_phase("infrastructure_setup")
        phases.end_phase("infrastructure_setup")

        # Phase 4: validation
        phases.start_phase("validation")
        phases.end_phase("validation")

        # Phase 5: compilation
        phases.start_phase("compilation")
        phases.end_phase("compilation")

        serialized = phases.phases
        assert len(serialized) == 5
        assert all(p["status"] == "completed" for p in serialized)
        assert all(p["duration_ms"] is not None for p in serialized)
        assert serialized[0]["metadata"]["path"] == "workflows/test.yaml"
        assert serialized[0]["metadata"]["stage_count"] == 3

    def test_validation_failure_records_error(self):
        """When validation fails, phases show exactly where it broke."""
        phases = PipelinePhaseTracker()

        phases.start_phase("config_loading")
        phases.end_phase("config_loading")

        phases.start_phase("validation")
        phases.fail_phase("validation", "Agent 'reseracher' not found")

        serialized = phases.phases
        assert len(serialized) == 2
        assert serialized[0]["status"] == "completed"
        assert serialized[1]["status"] == "failed"
        assert serialized[1]["error"] == "Agent 'reseracher' not found"

    def test_fail_current_catches_mid_phase_exception(self):
        """Simulates the except clause in run_pipeline."""
        phases = PipelinePhaseTracker()

        phases.start_phase("config_loading")
        phases.end_phase("config_loading")

        phases.start_phase("compilation")
        # Exception happens during compilation
        phases.fail_current("ValueError: invalid stage reference")

        serialized = phases.phases
        assert serialized[0]["status"] == "completed"
        assert serialized[1]["status"] == "failed"
        assert "invalid stage reference" in serialized[1]["error"]

    def test_replay_then_persist(self):
        """Simulate the _execute_in_tracker_scope flow: replay + persist."""
        phases = PipelinePhaseTracker()
        phases.start_phase("config_loading")
        phases.end_phase("config_loading")
        phases.start_phase("validation")
        phases.end_phase("validation")

        # Replay to event bus
        event_bus = MagicMock()
        phases.replay_to_event_bus(event_bus, "wf-test")
        assert event_bus.emit.call_count == 4  # 2 phases × 2 events

        # Persist via tracker
        from temper_ai.observability.tracker import ExecutionTracker

        backend = MagicMock()
        tracker = ExecutionTracker(backend=backend)
        tracker.record_pipeline_phases("wf-test", phases.phases)

        backend.update_workflow_metadata.assert_called_once()
        stored_phases = backend.update_workflow_metadata.call_args[0][1][
            "pipeline_phases"
        ]
        assert len(stored_phases) == 2
        assert all(isinstance(p["started_at"], str) for p in stored_phases)
