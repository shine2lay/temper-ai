"""Scored evaluator — LLM-as-judge with 0-1 score."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from temper_ai.optimization._schemas import EvaluationResult, EvaluatorConfig
from temper_ai.optimization.engine_constants import FIRST_BETTER, MAX_SCORE, MIN_SCORE, TIE

logger = logging.getLogger(__name__)

_SCORE_PATTERN = re.compile(r"(\d+\.?\d*)")
_DEFAULT_PASS_THRESHOLD = 0.5


class ScoredEvaluator:
    """Evaluator that uses LLM-as-judge to assign a 0-1 score."""

    def __init__(
        self,
        config: EvaluatorConfig,
        llm: Optional[Any] = None,
    ) -> None:
        self.rubric = config.rubric or "Rate the quality of this output."
        self.prompt_template = config.prompt
        self.llm = llm

    def evaluate(
        self,
        output: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """Score output via LLM on 0-1 scale."""
        if not self.llm:
            return EvaluationResult(passed=False, score=MIN_SCORE)
        try:
            prompt = (
                f"{self.rubric}\n\n"
                f"Output:\n{json.dumps(output, indent=2)}\n\n"
                "Respond with a single number between 0.0 and 1.0."
            )
            response = self.llm.generate(prompt)
            score = self._parse_score(response)
            return EvaluationResult(
                passed=score >= _DEFAULT_PASS_THRESHOLD,
                score=score,
                details={"raw_response": response.strip()},
            )
        except (AttributeError, TypeError, RuntimeError) as exc:
            logger.warning("Scored evaluation failed: %s", exc)
            return EvaluationResult(passed=False, score=MIN_SCORE)

    def compare(
        self,
        output_a: Dict[str, Any],
        output_b: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Compare by score: higher score wins."""
        result_a = self.evaluate(output_a, context)
        result_b = self.evaluate(output_b, context)
        if result_a.score > result_b.score:
            return FIRST_BETTER
        if result_b.score > result_a.score:
            return 1
        return TIE

    def _parse_score(self, response: str) -> float:
        """Extract float score from LLM response."""
        match = _SCORE_PATTERN.search(response.strip())
        if match:
            value = float(match.group(1))
            return max(MIN_SCORE, min(MAX_SCORE, value))
        return MIN_SCORE
