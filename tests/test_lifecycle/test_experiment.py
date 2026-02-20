"""Tests for lifecycle experimenter."""

from unittest.mock import MagicMock

import pytest

from temper_ai.lifecycle._schemas import LifecycleProfile
from temper_ai.lifecycle.experiment import LifecycleExperimenter


def _make_assignment(variant_id: str) -> MagicMock:
    """Create a mock VariantAssignment with the given variant_id."""
    return MagicMock(variant_id=variant_id)


def _make_variant(variant_id: str, variant_name: str) -> MagicMock:
    """Create a mock Variant with id and name set via configure_mock.

    Note: ``name`` is a reserved keyword argument for MagicMock, so we must
    use ``configure_mock`` to set it as a plain string attribute.
    """
    mock_variant = MagicMock()
    mock_variant.id = variant_id
    mock_variant.configure_mock(name=variant_name)
    return mock_variant


def _make_experiment_with_variant(variant_id: str, variant_name: str) -> MagicMock:
    """Create a mock Experiment whose variants list contains one variant."""
    mock_experiment = MagicMock()
    mock_experiment.variants = [_make_variant(variant_id, variant_name)]
    return mock_experiment


@pytest.fixture
def mock_service():
    return MagicMock()


@pytest.fixture
def experimenter(mock_service):
    return LifecycleExperimenter(experiment_service=mock_service)


class TestLifecycleExperimenter:
    """Tests for LifecycleExperimenter."""

    def test_control_returns_none(self, experimenter, mock_service):
        mock_service.assign_variant.return_value = _make_assignment("var-ctrl")
        mock_service.get_experiment.return_value = _make_experiment_with_variant(
            "var-ctrl", "control"
        )
        result = experimenter.get_adapted_profile(
            "exp-1", "wf-1",
            {"lean": LifecycleProfile(name="lean")},
        )
        assert result is None

    def test_treatment_returns_profile(self, experimenter, mock_service):
        mock_service.assign_variant.return_value = _make_assignment("var-lean")
        mock_service.get_experiment.return_value = _make_experiment_with_variant(
            "var-lean", "lean"
        )
        profile = LifecycleProfile(name="lean", description="Lean profile")
        result = experimenter.get_adapted_profile(
            "exp-1", "wf-1",
            {"lean": profile},
        )
        assert result is not None
        assert result.name == "lean"

    def test_unknown_variant_returns_none(self, experimenter, mock_service):
        mock_service.assign_variant.return_value = _make_assignment("var-unknown")
        mock_service.get_experiment.return_value = _make_experiment_with_variant(
            "var-unknown", "unknown"
        )
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

    def test_track_outcome_calls_track_execution_complete(self, experimenter, mock_service):
        experimenter.track_outcome("exp-1", "wf-1", {"duration": 42.0})
        mock_service.track_execution_complete.assert_called_once_with(
            "wf-1", {"duration": 42.0}
        )

    def test_track_outcome_failure_handled(self, experimenter, mock_service):
        mock_service.track_execution_complete.side_effect = RuntimeError("fail")
        # Should not propagate the exception — silent failure handling
        experimenter.track_outcome("exp-1", "wf-1", {"duration": 42.0})

    def test_no_profiles_dict(self, experimenter, mock_service):
        mock_service.assign_variant.return_value = _make_assignment("var-lean")
        mock_service.get_experiment.return_value = _make_experiment_with_variant(
            "var-lean", "lean"
        )
        result = experimenter.get_adapted_profile("exp-1", "wf-1")
        assert result is None

    def test_resolve_variant_name_fallback_on_no_experiment(
        self, experimenter, mock_service
    ):
        """variant_id is returned when experiment cannot be resolved."""
        mock_service.get_experiment.return_value = None
        name = experimenter._resolve_variant_name("exp-1", "var-xyz")
        assert name == "var-xyz"

    def test_resolve_variant_name_fallback_on_service_error(
        self, experimenter, mock_service
    ):
        """variant_id is returned when service raises."""
        mock_service.get_experiment.side_effect = RuntimeError("db error")
        name = experimenter._resolve_variant_name("exp-1", "var-xyz")
        assert name == "var-xyz"
