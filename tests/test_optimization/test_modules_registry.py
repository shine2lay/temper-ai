"""Tests for the DSPy module registry."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.optimization.dspy._schemas import PromptOptimizationConfig
from temper_ai.optimization.dspy.modules import (
    _build_best_of_n,
    _build_chain_of_thought,
    _build_multi_chain_comparison,
    _build_predict,
    _build_program_of_thought,
    _build_react,
    _build_refine,
    _build_reward_fn,
    get_module_builder,
    list_modules,
    register_module,
)


def _make_config(**kwargs) -> PromptOptimizationConfig:
    """Return a PromptOptimizationConfig with optional overrides."""
    return PromptOptimizationConfig(**kwargs)


def _make_mock_dspy() -> MagicMock:
    """Return a fresh MagicMock representing the dspy module."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Simple module builders
# ---------------------------------------------------------------------------


class TestBuildPredict:
    def test_calls_dspy_predict_with_signature(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config()

        result = _build_predict(dspy_mod, sig, config)

        dspy_mod.Predict.assert_called_once_with(sig)
        assert result is dspy_mod.Predict.return_value

    def test_returns_predict_instance(self):
        dspy_mod = _make_mock_dspy()
        config = _make_config()
        result = _build_predict(dspy_mod, "input -> output", config)
        assert result is not None


class TestBuildChainOfThought:
    def test_calls_chain_of_thought_with_signature(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config()

        result = _build_chain_of_thought(dspy_mod, sig, config)

        dspy_mod.ChainOfThought.assert_called_once_with(sig)
        assert result is dspy_mod.ChainOfThought.return_value

    def test_returns_module_instance(self):
        dspy_mod = _make_mock_dspy()
        config = _make_config()
        result = _build_chain_of_thought(dspy_mod, "q -> a", config)
        assert result is not None


class TestBuildProgramOfThought:
    def test_uses_default_max_iters(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config()

        _build_program_of_thought(dspy_mod, sig, config)

        dspy_mod.ProgramOfThought.assert_called_once_with(sig, max_iters=3)

    def test_uses_custom_max_iters_from_module_params(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"max_iters": 5})

        _build_program_of_thought(dspy_mod, sig, config)

        dspy_mod.ProgramOfThought.assert_called_once_with(sig, max_iters=5)

    def test_returns_module_instance(self):
        dspy_mod = _make_mock_dspy()
        config = _make_config()
        result = _build_program_of_thought(dspy_mod, "q -> a", config)
        assert result is not None


class TestBuildMultiChainComparison:
    def test_uses_default_m_and_temperature(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config()

        _build_multi_chain_comparison(dspy_mod, sig, config)

        dspy_mod.MultiChainComparison.assert_called_once_with(sig, M=3, temperature=0.7)

    def test_uses_custom_m_and_temperature(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"M": 5, "temperature": 0.9})

        _build_multi_chain_comparison(dspy_mod, sig, config)

        dspy_mod.MultiChainComparison.assert_called_once_with(sig, M=5, temperature=0.9)

    def test_returns_module_instance(self):
        dspy_mod = _make_mock_dspy()
        config = _make_config()
        result = _build_multi_chain_comparison(dspy_mod, "q -> a", config)
        assert result is not None


# ---------------------------------------------------------------------------
# Tool-using module builders
# ---------------------------------------------------------------------------


class TestBuildReAct:
    def test_raises_value_error_when_no_tools(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config()

        with pytest.raises(ValueError, match="ReAct module requires 'tools'"):
            _build_react(dspy_mod, sig, config)

    def test_raises_value_error_when_tools_is_empty_list(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"tools": []})

        with pytest.raises(ValueError, match="ReAct module requires 'tools'"):
            _build_react(dspy_mod, sig, config)

    def test_builds_with_tools_provided(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        mock_tool = MagicMock()
        config = _make_config(module_params={"tools": [mock_tool]})

        result = _build_react(dspy_mod, sig, config)

        dspy_mod.ReAct.assert_called_once_with(sig, tools=[mock_tool], max_iters=20)
        assert result is dspy_mod.ReAct.return_value

    def test_uses_custom_max_iters(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        mock_tool = MagicMock()
        config = _make_config(module_params={"tools": [mock_tool], "max_iters": 10})

        _build_react(dspy_mod, sig, config)

        dspy_mod.ReAct.assert_called_once_with(sig, tools=[mock_tool], max_iters=10)


# ---------------------------------------------------------------------------
# Wrapper module builders
# ---------------------------------------------------------------------------


class TestBuildBestOfN:
    def test_raises_value_error_when_n_missing(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"threshold": 0.8})

        with pytest.raises(ValueError, match="'N' in module_params"):
            _build_best_of_n(dspy_mod, sig, config)

    def test_raises_value_error_when_threshold_missing(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"N": 3})

        with pytest.raises(ValueError, match="'threshold' in module_params"):
            _build_best_of_n(dspy_mod, sig, config)

    def test_builds_base_module_then_wraps(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"N": 3, "threshold": 0.8})

        _build_best_of_n(dspy_mod, sig, config)

        # Default base_module is "predict", so Predict should be called first
        dspy_mod.Predict.assert_called_once_with(sig)
        # Then BestOfN should be called wrapping the Predict result
        dspy_mod.BestOfN.assert_called_once()
        call_kwargs = dspy_mod.BestOfN.call_args
        assert call_kwargs[1]["N"] == 3
        assert call_kwargs[1]["threshold"] == 0.8

    def test_uses_custom_base_module(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(
            module_params={"N": 2, "threshold": 0.5, "base_module": "chain_of_thought"},
        )

        _build_best_of_n(dspy_mod, sig, config)

        dspy_mod.ChainOfThought.assert_called_once_with(sig)
        dspy_mod.BestOfN.assert_called_once()

    def test_returns_best_of_n_instance(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"N": 3, "threshold": 0.8})

        result = _build_best_of_n(dspy_mod, sig, config)

        assert result is dspy_mod.BestOfN.return_value

    def test_n_forwarded_correctly(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"N": 5, "threshold": 0.7})

        _build_best_of_n(dspy_mod, sig, config)

        call_kwargs = dspy_mod.BestOfN.call_args[1]
        assert call_kwargs["N"] == 5

    def test_threshold_forwarded_correctly(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"N": 3, "threshold": 0.95})

        _build_best_of_n(dspy_mod, sig, config)

        call_kwargs = dspy_mod.BestOfN.call_args[1]
        assert call_kwargs["threshold"] == 0.95


