"""DSPy prompt compilation as a pipeline step."""

from __future__ import annotations

import logging
from typing import Any

from temper_ai.optimization._schemas import OptimizationResult

logger = logging.getLogger(__name__)

_ERR_AGENT_NAME = "agent_name required in config"
_ERR_DSPY_MISSING = "DSPy not installed"
_STATUS_INSUFFICIENT_DATA = "insufficient_data"
_STATUS_COMPILED = "compiled"
_DEFAULT_LOOKBACK_HOURS = 720
_DEFAULT_MAX_DEMOS = 3

# Module-level names populated lazily so tests can patch them.
# Set to None when the dspy subpackage is unavailable.
try:
    from temper_ai.optimization.dspy._schemas import PromptOptimizationConfig
    from temper_ai.optimization.dspy.compiler import DSPyCompiler
    from temper_ai.optimization.dspy.data_collector import TrainingDataCollector
    from temper_ai.optimization.dspy.program_builder import DSPyProgramBuilder
    from temper_ai.optimization.dspy.program_store import CompiledProgramStore

    _DSPY_AVAILABLE = True
except ImportError:
    PromptOptimizationConfig: type | None = None  # type: ignore[misc,no-redef]
    DSPyCompiler: type | None = None  # type: ignore[misc,no-redef]
    TrainingDataCollector: type | None = None  # type: ignore[misc,no-redef]
    DSPyProgramBuilder: type | None = None  # type: ignore[misc,no-redef]
    CompiledProgramStore: type | None = None  # type: ignore[misc,no-redef]
    _DSPY_AVAILABLE = False


class PromptOptimizer:
    """DSPy prompt compilation as an optimization pipeline step.

    Config keys (passed via config dict):
        agent_name: str — which agent to optimize
        provider/model/base_url/api_key: LLM settings for DSPy
        optimizer: "bootstrap" | "mipro" — DSPy optimizer type
        min_training_examples: int
        lookback_hours: int
        max_demos: int
        module_type: "predict" | "chain_of_thought"
    """

    def optimize(
        self,
        runner: Any,
        input_data: dict[str, Any],
        evaluator: Any,
        config: dict[str, Any],
    ) -> OptimizationResult:
        """Run DSPy prompt optimization as a pipeline step.

        Returns OptimizationResult with improved=True on success.
        """
        agent_name = config.get("agent_name", "")
        if not agent_name:
            return OptimizationResult(
                output=input_data,
                details={"error": _ERR_AGENT_NAME},
            )

        if not _DSPY_AVAILABLE or TrainingDataCollector is None:
            return OptimizationResult(
                output=input_data,
                details={"error": _ERR_DSPY_MISSING},
            )

        opt_config = _build_opt_config(PromptOptimizationConfig, config)
        evaluation_name = config.get("reads")
        examples = _collect_examples(
            TrainingDataCollector,
            agent_name,
            opt_config,
            evaluation_name,
        )

        if len(examples) < opt_config.min_training_examples:
            return OptimizationResult(
                output=input_data,
                details={
                    "status": _STATUS_INSUFFICIENT_DATA,
                    "examples_found": len(examples),
                    "examples_required": opt_config.min_training_examples,
                },
            )

        return _compile_and_save(
            DSPyProgramBuilder,
            DSPyCompiler,
            CompiledProgramStore,
            agent_name,
            examples,
            opt_config,
            config,
            input_data,
        )


def _build_opt_config(config_cls: Any, config: dict[str, Any]) -> Any:
    """Construct PromptOptimizationConfig from a raw config dict."""
    kwargs: dict[str, Any] = {
        "optimizer": config.get("optimizer", "bootstrap"),
        "module_type": config.get("module_type", "predict"),
        "min_training_examples": config.get("min_training_examples", 10),
        "lookback_hours": config.get("lookback_hours", _DEFAULT_LOOKBACK_HOURS),
        "max_demos": config.get("max_demos", _DEFAULT_MAX_DEMOS),
    }
    # Pass through new modular fields when present
    for key in (
        "training_metric",
        "optimizer_params",
        "metric_params",
        "module_params",
        "signature_style",
        "field_descriptions",
    ):
        if key in config:
            kwargs[key] = config[key]
    return config_cls(**kwargs)


def _collect_examples(
    collector_cls: Any,
    agent_name: str,
    opt_config: Any,
    evaluation_name: str | None = None,
) -> list:
    """Instantiate collector and gather historical training examples."""
    collector = collector_cls()
    return collector.collect_examples(
        agent_name=agent_name,
        min_quality_score=opt_config.min_quality_score,
        max_examples=opt_config.min_training_examples * 2,
        lookback_hours=opt_config.lookback_hours,
        evaluation_name=evaluation_name,
    )


def _compile_and_save(  # noqa: params
    builder_cls: Any,
    compiler_cls: Any,
    store_cls: Any,
    agent_name: str,
    examples: list,
    opt_config: Any,
    config: dict[str, Any],
    input_data: dict[str, Any],
) -> OptimizationResult:
    """Build, compile, and persist the DSPy program; return an OptimizationResult."""
    builder = builder_cls()
    program = builder.build_from_config(opt_config)

    compiler = compiler_cls()
    result = compiler.compile(
        program=program,
        training_examples=examples,
        config=opt_config,
        provider=config.get("provider", "openai"),
        model=config.get("model", "gpt-4"),
        api_key=config.get("api_key"),
        base_url=config.get("base_url"),
    )

    store = store_cls(store_dir=opt_config.program_store_dir)
    store.save(
        agent_name=agent_name,
        program=result.program_data,
        metadata={
            "optimizer": result.optimizer_type,
            "val_score": str(result.val_score or ""),
        },
    )

    return OptimizationResult(
        output=input_data,
        improved=True,
        details={
            "status": _STATUS_COMPILED,
            "agent_name": agent_name,
            "program_id": result.program_id,
            "num_examples": result.num_examples,
            "num_demos": result.num_demos,
            "val_score": result.val_score,
        },
    )
