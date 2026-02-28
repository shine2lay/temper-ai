"""Tests for temper_ai/stage/executors/_parallel_observability.py.

Covers:
- _emit_synthesis_event (no tracker, missing method, with tracker)
- _build_synthesis_metadata (all fields present)
- _emit_output_lineage (no tracker, exception swallowed, success)
- _emit_parallel_cost_summary (no tracker, exception swallowed, success)
- _track_quality_gate_event (no tracker, failure type, retry type)
- _emit_quality_gate_violation_details (exception swallowed)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from temper_ai.stage.executors._parallel_observability import (
    _build_synthesis_metadata,
    _emit_output_lineage,
    _emit_parallel_cost_summary,
    _emit_quality_gate_violation_details,
    _emit_synthesis_event,
    _track_quality_gate_event,
)
from temper_ai.stage.executors.state_keys import StateKeys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_synthesis_result(
    method="majority_vote",
    confidence=0.8,
    votes=None,
    conflicts=None,
    decision="yes",
    reasoning="good",
):
    sr = MagicMock()
    sr.method = method
    sr.confidence = confidence
    sr.votes = votes or {"yes": 3}
    sr.conflicts = conflicts or []
    sr.decision = decision
    sr.reasoning = reasoning
    return sr


def _make_state(tracker=None, stage_id="sid-1", workflow_id="wf-1"):
    state: dict = {
        StateKeys.WORKFLOW_ID: workflow_id,
        StateKeys.CURRENT_STAGE_ID: stage_id,
    }
    if tracker is not None:
        state[StateKeys.TRACKER] = tracker
    return state


def _make_tracker(has_collab=True, has_stage_output=True, has_cost_summary=True):
    t = MagicMock()
    if not has_collab:
        del t.track_collaboration_event
    if not has_stage_output:
        del t.set_stage_output
    if not has_cost_summary:
        del t.emit_cost_summary
    return t


# ---------------------------------------------------------------------------
# TestEmitSynthesisEvent
# ---------------------------------------------------------------------------


class TestEmitSynthesisEvent:
    """_emit_synthesis_event emits or skips based on tracker presence."""

    def test_no_tracker_in_state_is_noop(self):
        state = _make_state(tracker=None)
        sr = _make_synthesis_result()
        # Should complete without error and make no tracker calls
        _emit_synthesis_event(state, "s1", sr, {}, {}, {})

    def test_tracker_without_track_collaboration_event_is_noop(self):
        tracker = MagicMock(spec=[])  # no methods
        state = _make_state(tracker=tracker)
        sr = _make_synthesis_result()
        _emit_synthesis_event(state, "s1", sr, {}, {}, {})
        # No track_collaboration_event attribute → no call attempted

    def test_with_tracker_calls_track_collaboration_event(self):
        tracker = MagicMock()
        state = _make_state(tracker=tracker)
        sr = _make_synthesis_result(decision="go", confidence=0.9)
        agent_outputs = {"agent-a": MagicMock()}

        with patch(
            "temper_ai.observability._tracker_helpers.CollaborationEventData"
        ) as mock_ced:
            mock_ced.return_value = MagicMock()
            _emit_synthesis_event(state, "stage1", sr, agent_outputs, {}, {})

        tracker.track_collaboration_event.assert_called_once()
        ced_kwargs = mock_ced.call_args.kwargs
        assert ced_kwargs["event_type"] == "synthesis"
        assert ced_kwargs["stage_name"] == "stage1"
        assert "agent-a" in ced_kwargs["agents"]
        assert ced_kwargs["decision"] == "go"
        assert ced_kwargs["confidence"] == 0.9


# ---------------------------------------------------------------------------
# TestBuildSynthesisMetadata
# ---------------------------------------------------------------------------


class TestBuildSynthesisMetadata:
    """_build_synthesis_metadata includes all required fields."""

    def _call(self, sr=None, parallel_result=None, aggregate_metrics=None):
        sr = sr or _make_synthesis_result()
        parallel_result = parallel_result or {StateKeys.AGENT_STATUSES: {"a": "ok"}}
        aggregate_metrics = aggregate_metrics or {"total_tokens": 500}
        return _build_synthesis_metadata(sr, parallel_result, aggregate_metrics)

    def test_includes_method(self):
        sr = _make_synthesis_result(method="weighted_vote")
        result = self._call(sr=sr)
        assert result[StateKeys.METHOD] == "weighted_vote"

    def test_includes_confidence(self):
        sr = _make_synthesis_result(confidence=0.75)
        result = self._call(sr=sr)
        assert result[StateKeys.CONFIDENCE] == 0.75

    def test_includes_votes(self):
        sr = _make_synthesis_result(votes={"yes": 2, "no": 1})
        result = self._call(sr=sr)
        assert result[StateKeys.VOTES] == {"yes": 2, "no": 1}

    def test_num_conflicts_is_length_of_conflicts(self):
        sr = _make_synthesis_result(conflicts=["c1", "c2"])
        result = self._call(sr=sr)
        assert result["num_conflicts"] == 2

    def test_includes_reasoning(self):
        sr = _make_synthesis_result(reasoning="thorough")
        result = self._call(sr=sr)
        assert result[StateKeys.REASONING] == "thorough"

    def test_includes_agent_statuses(self):
        parallel_result = {StateKeys.AGENT_STATUSES: {"agent-1": "success"}}
        result = self._call(parallel_result=parallel_result)
        assert result[StateKeys.AGENT_STATUSES] == {"agent-1": "success"}

    def test_includes_aggregate_metrics(self):
        agg = {"total_tokens": 999}
        result = self._call(aggregate_metrics=agg)
        assert result[StateKeys.AGGREGATE_METRICS] == agg


# ---------------------------------------------------------------------------
# TestEmitOutputLineage
# ---------------------------------------------------------------------------


class TestEmitOutputLineage:
    """_emit_output_lineage tracks lineage or swallows exceptions."""

    def test_no_tracker_is_noop(self):
        state = _make_state(tracker=None)
        # Should not raise
        _emit_output_lineage(state, "s1", {}, {}, _make_synthesis_result())

    def test_exception_swallowed_and_logged(self):
        tracker = MagicMock()
        state = _make_state(tracker=tracker)
        sr = _make_synthesis_result()

        with patch(
            "temper_ai.observability.lineage.compute_output_lineage",
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise
            _emit_output_lineage(state, "s1", {}, {}, sr)

    def test_with_tracker_calls_set_stage_output(self):
        tracker = MagicMock()
        state = _make_state(tracker=tracker, stage_id="stage-99")
        sr = _make_synthesis_result()
        agent_outputs = {"a1": MagicMock()}
        parallel_result = {StateKeys.AGENT_STATUSES: {}}
        fake_lineage = MagicMock()
        fake_lineage_dict = {"source": "a1"}

        with (
            patch(
                "temper_ai.observability.lineage.compute_output_lineage",
                return_value=fake_lineage,
            ),
            patch(
                "temper_ai.observability.lineage.lineage_to_dict",
                return_value=fake_lineage_dict,
            ),
        ):
            _emit_output_lineage(state, "stage1", agent_outputs, parallel_result, sr)

        tracker.set_stage_output.assert_called_once_with(
            stage_id="stage-99",
            output_data={},
            output_lineage=fake_lineage_dict,
        )


# ---------------------------------------------------------------------------
# TestEmitParallelCostSummary
# ---------------------------------------------------------------------------


class TestEmitParallelCostSummary:
    """_emit_parallel_cost_summary emits or swallows."""

    def test_no_tracker_is_noop(self):
        state = _make_state(tracker=None)
        _emit_parallel_cost_summary(state, "s1", {})

    def test_exception_swallowed(self):
        tracker = MagicMock()
        state = _make_state(tracker=tracker)

        with patch(
            "temper_ai.observability.cost_rollup.compute_stage_cost_summary",
            side_effect=ValueError("oops"),
        ):
            # Should not raise
            _emit_parallel_cost_summary(state, "s1", {})

    def test_with_tracker_calls_emit_cost_summary(self):
        tracker = MagicMock()
        state = _make_state(tracker=tracker, stage_id="sid-x")
        parallel_result = {
            StateKeys.AGENT_METRICS: {"a": {"tokens": 10}},
            StateKeys.AGENT_STATUSES: {"a": "success"},
        }
        fake_summary = MagicMock()

        with (
            patch(
                "temper_ai.observability.cost_rollup.compute_stage_cost_summary",
                return_value=fake_summary,
            ) as mock_compute,
            patch("temper_ai.observability.cost_rollup.emit_cost_summary") as mock_emit,
        ):
            _emit_parallel_cost_summary(state, "stage-z", parallel_result)

        mock_compute.assert_called_once()
        mock_emit.assert_called_once_with(tracker, "sid-x", fake_summary)


# ---------------------------------------------------------------------------
# TestTrackQualityGateEvent
# ---------------------------------------------------------------------------


class TestTrackQualityGateEvent:
    """_track_quality_gate_event handles no tracker, failure, retry types."""

    def test_no_tracker_is_noop(self):
        sr = _make_synthesis_result()
        # Should not raise
        _track_quality_gate_event(None, "quality_gate_failure", "s1", sr, [], {}, 0)

    def test_failure_type_includes_on_failure_action(self):
        tracker = MagicMock()
        sr = _make_synthesis_result()
        qg_config = {"on_failure": "abort", "max_retries": 2}

        with patch(
            "temper_ai.observability._tracker_helpers.CollaborationEventData"
        ) as mock_ced:
            mock_ced.return_value = MagicMock()
            _track_quality_gate_event(
                tracker, "quality_gate_failure", "stage1", sr, ["v1"], qg_config, 1
            )

        ced_kwargs = mock_ced.call_args.kwargs
        meta = ced_kwargs["metadata"]
        assert "on_failure_action" in meta
        assert meta["on_failure_action"] == "abort"

    def test_retry_type_includes_retry_attempt(self):
        tracker = MagicMock()
        sr = _make_synthesis_result()
        qg_config = {"max_retries": 3}

        with patch(
            "temper_ai.observability._tracker_helpers.CollaborationEventData"
        ) as mock_ced:
            mock_ced.return_value = MagicMock()
            _track_quality_gate_event(
                tracker, "quality_gate_retry", "stage1", sr, [], qg_config, 2
            )

        ced_kwargs = mock_ced.call_args.kwargs
        meta = ced_kwargs["metadata"]
        assert "retry_attempt" in meta
        assert meta["retry_attempt"] == 3  # retry_count + 1


# ---------------------------------------------------------------------------
# TestEmitQualityGateViolationDetails
# ---------------------------------------------------------------------------


class TestEmitQualityGateViolationDetails:
    """_emit_quality_gate_violation_details swallows exceptions."""

    def test_exception_swallowed(self):
        state = _make_state()
        sr = _make_synthesis_result()

        with patch(
            "temper_ai.observability.dialogue_metrics.build_quality_gate_details",
            side_effect=RuntimeError("crash"),
        ):
            # Should not raise
            _emit_quality_gate_violation_details(state, "s1", [], sr, {})

    def test_calls_emit_when_successful(self):
        tracker = MagicMock()
        state = _make_state(tracker=tracker, stage_id="sid-q")
        sr = _make_synthesis_result()
        violations = ["v1"]
        qg_config = {"max_retries": 1}
        fake_details = {"detail": "data"}

        with (
            patch(
                "temper_ai.observability.dialogue_metrics.build_quality_gate_details",
                return_value=fake_details,
            ) as mock_build,
            patch(
                "temper_ai.observability.dialogue_metrics.emit_quality_gate_details"
            ) as mock_emit,
        ):
            _emit_quality_gate_violation_details(
                state, "stage1", violations, sr, qg_config
            )

        mock_build.assert_called_once_with(violations, sr, qg_config)
        mock_emit.assert_called_once_with(tracker, "sid-q", "stage1", fake_details)
