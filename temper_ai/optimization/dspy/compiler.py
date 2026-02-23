"""DSPy compiler — wraps pluggable optimizers via registry dispatch."""

import logging
import uuid
from collections.abc import Callable
from typing import Any

from temper_ai.optimization.dspy._schemas import (
    CompilationResult,
    PromptOptimizationConfig,
    TrainingExample,
)
from temper_ai.optimization.dspy.constants import TRAIN_SPLIT_RATIO

_UUID_SHORT_LENGTH = 8
_GEPA_OPTIMIZER = "gepa"
_GEPA_DEFAULT_METRIC = "gepa_feedback"
_DEFAULT_METRIC_NAME = "exact_match"

logger = logging.getLogger(__name__)


class DSPyCompiler:
    """Compiles DSPy programs using training data."""

    def compile(
        self,
        program: Any,
        training_examples: list[TrainingExample],
        config: PromptOptimizationConfig,
        provider: str = "openai",
        model: str = "gpt-4",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> CompilationResult:
        """Compile a DSPy program using the configured optimizer."""
        from temper_ai.optimization.dspy._helpers import (
            configure_dspy_lm,
            ensure_dspy_available,
            examples_to_dspy,
        )

        ensure_dspy_available()
        import dspy

        configure_dspy_lm(provider, model, api_key, base_url)
        dspy_examples = examples_to_dspy(training_examples)
        trainset, valset = self._split_data(dspy_examples)
        metric_fn = self._resolve_metric(config)

        compiled = self._run_optimizer(
            dspy,
            program,
            trainset,
            valset,
            metric_fn,
            config,
        )

        train_score = self._evaluate(compiled, trainset, metric_fn)
        val_score = self._evaluate(compiled, valset, metric_fn)

        program_id = self._generate_id(config)
        program_data = self._extract_program_data(compiled)
        return CompilationResult(
            program_id=program_id,
            agent_name="",  # Set by caller
            optimizer_type=config.optimizer,
            train_score=train_score,
            val_score=val_score,
            num_examples=len(training_examples),
            num_demos=len(program_data.get("demos", [])),
            program_data=program_data,
        )

    def _split_data(self, examples: list) -> tuple:
        """Split examples into train/val using TRAIN_SPLIT_RATIO."""
        split_idx = max(1, int(len(examples) * TRAIN_SPLIT_RATIO))
        return examples[:split_idx], examples[split_idx:]

    @staticmethod
    def _run_optimizer(
        dspy: Any,
        program: Any,
        trainset: list,
        valset: list,
        metric_fn: Callable,
        config: PromptOptimizationConfig,
    ) -> Any:
        """Run the configured optimizer via the optimizer registry."""
        from temper_ai.optimization.dspy.optimizers import (
            get_optimizer,  # noqa: PLC0415
        )

        runner = get_optimizer(config.optimizer)
        return runner(dspy, program, trainset, metric_fn, config, valset=valset)

    @staticmethod
    def _resolve_metric(config: PromptOptimizationConfig) -> Callable:
        """Resolve the metric function via the metric registry.

        For GEPA optimizer, auto-selects gepa_feedback metric when the
        configured metric is the default exact_match.
        """
        from temper_ai.optimization.dspy.metrics import get_metric  # noqa: PLC0415

        metric_name = config.training_metric
        if config.optimizer == _GEPA_OPTIMIZER and metric_name == _DEFAULT_METRIC_NAME:
            metric_name = _GEPA_DEFAULT_METRIC
        return get_metric(metric_name, **(config.metric_params or {}))

    @staticmethod
    def _evaluate(program: Any, dataset: list, metric_fn: Callable) -> float | None:
        """Evaluate compiled program on a dataset."""
        if not dataset:
            return None
        correct = 0
        for example in dataset:
            try:
                pred = program(input=example.input)
                if metric_fn(example, pred):
                    correct += 1
            except (AttributeError, TypeError, RuntimeError):
                pass
        return correct / len(dataset)

    @staticmethod
    def _extract_program_data(compiled: Any) -> dict:
        """Extract instruction and demos from a compiled DSPy program."""
        instruction = ""
        demos: list = []
        try:
            for predictor in compiled.predictors():
                if hasattr(predictor, "signature"):
                    sig_instructions = getattr(
                        predictor.signature,
                        "instructions",
                        "",
                    )
                    if sig_instructions and not instruction:
                        instruction = str(sig_instructions)
                for demo in getattr(predictor, "demos", []):
                    entry: dict = {}
                    if hasattr(demo, "input"):
                        entry["input"] = str(demo.input)
                    if hasattr(demo, "output"):
                        entry["output"] = str(demo.output)
                    if entry:
                        demos.append(entry)
        except (AttributeError, TypeError):
            logger.debug("Could not extract predictors from compiled program")
        return {"instruction": instruction, "demos": demos}

    @staticmethod
    def _generate_id(config: PromptOptimizationConfig) -> str:
        """Generate a unique program ID."""
        short_uuid = uuid.uuid4().hex[:_UUID_SHORT_LENGTH]
        return f"prog_{config.optimizer}_{short_uuid}"
