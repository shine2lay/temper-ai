"""DSPy compiler — wraps BootstrapFewShot and MIPROv2 optimizers."""

import logging
import uuid
from typing import Any, Callable, List, Optional

from temper_ai.optimization.dspy._schemas import (
    CompilationResult,
    PromptOptimizationConfig,
    TrainingExample,
)
from temper_ai.optimization.dspy.constants import TRAIN_SPLIT_RATIO

_UUID_SHORT_LENGTH = 8
FUZZY_THRESHOLD = 0.5

logger = logging.getLogger(__name__)


def _exact_match_metric(
    example: Any, prediction: Any, trace: Any = None,
) -> bool:
    """Return True if prediction output matches example output exactly."""
    return getattr(prediction, "output", "") == getattr(example, "output", "")


def _contains_metric(
    example: Any, prediction: Any, trace: Any = None,
) -> bool:
    """Return True if expected output is a substring of predicted output."""
    expected = str(getattr(example, "output", ""))
    actual = str(getattr(prediction, "output", ""))
    return expected in actual


def _fuzzy_metric(
    example: Any, prediction: Any, trace: Any = None,
) -> bool:
    """Return True if token overlap ratio >= threshold."""
    expected = set(str(getattr(example, "output", "")).lower().split())
    actual = set(str(getattr(prediction, "output", "")).lower().split())
    if not expected:
        return not actual
    overlap = len(expected & actual) / len(expected | actual)
    return overlap >= FUZZY_THRESHOLD


class DSPyCompiler:
    """Compiles DSPy programs using training data."""

    def compile(
        self,
        program: Any,
        training_examples: List[TrainingExample],
        config: PromptOptimizationConfig,
        provider: str = "openai",
        model: str = "gpt-4",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
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
        metric_fn = self._get_metric(config.training_metric)

        compiled = self._run_optimizer(
            dspy, program, trainset, metric_fn, config,
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

    def _run_optimizer(self, dspy: Any, program: Any, trainset: list, metric_fn: Callable, config: PromptOptimizationConfig) -> Any:
        """Run the configured optimizer."""
        if config.optimizer == "mipro":
            optimizer = dspy.MIPROv2(
                metric=metric_fn, auto="light",
            )
            return optimizer.compile(
                program, trainset=trainset,
                num_threads=config.num_threads,
            )

        optimizer = dspy.BootstrapFewShot(
            metric=metric_fn,
            max_bootstrapped_demos=config.max_demos,
        )
        return optimizer.compile(program, trainset=trainset)

    @staticmethod
    def _get_metric(metric_name: Optional[str]) -> Callable:
        """Return the metric function for the given metric name.

        Supported metrics:
            - "exact_match" (default): output must exactly match expected
            - "contains": expected must be a substring of output
            - "fuzzy": token overlap ratio >= 0.5
        """
        if metric_name == "contains":
            return _contains_metric
        if metric_name == "fuzzy":
            return _fuzzy_metric
        return _exact_match_metric

    @staticmethod
    def _evaluate(program: Any, dataset: list, metric_fn: Callable) -> Optional[float]:
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
                        predictor.signature, "instructions", "",
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
