"""Optimizer registry for DSPy prompt optimization."""

from collections.abc import Callable
from typing import Any

from temper_ai.optimization.dspy._schemas import PromptOptimizationConfig

OptimizerRunner = Callable[..., Any]

DEFAULT_COPRO_BREADTH = 10
DEFAULT_COPRO_DEPTH = 3
DEFAULT_SIMBA_NUM_CANDIDATES = 6
DEFAULT_SIMBA_MAX_STEPS = 8


def _run_bootstrap(
    dspy_mod: Any,
    program: Any,
    trainset: list,
    metric_fn: Callable,
    config: PromptOptimizationConfig,
    **kwargs: Any,
) -> Any:
    """Compile using BootstrapFewShot optimizer."""
    optimizer = dspy_mod.BootstrapFewShot(
        metric=metric_fn,
        max_bootstrapped_demos=config.max_demos,
    )
    return optimizer.compile(program, trainset=trainset)


def _run_mipro(
    dspy_mod: Any,
    program: Any,
    trainset: list,
    metric_fn: Callable,
    config: PromptOptimizationConfig,
    **kwargs: Any,
) -> Any:
    """Compile using MIPROv2 optimizer."""
    optimizer = dspy_mod.MIPROv2(metric=metric_fn, auto="light")
    return optimizer.compile(
        program,
        trainset=trainset,
        max_bootstrapped_demos=config.max_demos,
        requires_permission_to_run=False,
    )


def _run_copro(
    dspy_mod: Any,
    program: Any,
    trainset: list,
    metric_fn: Callable,
    config: PromptOptimizationConfig,
    **kwargs: Any,
) -> Any:
    """Compile using COPRO optimizer."""
    params = getattr(config, "optimizer_params", None) or {}
    breadth = params.get("breadth", DEFAULT_COPRO_BREADTH)
    depth = params.get("depth", DEFAULT_COPRO_DEPTH)
    optimizer = dspy_mod.COPRO(metric=metric_fn, breadth=breadth, depth=depth)
    return optimizer.compile(program, trainset=trainset, eval_kwargs={})


def _run_simba(
    dspy_mod: Any,
    program: Any,
    trainset: list,
    metric_fn: Callable,
    config: PromptOptimizationConfig,
    **kwargs: Any,
) -> Any:
    """Compile using SIMBA optimizer."""
    params = getattr(config, "optimizer_params", None) or {}
    num_candidates = params.get("num_candidates", DEFAULT_SIMBA_NUM_CANDIDATES)
    max_steps = params.get("max_steps", DEFAULT_SIMBA_MAX_STEPS)
    optimizer = dspy_mod.SIMBA(
        metric=metric_fn,
        num_candidates=num_candidates,
        max_steps=max_steps,
        max_demos=config.max_demos,
    )
    return optimizer.compile(program, trainset=trainset)


def _run_gepa(
    dspy_mod: Any,
    program: Any,
    trainset: list,
    metric_fn: Callable,
    config: PromptOptimizationConfig,
    **kwargs: Any,
) -> Any:
    """Compile using GEPA optimizer."""
    valset = kwargs.get("valset")
    optimizer = dspy_mod.GEPA(metric=metric_fn, auto="light")
    return optimizer.compile(program, trainset=trainset, valset=valset)


_OPTIMIZER_REGISTRY: dict[str, OptimizerRunner] = {
    "bootstrap": _run_bootstrap,
    "mipro": _run_mipro,
    "copro": _run_copro,
    "simba": _run_simba,
    "gepa": _run_gepa,
}


def get_optimizer(name: str) -> OptimizerRunner:
    """Return the optimizer runner for the given name.

    Raises ValueError if the name is not registered.
    """
    runner = _OPTIMIZER_REGISTRY.get(name)
    if runner is None:
        raise ValueError(
            f"Unknown optimizer '{name}'. Available: {list_optimizers()}",
        )
    return runner


def register_optimizer(name: str, runner: OptimizerRunner) -> None:
    """Register an optimizer runner under the given name."""
    _OPTIMIZER_REGISTRY[name] = runner


def list_optimizers() -> list[str]:
    """Return a sorted list of all registered optimizer names."""
    return sorted(_OPTIMIZER_REGISTRY.keys())