class TestBuildRefine:
    def test_raises_value_error_when_n_missing(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"threshold": 0.8})

        with pytest.raises(ValueError, match="'N' in module_params"):
            _build_refine(dspy_mod, sig, config)

    def test_raises_value_error_when_threshold_missing(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"N": 3})

        with pytest.raises(ValueError, match="'threshold' in module_params"):
            _build_refine(dspy_mod, sig, config)

    def test_builds_base_module_then_wraps(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"N": 3, "threshold": 0.8})

        _build_refine(dspy_mod, sig, config)

        dspy_mod.Predict.assert_called_once_with(sig)
        dspy_mod.Refine.assert_called_once()
        call_kwargs = dspy_mod.Refine.call_args[1]
        assert call_kwargs["N"] == 3
        assert call_kwargs["threshold"] == 0.8

    def test_returns_refine_instance(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"N": 3, "threshold": 0.8})

        result = _build_refine(dspy_mod, sig, config)

        assert result is dspy_mod.Refine.return_value

    def test_n_and_threshold_forwarded_correctly(self):
        dspy_mod = _make_mock_dspy()
        sig = "question -> answer"
        config = _make_config(module_params={"N": 4, "threshold": 0.6})

        _build_refine(dspy_mod, sig, config)

        call_kwargs = dspy_mod.Refine.call_args[1]
        assert call_kwargs["N"] == 4
        assert call_kwargs["threshold"] == 0.6


