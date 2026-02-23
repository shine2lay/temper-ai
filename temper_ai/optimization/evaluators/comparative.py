"""Comparative evaluator — pairwise A vs B via LLM."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from temper_ai.optimization._schemas import EvaluationResult, EvaluatorConfig
from temper_ai.optimization.engine_constants import (
    FIRST_BETTER,
    MAX_SCORE,
    SECOND_BETTER,
    TIE,
)

logger = logging.getLogger(__name__)

_CHOICE_PATTERN = re.compile(r"\b([AB])\b")


class ComparativeEvaluator:
    """Evaluator that uses LLM to compare two outputs pairwise."""

    def __init__(
        self,
        config: EvaluatorConfig,
        llm: Any | None = None,
    ) -> None:
        self.prompt_template = config.prompt or "Which output is better?"
        self.llm = llm

    def evaluate(
        self,
        output: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        """Single output evaluation: always passes (comparison-only evaluator)."""
        return EvaluationResult(passed=True, score=MAX_SCORE)

    def compare(
        self,
        output_a: dict[str, Any],
        output_b: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> int:
        """Compare two outputs via LLM. Returns -1 (A), 0 (tie), 1 (B)."""
        if not self.llm:
            return TIE
        try:
            prompt = (
                f"{self.prompt_template}\n\n"
                f"Output A:\n{json.dumps(output_a, indent=2)}\n\n"
                f"Output B:\n{json.dumps(output_b, indent=2)}\n\n"
                "Answer with A, B, or TIE."
            )
            response = self.llm.generate(prompt)
            return self._parse_choice(response)
        except (AttributeError, TypeError, RuntimeError) as exc:
            logger.warning("Comparative evaluation failed: %s", exc)
            return TIE

    def _parse_choice(self, response: str) -> int:
        """Parse LLM response into comparison result."""
        text = response.strip().upper()
        if "TIE" in text:
            return TIE
        match = _CHOICE_PATTERN.search(text)
        if match:
            choice = match.group(1)
            if choice == "A":
                return FIRST_BETTER
            return SECOND_BETTER
        return TIE
