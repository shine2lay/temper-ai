"""Tests for lifecycle experimenter."""

from unittest.mock import MagicMock

import pytest

from src.lifecycle._schemas import LifecycleProfile
from src.lifecycle.experiment import LifecycleExperimenter


@pytest.fixture
def mock_service():
    return MagicMock()


@pytest.fixture
def experimenter(mock_service):
    return LifecycleExperimenter(experiment_service=mock_service)


class TestLifecycleExperimenter:
    """Tests for LifecycleExperimenter."""

    def test_control_returns_none(self, experimenter, mock_service):
        mock_service.assign_variant.return_value = MagicMock(variant_name="control")
        result = experimenter.get_adapted_profile(
            "exp-1", "wf-1",
            {"lean": LifecycleProfile(name="lean")},
        )
        assert result is None

    def test_treatment_returns_profile(self, experimenter, mock_service):
        mock_service.assign_variant.return_value = MagicMock(variant_name="lean")
        profile = LifecycleProfile(name="lean", description="Lean profile")
        result = experimenter.get_adapted_profile(
            "exp-1", "wf-1",
            {"lean": profile},
        )
        assert result is not None
        assert result.name == "lean"

    def test_unknown_variant_returns_none(self, experimenter, mock_service):
        mock_service.assign_variant.return_value = MagicMock(variant_name="unknown")
        result = experimenter.get_adapted_profile(
            "exp-1", "wf-1",
            {"lean": LifecycleProfile(name="lean")},
        )
        assert result is None

    def test_no_assignment_returns_none(self, experimenter, mock_service):
        mock_service.assign_variant.return_value = None
        result = experimenter.get_adapted_profile("exp-1", "wf-1")
        assert result is None

    def test_assignment_failure_returns_none(self, experimenter, mock_service):
        mock_service.assign_variant.side_effect = RuntimeError("fail")
        result = experimenter.get_adapted_profile("exp-1", "wf-1")
        assert result is None

    def test_track_outcome(self, experimenter, mock_service):
        experimenter.track_outcome("exp-1", "wf-1", {"duration": 42.0})
        mock_service.record_metric.assert_called_once()

    def test_track_outcome_failure_handled(self, experimenter, mock_service):
        mock_service.record_metric.side_effect = RuntimeError("fail")
        experimenter.track_outcome("exp-1", "wf-1", {"duration": 42.0})
        assert mock_service.record_metric.called

    def test_no_profiles_dict(self, experimenter, mock_service):
        mock_service.assign_variant.return_value = MagicMock(variant_name="lean")
        result = experimenter.get_adapted_profile("exp-1", "wf-1")
        assert result is None