# ---------------------------------------------------------------------------
# Reward function helper
# ---------------------------------------------------------------------------


class TestBuildRewardFn:
    def test_default_reward_fn_returns_one(self):
        reward_fn = _build_reward_fn(None)
        result = reward_fn({}, MagicMock())
        assert result == 1.0

    def test_default_reward_fn_returns_one_for_empty_string(self):
        reward_fn = _build_reward_fn("")
        result = reward_fn({}, MagicMock())
        assert result == 1.0

    def test_adapted_reward_fn_converts_bool_true(self):
        mock_metric = MagicMock(return_value=True)
        with patch(
            "temper_ai.optimization.dspy.metrics.get_metric",
            return_value=mock_metric,
        ):
            reward_fn = _build_reward_fn("exact_match")
            result = reward_fn({}, MagicMock())
        assert result == 1.0

    def test_adapted_reward_fn_converts_bool_false(self):
        mock_metric = MagicMock(return_value=False)
        with patch(
            "temper_ai.optimization.dspy.metrics.get_metric",
            return_value=mock_metric,
        ):
            reward_fn = _build_reward_fn("exact_match")
            result = reward_fn({}, MagicMock())
        assert result == 0.0

    def test_adapted_reward_fn_converts_float(self):
        mock_metric = MagicMock(return_value=0.75)
        with patch(
            "temper_ai.optimization.dspy.metrics.get_metric",
            return_value=mock_metric,
        ):
            reward_fn = _build_reward_fn("fuzzy")
            result = reward_fn({}, MagicMock())
        assert result == 0.75


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------


class TestGetModuleBuilder:
    @pytest.mark.parametrize(
        "name",
        [
            "predict",
            "chain_of_thought",
            "program_of_thought",
            "multi_chain_comparison",
            "react",
            "best_of_n",
            "refine",
        ],
    )
    def test_dispatch_all_seven_names(self, name: str):
        builder = get_module_builder(name)
        assert callable(builder)

    def test_predict_builder_is_correct(self):
        builder = get_module_builder("predict")
        assert builder is _build_predict

    def test_chain_of_thought_builder_is_correct(self):
        builder = get_module_builder("chain_of_thought")
        assert builder is _build_chain_of_thought

    def test_react_builder_is_correct(self):
        builder = get_module_builder("react")
        assert builder is _build_react

    def test_raises_value_error_for_unknown_name(self):
        with pytest.raises(ValueError, match="Unknown module 'unknown_module'"):
            get_module_builder("unknown_module")

    def test_error_message_lists_available_modules(self):
        with pytest.raises(ValueError) as exc_info:
            get_module_builder("nonexistent")
        assert "predict" in str(exc_info.value)


class TestRegisterModule:
    def test_register_custom_module(self):
        custom_builder = MagicMock()
        register_module("custom_test_module", custom_builder)

        retrieved = get_module_builder("custom_test_module")
        assert retrieved is custom_builder

    def test_registered_module_appears_in_list(self):
        register_module("another_test_module", MagicMock())
        modules = list_modules()
        assert "another_test_module" in modules

    def test_register_overwrites_existing(self):
        new_builder = MagicMock()
        register_module("predict", new_builder)
        retrieved = get_module_builder("predict")
        assert retrieved is new_builder
        # Restore original for other tests
        from temper_ai.optimization.dspy.modules import _build_predict as orig

        register_module("predict", orig)


class TestListModules:
    def test_returns_sorted_list(self):
        modules = list_modules()
        assert modules == sorted(modules)

    def test_contains_all_seven_core_modules(self):
        modules = list_modules()
        expected = {
            "predict",
            "chain_of_thought",
            "program_of_thought",
            "multi_chain_comparison",
            "react",
            "best_of_n",
            "refine",
        }
        assert expected.issubset(set(modules))

    def test_returns_list_type(self):
        result = list_modules()
        assert isinstance(result, list)

    def test_no_duplicates(self):
        modules = list_modules()
        assert len(modules) == len(set(modules))
