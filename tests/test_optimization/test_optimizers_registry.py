"""Tests for temper_ai.optimization.dspy.optimizers module."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from temper_ai.optimization.dspy.optimizers import (
    DEFAULT_COPRO_BREADTH,
    DEFAULT_COPRO_DEPTH,
    DEFAULT_SIMBA_MAX_STEPS,
    DEFAULT_SIMBA_NUM_CANDIDATES,
    _run_bootstrap,
    _run_copro,
    _run_gepa,
    _run_mipro,
    _run_simba,
    get_optimizer,
    list_optimizers,
    register_optimizer,
)

# ---------------------------------------------------------------------------
# Helpers — build mock config objects
# ---------------------------------------------------------------------------


def _make_config(
    max_demos: int = 3,
    optimizer_params: Any = None,
) -> MagicMock:
    cfg = MagicMock()
    cfg.max_demos = max_demos
    cfg.optimizer_params = optimizer_params
    return cfg


def _make_dspy() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# _run_bootstrap
# ---------------------------------------------------------------------------


class TestRunBootstrap:
    def test_calls_bootstrap_few_shot_with_correct_params(self) -> None:
        dspy_mod = _make_dspy()
        program = MagicMock()
        trainset = [MagicMock()]
        metric_fn = MagicMock()
        config = _make_config(max_demos=5)

        _run_bootstrap(dspy_mod, program, trainset, metric_fn, config)

        dspy_mod.BootstrapFewShot.assert_called_once_with(
            metric=metric_fn,
            max_bootstrapped_demos=5,
        )
        dspy_mod.BootstrapFewShot.return_value.compile.assert_called_once_with(
            program,
            trainset=trainset,
        )

    def test_returns_compiled_program(self) -> None:
        dspy_mod = _make_dspy()
        compiled = MagicMock()
        dspy_mod.BootstrapFewShot.return_value.compile.return_value = compiled

        result = _run_bootstrap(dspy_mod, MagicMock(), [], MagicMock(), _make_config())

        assert result is compiled


# ---------------------------------------------------------------------------
# _run_mipro
# ---------------------------------------------------------------------------


class TestRunMipro:
    def test_calls_mipro_v2_with_auto_light(self) -> None:
        dspy_mod = _make_dspy()
        program = MagicMock()
        trainset = [MagicMock()]
        metric_fn = MagicMock()
        config = _make_config(max_demos=4)

        _run_mipro(dspy_mod, program, trainset, metric_fn, config)

        dspy_mod.MIPROv2.assert_called_once_with(metric=metric_fn, auto="light")
        dspy_mod.MIPROv2.return_value.compile.assert_called_once_with(
            program,
            trainset=trainset,
            max_bootstrapped_demos=4,
            requires_permission_to_run=False,
        )

    def test_returns_compiled_program(self) -> None:
        dspy_mod = _make_dspy()
        compiled = MagicMock()
        dspy_mod.MIPROv2.return_value.compile.return_value = compiled

        result = _run_mipro(dspy_mod, MagicMock(), [], MagicMock(), _make_config())

        assert result is compiled


# ---------------------------------------------------------------------------
# _run_copro
# ---------------------------------------------------------------------------


class TestRunCopro:
    def test_uses_defaults_when_no_params(self) -> None:
        dspy_mod = _make_dspy()
        config = _make_config(optimizer_params=None)

        _run_copro(dspy_mod, MagicMock(), [], MagicMock(), config)

        dspy_mod.COPRO.assert_called_once_with(
            metric=dspy_mod.COPRO.call_args[1]["metric"],
            breadth=DEFAULT_COPRO_BREADTH,
            depth=DEFAULT_COPRO_DEPTH,
        )

    def test_reads_breadth_and_depth_from_params(self) -> None:
        dspy_mod = _make_dspy()
        config = _make_config(optimizer_params={"breadth": 15, "depth": 5})

        _run_copro(dspy_mod, MagicMock(), [], MagicMock(), config)

        dspy_mod.COPRO.assert_called_once_with(
            metric=dspy_mod.COPRO.call_args[1]["metric"],
            breadth=15,
            depth=5,
        )

    def test_passes_eval_kwargs_empty_dict(self) -> None:
        dspy_mod = _make_dspy()
        config = _make_config()
        program = MagicMock()
        trainset = [MagicMock()]

        _run_copro(dspy_mod, program, trainset, MagicMock(), config)

        dspy_mod.COPRO.return_value.compile.assert_called_once_with(
            program,
            trainset=trainset,
            eval_kwargs={},
        )

    def test_returns_compiled_program(self) -> None:
        dspy_mod = _make_dspy()
        compiled = MagicMock()
        dspy_mod.COPRO.return_value.compile.return_value = compiled

        result = _run_copro(dspy_mod, MagicMock(), [], MagicMock(), _make_config())

        assert result is compiled


# ---------------------------------------------------------------------------
# _run_simba
# ---------------------------------------------------------------------------


class TestRunSimba:
    def test_uses_defaults_when_no_params(self) -> None:
        dspy_mod = _make_dspy()
        config = _make_config(max_demos=3, optimizer_params=None)

        _run_simba(dspy_mod, MagicMock(), [], MagicMock(), config)

        dspy_mod.SIMBA.assert_called_once_with(
            metric=dspy_mod.SIMBA.call_args[1]["metric"],
            num_candidates=DEFAULT_SIMBA_NUM_CANDIDATES,
            max_steps=DEFAULT_SIMBA_MAX_STEPS,
            max_demos=3,
        )

    def test_reads_num_candidates_and_max_steps_from_params(self) -> None:
        dspy_mod = _make_dspy()
        config = _make_config(optimizer_params={"num_candidates": 12, "max_steps": 20})

        _run_simba(dspy_mod, MagicMock(), [], MagicMock(), config)

        dspy_mod.SIMBA.assert_called_once_with(
            metric=dspy_mod.SIMBA.call_args[1]["metric"],
            num_candidates=12,
            max_steps=20,
            max_demos=config.max_demos,
        )

    def test_returns_compiled_program(self) -> None:
        dspy_mod = _make_dspy()
        compiled = MagicMock()
        dspy_mod.SIMBA.return_value.compile.return_value = compiled

        result = _run_simba(dspy_mod, MagicMock(), [], MagicMock(), _make_config())

        assert result is compiled


# ---------------------------------------------------------------------------
# _run_gepa
# ---------------------------------------------------------------------------


class TestRunGepa:
    def test_passes_valset_kwarg_through(self) -> None:
        dspy_mod = _make_dspy()
        program = MagicMock()
        trainset = [MagicMock()]
        valset = [MagicMock(), MagicMock()]
        config = _make_config()

        _run_gepa(dspy_mod, program, trainset, MagicMock(), config, valset=valset)

        dspy_mod.GEPA.return_value.compile.assert_called_once_with(
            program,
            trainset=trainset,
            valset=valset,
        )

    def test_calls_gepa_with_auto_light(self) -> None:
        dspy_mod = _make_dspy()
        metric_fn = MagicMock()
        config = _make_config()

        _run_gepa(dspy_mod, MagicMock(), [], metric_fn, config)

        dspy_mod.GEPA.assert_called_once_with(metric=metric_fn, auto="light")

    def test_returns_compiled_program(self) -> None:
        dspy_mod = _make_dspy()
        compiled = MagicMock()
        dspy_mod.GEPA.return_value.compile.return_value = compiled

        result = _run_gepa(dspy_mod, MagicMock(), [], MagicMock(), _make_config())

        assert result is compiled


# ---------------------------------------------------------------------------
# get_optimizer dispatch
# ---------------------------------------------------------------------------


class TestGetOptimizerDispatch:
    def test_bootstrap_returns_callable(self) -> None:
        runner = get_optimizer("bootstrap")
        assert callable(runner)

    def test_mipro_returns_callable(self) -> None:
        runner = get_optimizer("mipro")
        assert callable(runner)

    def test_copro_returns_callable(self) -> None:
        runner = get_optimizer("copro")
        assert callable(runner)

    def test_simba_returns_callable(self) -> None:
        runner = get_optimizer("simba")
        assert callable(runner)

    def test_gepa_returns_callable(self) -> None:
        runner = get_optimizer("gepa")
        assert callable(runner)

    def test_unknown_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown_optimizer"):
            get_optimizer("unknown_optimizer")


# ---------------------------------------------------------------------------
# register_optimizer
# ---------------------------------------------------------------------------


class TestRegisterOptimizer:
    def test_custom_optimizer_registered_and_retrieved(self) -> None:
        def _my_runner(
            dspy_mod: Any,
            program: Any,
            trainset: list,
            metric_fn: Any,
            config: Any,
            **kwargs: Any,
        ) -> str:
            return "custom_result"

        register_optimizer("custom_test_optimizer", _my_runner)
        runner = get_optimizer("custom_test_optimizer")
        assert callable(runner)
        assert runner(None, None, [], None, None) == "custom_result"

    def test_registered_optimizer_appears_in_list(self) -> None:
        register_optimizer("custom_for_list_check", lambda *a, **kw: None)
        assert "custom_for_list_check" in list_optimizers()


# ---------------------------------------------------------------------------
# list_optimizers
# ---------------------------------------------------------------------------


class TestListOptimizers:
    def test_returns_sorted_list(self) -> None:
        optimizers = list_optimizers()
        assert optimizers == sorted(optimizers)

    def test_all_five_builtins_present(self) -> None:
        optimizers = list_optimizers()
        for name in ("bootstrap", "mipro", "copro", "simba", "gepa"):
            assert name in optimizers
