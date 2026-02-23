"""Tests for experiment-workflow integration."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.experimentation._workflow_integration import (
    _extract_variant_overrides,
    assign_and_merge,
    track_experiment_completion,
)

# Patch targets: lazy imports inside each function resolve at the source module.
_SERVICE_PATH = "temper_ai.experimentation.service.ExperimentService"
_CONFIG_MANAGER_PATH = "temper_ai.experimentation.config_manager.ConfigManager"


class TestAssignAndMerge:

    def test_assignment_returns_merged_config(self):
        """Config overrides are applied when variant has them."""
        mock_service = MagicMock()
        mock_assignment = MagicMock()
        mock_assignment.variant_id = "v1"
        mock_service.assign_variant.return_value = mock_assignment

        mock_experiment = MagicMock()
        mock_variant = MagicMock()
        mock_variant.id = "v1"
        mock_variant.config_overrides = {"agent": {"temperature": 0.9}}
        mock_experiment.variants = [mock_variant]
        mock_service.get_experiment.return_value = mock_experiment

        base_config = {"agent": {"temperature": 0.7, "model": "gpt-4"}}
        expected_merged = {"agent": {"temperature": 0.9, "model": "gpt-4"}}

        with (
            patch(_SERVICE_PATH, return_value=mock_service),
            patch(_CONFIG_MANAGER_PATH) as MockCM,
        ):
            mock_cm = MagicMock()
            mock_cm.apply_overrides_safely.return_value = expected_merged
            MockCM.return_value = mock_cm

            merged, variant_id = assign_and_merge("exp1", "wf1", base_config)

        assert variant_id == "v1"
        mock_cm.apply_overrides_safely.assert_called_once()

    def test_no_assignment_returns_original(self):
        """When assignment returns None, original config unchanged."""
        mock_service = MagicMock()
        mock_service.assign_variant.return_value = None

        base_config = {"key": "value"}
        with patch(_SERVICE_PATH, return_value=mock_service):
            merged, variant_id = assign_and_merge("exp1", "wf1", base_config)

        assert merged is base_config
        assert variant_id is None

    def test_no_overrides_returns_original(self):
        """When variant has no config_overrides, original config unchanged."""
        mock_service = MagicMock()
        mock_assignment = MagicMock()
        mock_assignment.variant_id = "v1"
        mock_service.assign_variant.return_value = mock_assignment

        mock_experiment = MagicMock()
        mock_variant = MagicMock()
        mock_variant.id = "v1"
        mock_variant.config_overrides = None
        mock_experiment.variants = [mock_variant]
        mock_service.get_experiment.return_value = mock_experiment

        base_config = {"key": "value"}
        with patch(_SERVICE_PATH, return_value=mock_service):
            merged, variant_id = assign_and_merge("exp1", "wf1", base_config)

        assert merged is base_config
        assert variant_id == "v1"

    def test_no_experiment_returns_original(self):
        """When experiment lookup returns None, original config unchanged."""
        mock_service = MagicMock()
        mock_assignment = MagicMock()
        mock_assignment.variant_id = "v1"
        mock_service.assign_variant.return_value = mock_assignment
        mock_service.get_experiment.return_value = None

        base_config = {"key": "value"}
        with patch(_SERVICE_PATH, return_value=mock_service):
            merged, variant_id = assign_and_merge("exp1", "wf1", base_config)

        assert merged is base_config
        assert variant_id == "v1"

    def test_merged_config_returned_on_overrides(self):
        """Merged config from apply_overrides_safely is returned."""
        expected_merged = {"agent": {"temperature": 0.9, "model": "gpt-4"}}

        mock_service = MagicMock()
        mock_assignment = MagicMock()
        mock_assignment.variant_id = "v2"
        mock_service.assign_variant.return_value = mock_assignment

        mock_experiment = MagicMock()
        mock_variant = MagicMock()
        mock_variant.id = "v2"
        mock_variant.config_overrides = {"agent": {"temperature": 0.9}}
        mock_experiment.variants = [mock_variant]
        mock_service.get_experiment.return_value = mock_experiment

        with (
            patch(_SERVICE_PATH, return_value=mock_service),
            patch(_CONFIG_MANAGER_PATH) as MockCM,
        ):
            mock_cm = MagicMock()
            mock_cm.apply_overrides_safely.return_value = expected_merged
            MockCM.return_value = mock_cm

            merged, variant_id = assign_and_merge(
                "exp1",
                "wf1",
                {"agent": {"temperature": 0.7, "model": "gpt-4"}},
            )

        assert merged == expected_merged
        assert variant_id == "v2"


class TestExtractVariantOverrides:

    def test_matching_variant(self):
        experiment = MagicMock()
        variant = MagicMock()
        variant.id = "v1"
        variant.config_overrides = {"temperature": 0.9}
        experiment.variants = [variant]
        assert _extract_variant_overrides(experiment, "v1") == {"temperature": 0.9}

    def test_no_matching_variant(self):
        experiment = MagicMock()
        variant = MagicMock()
        variant.id = "v2"
        experiment.variants = [variant]
        assert _extract_variant_overrides(experiment, "v1") == {}

    def test_empty_variants(self):
        experiment = MagicMock()
        experiment.variants = []
        assert _extract_variant_overrides(experiment, "v1") == {}

    def test_variant_with_empty_overrides(self):
        experiment = MagicMock()
        variant = MagicMock()
        variant.id = "v1"
        variant.config_overrides = {}
        experiment.variants = [variant]
        assert _extract_variant_overrides(experiment, "v1") == {}

    def test_variant_id_coerced_to_string(self):
        """Variant ID comparison uses string conversion."""
        experiment = MagicMock()
        variant = MagicMock()
        variant.id = 42
        variant.config_overrides = {"temperature": 0.5}
        experiment.variants = [variant]
        assert _extract_variant_overrides(experiment, "42") == {"temperature": 0.5}

    def test_no_variants_attribute(self):
        experiment = MagicMock(spec=[])
        assert _extract_variant_overrides(experiment, "v1") == {}


class TestTrackExperimentCompletion:

    def test_tracks_metrics(self):
        """Completion tracking calls service correctly."""
        mock_service = MagicMock()
        with patch(_SERVICE_PATH, return_value=mock_service):
            track_experiment_completion(
                "exp1",
                "wf1",
                {"total_tokens": 500, "total_cost": 0.05},
                duration_seconds=12.5,
            )
        mock_service.track_execution_complete.assert_called_once()
        call_kwargs = mock_service.track_execution_complete.call_args[1]
        assert call_kwargs["workflow_id"] == "wf1"
        assert call_kwargs["metrics"]["duration_seconds"] == 12.5
        assert call_kwargs["metrics"]["total_tokens"] == 500.0

    def test_tracks_total_cost(self):
        """total_cost is extracted and converted to float."""
        mock_service = MagicMock()
        with patch(_SERVICE_PATH, return_value=mock_service):
            track_experiment_completion(
                "exp1",
                "wf1",
                {"total_cost": 0.123},
                duration_seconds=5.0,
            )
        call_kwargs = mock_service.track_execution_complete.call_args[1]
        assert call_kwargs["metrics"]["total_cost"] == pytest.approx(0.123)

    def test_tracks_duration_only_when_no_extra_keys(self):
        """Only duration_seconds included when result has no token/cost keys."""
        mock_service = MagicMock()
        with patch(_SERVICE_PATH, return_value=mock_service):
            track_experiment_completion(
                "exp1",
                "wf1",
                {},
                duration_seconds=3.0,
            )
        call_kwargs = mock_service.track_execution_complete.call_args[1]
        assert call_kwargs["metrics"] == {"duration_seconds": 3.0}
        assert "total_tokens" not in call_kwargs["metrics"]

    def test_non_dict_result_skips_extra_metrics(self):
        """Empty result dict only tracks duration."""
        mock_service = MagicMock()
        with patch(_SERVICE_PATH, return_value=mock_service):
            track_experiment_completion(
                "exp1",
                "wf1",
                {},
                duration_seconds=7.5,
            )
        call_kwargs = mock_service.track_execution_complete.call_args[1]
        assert call_kwargs["metrics"]["duration_seconds"] == 7.5
