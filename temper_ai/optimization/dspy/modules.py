"""Module registry for DSPy prompt optimization."""

from collections.abc import Callable
from typing import Any

from temper_ai.optimization.dspy._schemas import PromptOptimizationConfig

ModuleBuilder = Callable[..., Any]

_DEFAULT_REWARD_SCORE = 1.0
_DEFAULT_MAX_ITERS = 20
_DEFAULT_PROGRAM_OF_THOUGHT_MAX_ITERS = 3
_DEFAULT_M = 3
_DEFAULT_TEMPERATURE = 0.7


def _build_reward_fn(metric_name: str | None) -> Callable:
    """Adapt a metric registry metric to DSPy's reward_fn signature.

    Returns a callable with signature (inputs_dict, prediction) -> float.
    If no metric_name, returns a default that always returns 1.0.
    """
    if not metric_name:

        def _default_reward(inputs_dict: Any, prediction: Any) -> float:
            return _DEFAULT_REWARD_SCORE

        return _default_reward

    from temper_ai.optimization.dspy.metrics import get_metric  # noqa: PLC0415

    metric_fn = get_metric(metric_name)

    def _adapted_reward(inputs_dict: Any, prediction: Any) -> float:
        result = metric_fn(inputs_dict, prediction)
        if isinstance(result, bool):
            return float(result)
        try:
            return float(result)
        except (TypeError, ValueError):
            return _DEFAULT_REWARD_SCORE

    return _adapted_reward


def _build_predict(dspy_mod: Any, sig: Any, config: PromptOptimizationConfig) -> Any:
    """Build a dspy.Predict module."""
    return dspy_mod.Predict(sig)


def _build_chain_of_thought(
    dspy_mod: Any,
    sig: Any,
    config: PromptOptimizationConfig,
) -> Any:
    """Build a dspy.ChainOfThought module."""
    return dspy_mod.ChainOfThought(sig)


def _build_program_of_thought(
    dspy_mod: Any,
    sig: Any,
    config: PromptOptimizationConfig,
) -> Any:
    """Build a dspy.ProgramOfThought module."""
    params = config.module_params or {}
    max_iters = params.get("max_iters", _DEFAULT_PROGRAM_OF_THOUGHT_MAX_ITERS)
    return dspy_mod.ProgramOfThought(sig, max_iters=max_iters)


def _build_multi_chain_comparison(
    dspy_mod: Any,
    sig: Any,
    config: PromptOptimizationConfig,
) -> Any:
    """Build a dspy.MultiChainComparison module."""
    params = config.module_params or {}
    m_val = params.get("M", _DEFAULT_M)
    temperature = params.get("temperature", _DEFAULT_TEMPERATURE)
    return dspy_mod.MultiChainComparison(sig, M=m_val, temperature=temperature)


def _build_react(dspy_mod: Any, sig: Any, config: PromptOptimizationConfig) -> Any:
    """Build a dspy.ReAct module."""
    params = config.module_params or {}
    tools = params.get("tools")
    if not tools:
        raise ValueError("ReAct module requires 'tools' in module_params")
    max_iters = params.get("max_iters", _DEFAULT_MAX_ITERS)
    return dspy_mod.ReAct(sig, tools=tools, max_iters=max_iters)


def _build_best_of_n(dspy_mod: Any, sig: Any, config: PromptOptimizationConfig) -> Any:
    """Build a dspy.BestOfN module wrapping a base module."""
    params = config.module_params or {}
    if "N" not in params:
        raise ValueError("BestOfN module requires 'N' in module_params")
    if "threshold" not in params:
        raise ValueError("BestOfN module requires 'threshold' in module_params")

    base_name = params.get("base_module", "predict")
    n_val = params["N"]
    threshold = params["threshold"]
    reward_metric = params.get("reward_metric")

    base_builder = get_module_builder(base_name)
    base = base_builder(dspy_mod, sig, config)
    reward_fn = _build_reward_fn(reward_metric)

    return dspy_mod.BestOfN(base, N=n_val, reward_fn=reward_fn, threshold=threshold)


def _build_refine(dspy_mod: Any, sig: Any, config: PromptOptimizationConfig) -> Any:
    """Build a dspy.Refine module wrapping a base module."""
    params = config.module_params or {}
    if "N" not in params:
        raise ValueError("Refine module requires 'N' in module_params")
    if "threshold" not in params:
        raise ValueError("Refine module requires 'threshold' in module_params")

    base_name = params.get("base_module", "predict")
    n_val = params["N"]
    threshold = params["threshold"]
    reward_metric = params.get("reward_metric")

    base_builder = get_module_builder(base_name)
    base = base_builder(dspy_mod, sig, config)
    reward_fn = _build_reward_fn(reward_metric)

    return dspy_mod.Refine(base, N=n_val, reward_fn=reward_fn, threshold=threshold)


_MODULE_REGISTRY: dict[str, ModuleBuilder] = {
    "predict": _build_predict,
    "chain_of_thought": _build_chain_of_thought,
    "program_of_thought": _build_program_of_thought,
    "multi_chain_comparison": _build_multi_chain_comparison,
    "react": _build_react,
    "best_of_n": _build_best_of_n,
    "refine": _build_refine,
}


def get_module_builder(name: str) -> ModuleBuilder:
    """Return the module builder for the given name.

    Raises ValueError if the name is not registered.
    """
    builder = _MODULE_REGISTRY.get(name)
    if builder is None:
        raise ValueError(
            f"Unknown module '{name}'. Available: {list_modules()}",
        )
    return builder


def register_module(name: str, builder: ModuleBuilder) -> None:
    """Register a module builder under the given name."""
    _MODULE_REGISTRY[name] = builder


def list_modules() -> list[str]:
    """Return a sorted list of all registered module names."""
    return sorted(_MODULE_REGISTRY.keys())
