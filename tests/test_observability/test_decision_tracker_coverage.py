"""Tests for decision_tracker.py to cover uncovered lines."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.observability.decision_tracker import (
    DecisionTracker,
    DecisionTrackingParams,
    _resolve_decision_params,
)


class TestResolveDecisionParams:
    """Test _resolve_decision_params helper."""

    def test_direct_params(self):
        params = DecisionTrackingParams(
            decision_type="test", outcome="success", decision_data={}
        )
        result = _resolve_decision_params(params)
        assert result is params

    def test_from_string_type(self):
        result = _resolve_decision_params(
            "experiment", outcome="success", decision_data={"key": "val"}
        )
        assert result.decision_type == "experiment"
        assert result.outcome == "success"

    def test_from_kwargs_with_decision_type(self):
        result = _resolve_decision_params(
            None, decision_type="experiment", outcome="success", decision_data={}
        )
        assert result.decision_type == "experiment"

    def test_from_kwargs_params(self):
        params = DecisionTrackingParams(
            decision_type="test", outcome="success", decision_data={}
        )
        result = _resolve_decision_params(None, params=params)
        assert result is params

    def test_raises_type_error(self):
        with pytest.raises(TypeError, match="requires a DecisionTrackingParams"):
            _resolve_decision_params(None)


class TestDecisionTracker:
    """Test DecisionTracker class."""

    def test_init_default_sanitizer(self):
        tracker = DecisionTracker()
        # The default sanitizer should be a no-op
        result = tracker._sanitize({"key": "value"}, 0)
        assert result == {"key": "value"}

    def test_init_custom_sanitizer(self):
        def custom_sanitize(d: dict, _depth: int = 0) -> dict:
            return dict.fromkeys(d, "***")

        tracker = DecisionTracker(sanitize_fn=custom_sanitize)
        result = tracker._sanitize({"key": "value"}, 0)
        assert result == {"key": "***"}

    def test_track_success(self):
        tracker = DecisionTracker()

        mock_session = MagicMock()
        mock_decision_outcome = MagicMock()

        with patch(
            "temper_ai.observability.decision_tracker.DecisionOutcome",
            mock_decision_outcome,
            create=True,
        ):
            with patch.dict("sys.modules", {}):
                # Mock the import inside _create_decision_record
                with patch(
                    "temper_ai.observability.decision_tracker.DecisionTracker._create_decision_record"
                ) as mock_create:
                    mock_record = MagicMock()
                    mock_create.return_value = mock_record

                    with patch(
                        "temper_ai.observability.decision_tracker.DecisionTracker._persist_decision"
                    ) as mock_persist:
                        mock_persist.return_value = "decision-abc123"

                        result = tracker.track(
                            mock_session,
                            decision_type="experiment",
                            outcome="success",
                            decision_data={"key": "value"},
                        )
                        assert result == "decision-abc123"

    def test_track_create_record_returns_none(self):
        """Test track when _create_decision_record returns None (import error)."""
        tracker = DecisionTracker()
        mock_session = MagicMock()

        with patch.object(tracker, "_create_decision_record", return_value=None):
            result = tracker.track(
                mock_session,
                decision_type="test",
                outcome="success",
                decision_data={},
            )
            assert result == ""

    def test_create_decision_record_import_error(self):
        """Test _create_decision_record when DecisionOutcome can't be imported."""
        tracker = DecisionTracker()
        params = DecisionTrackingParams(
            decision_type="test",
            outcome="success",
            decision_data={"key": "value"},
            impact_metrics={"confidence": 0.9},
        )

        with patch(
            "builtins.__import__",
            side_effect=ImportError("no module"),
        ):
            result = tracker._create_decision_record(params, "decision-123")
            assert result is None

    def test_create_decision_record_type_error(self):
        """Test _create_decision_record when DecisionOutcome raises TypeError."""
        tracker = DecisionTracker()
        params = DecisionTrackingParams(
            decision_type="test",
            outcome="success",
            decision_data={"key": "value"},
        )

        mock_module = MagicMock()
        mock_module.DecisionOutcome.side_effect = TypeError("bad args")

        with patch.dict(
            "sys.modules",
            {
                "temper_ai.storage.database.models": mock_module,
            },
        ):
            result = tracker._create_decision_record(params, "decision-123")
            assert result is None

    def test_create_decision_record_value_error(self):
        """Test _create_decision_record when DecisionOutcome raises ValueError."""
        tracker = DecisionTracker()
        params = DecisionTrackingParams(
            decision_type="test",
            outcome="success",
            decision_data={"key": "value"},
        )

        mock_module = MagicMock()
        mock_module.DecisionOutcome.side_effect = ValueError("bad value")

        with patch.dict(
            "sys.modules",
            {
                "temper_ai.storage.database.models": mock_module,
            },
        ):
            result = tracker._create_decision_record(params, "decision-123")
            assert result is None

    def test_persist_decision_attribute_error(self):
        """Test _persist_decision when session has no required methods."""
        tracker = DecisionTracker()
        mock_session = MagicMock()
        mock_session.add.side_effect = AttributeError("no add method")

        params = DecisionTrackingParams(
            decision_type="test",
            outcome="success",
            decision_data={},
        )

        result = tracker._persist_decision(
            mock_session, MagicMock(), params, "decision-123"
        )
        assert result == ""

    def test_persist_decision_database_error(self):
        """Test _persist_decision on database error with rollback."""
        tracker = DecisionTracker()
        mock_session = MagicMock()
        mock_session.commit.side_effect = Exception("database error")

        params = DecisionTrackingParams(
            decision_type="test",
            outcome="success",
            decision_data={},
        )

        result = tracker._persist_decision(
            mock_session, MagicMock(), params, "decision-123"
        )
        assert result == ""
        mock_session.rollback.assert_called_once()

    def test_persist_decision_rollback_also_fails(self):
        """Test _persist_decision when rollback also fails."""
        tracker = DecisionTracker()
        mock_session = MagicMock()
        mock_session.commit.side_effect = Exception("database error")
        mock_session.rollback.side_effect = Exception("rollback failed")

        params = DecisionTrackingParams(
            decision_type="test",
            outcome="success",
            decision_data={},
        )

        result = tracker._persist_decision(
            mock_session, MagicMock(), params, "decision-123"
        )
        assert result == ""

    def test_update_merit_score_if_applicable(self):
        """Test merit score update when agent_name is in decision data."""
        tracker = DecisionTracker()
        tracker._merit_service = MagicMock()
        mock_session = MagicMock()

        params = DecisionTrackingParams(
            decision_type="test",
            outcome="success",
            decision_data={"agent_name": "researcher"},
            impact_metrics={"confidence": 0.9},
            tags=["analysis"],
        )

        tracker._update_merit_score_if_applicable(mock_session, params, "decision-123")
        tracker._merit_service.update.assert_called_once()

    def test_update_merit_score_no_tags(self):
        """Test merit score update without tags (uses decision_type as domain)."""
        tracker = DecisionTracker()
        tracker._merit_service = MagicMock()
        mock_session = MagicMock()

        params = DecisionTrackingParams(
            decision_type="experiment",
            outcome="success",
            decision_data={"agent_name": "researcher"},
        )

        tracker._update_merit_score_if_applicable(mock_session, params, "decision-123")
        tracker._merit_service.update.assert_called_once_with(
            session=mock_session,
            agent_name="researcher",
            domain="experiment",
            decision_outcome="success",
            confidence=None,
        )

    def test_update_merit_score_exception(self):
        """Test merit score update when exception occurs."""
        tracker = DecisionTracker()
        tracker._merit_service = MagicMock()
        tracker._merit_service.update.side_effect = RuntimeError("merit error")
        mock_session = MagicMock()

        params = DecisionTrackingParams(
            decision_type="test",
            outcome="success",
            decision_data={"agent_name": "researcher"},
        )

        # Should not raise
        tracker._update_merit_score_if_applicable(mock_session, params, "decision-123")

    def test_update_merit_score_no_agent_name(self):
        """Test merit score update skipped when no agent_name in data."""
        tracker = DecisionTracker()
        tracker._merit_service = MagicMock()
        mock_session = MagicMock()

        params = DecisionTrackingParams(
            decision_type="test",
            outcome="success",
            decision_data={"key": "value"},
        )

        tracker._update_merit_score_if_applicable(mock_session, params, "decision-123")
        tracker._merit_service.update.assert_not_called()
