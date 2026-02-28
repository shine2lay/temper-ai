"""Tests for portfolio observability tracking helper."""

from unittest.mock import MagicMock, patch

from temper_ai.portfolio._tracking import track_portfolio_event


class TestTrackPortfolioEvent:
    """Tests for track_portfolio_event function."""

    def test_calls_tracker_on_success(self):
        mock_tracker = MagicMock()
        mock_tracking_data_cls = MagicMock()
        mock_tracking_data_instance = MagicMock()
        mock_tracking_data_cls.return_value = mock_tracking_data_instance

        with (
            patch(
                "temper_ai.observability.get_tracker",
                return_value=mock_tracker,
            ),
            patch(
                "temper_ai.observability._tracker_helpers.DecisionTrackingData",
                mock_tracking_data_cls,
            ),
        ):
            track_portfolio_event(
                decision_type="scorecard_computed",
                decision_data={"product": "web_app"},
                outcome="success",
            )

        mock_tracking_data_cls.assert_called_once_with(
            decision_type="scorecard_computed",
            decision_data={"product": "web_app"},
            outcome="success",
            impact_metrics=None,
            validation_duration_seconds=None,
            tags=["portfolio"],
        )
        mock_tracker.track_decision_outcome.assert_called_once_with(
            mock_tracking_data_instance
        )

    def test_passes_optional_impact_metrics(self):
        mock_tracker = MagicMock()
        mock_tracking_data_cls = MagicMock()

        with (
            patch("temper_ai.observability.get_tracker", return_value=mock_tracker),
            patch(
                "temper_ai.observability._tracker_helpers.DecisionTrackingData",
                mock_tracking_data_cls,
            ),
        ):
            track_portfolio_event(
                decision_type="optimize",
                decision_data={},
                outcome="ok",
                impact_metrics={"cost_delta": -10.5},
            )

        call_kwargs = mock_tracking_data_cls.call_args.kwargs
        assert call_kwargs["impact_metrics"] == {"cost_delta": -10.5}

    def test_passes_optional_duration(self):
        mock_tracker = MagicMock()
        mock_tracking_data_cls = MagicMock()

        with (
            patch("temper_ai.observability.get_tracker", return_value=mock_tracker),
            patch(
                "temper_ai.observability._tracker_helpers.DecisionTrackingData",
                mock_tracking_data_cls,
            ),
        ):
            track_portfolio_event(
                decision_type="optimize",
                decision_data={},
                outcome="ok",
                duration_s=1.23,
            )

        call_kwargs = mock_tracking_data_cls.call_args.kwargs
        assert call_kwargs["validation_duration_seconds"] == 1.23

    def test_passes_custom_tags(self):
        mock_tracker = MagicMock()
        mock_tracking_data_cls = MagicMock()

        with (
            patch("temper_ai.observability.get_tracker", return_value=mock_tracker),
            patch(
                "temper_ai.observability._tracker_helpers.DecisionTrackingData",
                mock_tracking_data_cls,
            ),
        ):
            track_portfolio_event(
                decision_type="invest",
                decision_data={},
                outcome="ok",
                tags=["portfolio", "optimizer"],
            )

        call_kwargs = mock_tracking_data_cls.call_args.kwargs
        assert call_kwargs["tags"] == ["portfolio", "optimizer"]

    def test_defaults_tags_to_portfolio_list(self):
        mock_tracker = MagicMock()
        mock_tracking_data_cls = MagicMock()

        with (
            patch("temper_ai.observability.get_tracker", return_value=mock_tracker),
            patch(
                "temper_ai.observability._tracker_helpers.DecisionTrackingData",
                mock_tracking_data_cls,
            ),
        ):
            track_portfolio_event(
                decision_type="invest",
                decision_data={},
                outcome="ok",
                tags=None,
            )

        call_kwargs = mock_tracking_data_cls.call_args.kwargs
        assert call_kwargs["tags"] == ["portfolio"]

    def test_silently_degrades_on_import_error(self):
        """Tracker unavailable should not raise."""
        with patch(
            "temper_ai.observability.get_tracker",
            side_effect=ImportError("tracker not available"),
        ):
            # Should not raise
            track_portfolio_event(
                decision_type="test",
                decision_data={},
                outcome="ok",
            )

    def test_silently_degrades_on_tracker_exception(self):
        """Tracker.track_decision_outcome failure should not propagate."""
        mock_tracker = MagicMock()
        mock_tracker.track_decision_outcome.side_effect = RuntimeError(
            "tracking failed"
        )

        with (
            patch("temper_ai.observability.get_tracker", return_value=mock_tracker),
            patch(
                "temper_ai.observability._tracker_helpers.DecisionTrackingData",
                MagicMock(),
            ),
        ):
            # Should not raise
            track_portfolio_event(
                decision_type="test",
                decision_data={},
                outcome="ok",
            )

    def test_logs_debug_on_failure(self, caplog):
        """Debug log entry emitted when tracking fails."""
        import logging

        with (
            patch(
                "temper_ai.observability.get_tracker",
                side_effect=Exception("boom"),
            ),
            caplog.at_level(logging.DEBUG, logger="temper_ai.portfolio._tracking"),
        ):
            track_portfolio_event(
                decision_type="test",
                decision_data={},
                outcome="ok",
            )

        assert any("Portfolio tracking failed" in r.message for r in caplog.records)
