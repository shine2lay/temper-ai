"""Tests for experiment tracking helpers."""

from unittest.mock import MagicMock, call

from temper_ai.optimization._experiment_helpers import (
    METRIC_OPTIMIZATION_SCORE,
    MIN_SAMPLE_SIZE_SINGLE,
    STATUS_COMPLETED,
    create_refinement_experiment,
    create_selection_experiment,
    create_tuning_experiment,
    create_workflow_id,
    finalize_experiment,
    generate_experiment_name,
    track_run_result,
)


class TestGenerateExperimentName:
    def test_format(self):
        name = generate_experiment_name("selection", "quality_eval")
        parts = name.split("-")
        assert parts[0] == "selection"
        assert "quality_eval" in name

    def test_unique_per_call(self):
        name1 = generate_experiment_name("tuning", "eval")
        name2 = generate_experiment_name("tuning", "eval")
        # Names include timestamp — same second means same name, so just check format
        assert name1.startswith("tuning-")
        assert name2.startswith("tuning-")


class TestCreateWorkflowId:
    def test_format(self):
        wf_id = create_workflow_id("exp-abc", 0)
        assert wf_id == "opt-exp-abc-run-0"

    def test_different_indices(self):
        wf0 = create_workflow_id("exp-1", 0)
        wf1 = create_workflow_id("exp-1", 1)
        assert wf0 != wf1


class TestCreateSelectionExperiment:
    def test_creates_and_starts(self):
        service = MagicMock()
        service.create_experiment.return_value = "exp-sel-1"

        exp_id = create_selection_experiment(service, "quality", 3)  # noqa

        assert exp_id == "exp-sel-1"
        service.create_experiment.assert_called_once()
        call_kwargs = service.create_experiment.call_args[1]
        assert call_kwargs["primary_metric"] == METRIC_OPTIMIZATION_SCORE
        assert call_kwargs["min_sample_size_per_variant"] == MIN_SAMPLE_SIZE_SINGLE
        assert len(call_kwargs["variants"]) == 3  # noqa
        service.start_experiment.assert_called_once_with("exp-sel-1")

    def test_variant_names(self):
        service = MagicMock()
        service.create_experiment.return_value = "exp-1"

        create_selection_experiment(service, "eval", 2)  # noqa

        variants = service.create_experiment.call_args[1]["variants"]
        names = [v["name"] for v in variants]
        assert names == ["run-0", "run-1"]


class TestCreateRefinementExperiment:
    def test_creates_with_baseline_plus_iterations(self):
        service = MagicMock()
        service.create_experiment.return_value = "exp-ref-1"

        exp_id = create_refinement_experiment(service, "quality", 2)  # noqa

        assert exp_id == "exp-ref-1"
        call_kwargs = service.create_experiment.call_args[1]
        variants = call_kwargs["variants"]
        assert variants[0]["name"] == "baseline"
        assert variants[1]["name"] == "iteration-1"
        assert variants[2]["name"] == "iteration-2"  # noqa
        assert call_kwargs["min_sample_size_per_variant"] == MIN_SAMPLE_SIZE_SINGLE
        service.start_experiment.assert_called_once_with("exp-ref-1")


class TestCreateTuningExperiment:
    def test_creates_with_strategy_names(self):
        service = MagicMock()
        service.create_experiment.return_value = "exp-tun-1"

        strategies = [{"name": "fast"}, {"name": "slow"}]
        exp_id = create_tuning_experiment(service, "perf", strategies, 2)  # noqa

        assert exp_id == "exp-tun-1"
        call_kwargs = service.create_experiment.call_args[1]
        variants = call_kwargs["variants"]
        assert variants[0]["name"] == "fast"
        assert variants[1]["name"] == "slow"
        # Tuning uses default min_sample_size (not MIN_SAMPLE_SIZE_SINGLE)
        assert "min_sample_size_per_variant" not in call_kwargs
        service.start_experiment.assert_called_once_with("exp-tun-1")


class TestTrackRunResult:
    def test_calls_track_execution_complete(self):
        service = MagicMock()

        track_run_result(service, "wf-1", 0.85)

        service.track_execution_complete.assert_called_once_with(
            workflow_id="wf-1",
            metrics={METRIC_OPTIMIZATION_SCORE: 0.85},
            status=STATUS_COMPLETED,
        )


class TestFinalizeExperiment:
    def test_gets_results_and_stops(self):
        service = MagicMock()
        service.get_experiment_results.return_value = {
            "recommended_winner": "run-1",
            "confidence": 0.95,
        }

        results = finalize_experiment(service, "exp-1")

        assert results["recommended_winner"] == "run-1"
        service.get_experiment_results.assert_called_once_with("exp-1")
        service.stop_experiment.assert_called_once_with(
            "exp-1", winner="run-1"
        )

    def test_no_winner(self):
        service = MagicMock()
        service.get_experiment_results.return_value = {
            "confidence": 0.3,
        }

        results = finalize_experiment(service, "exp-2")

        service.stop_experiment.assert_called_once_with(
            "exp-2", winner=None
        )
        assert results["confidence"] == 0.3
