"""Criteria evaluator — pass/fail checks (programmatic + LLM)."""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
from typing import Any, Dict, List, Optional

from temper_ai.optimization._schemas import CheckConfig, EvaluationResult, EvaluatorConfig
from temper_ai.optimization.engine_constants import (
    CHECK_METHOD_LLM,
    CHECK_METHOD_PROGRAMMATIC,
    FIRST_BETTER,
    MAX_SCORE,
    MIN_SCORE,
    TIE,
)

logger = logging.getLogger(__name__)


class CriteriaEvaluator:
    """Evaluator that runs pass/fail checks against output."""

    def __init__(
        self,
        config: EvaluatorConfig,
        llm: Optional[Any] = None,
    ) -> None:
        self.checks: List[CheckConfig] = config.checks
        self.llm = llm

    def evaluate(
        self,
        output: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """Run all checks and return aggregated result."""
        if not self.checks:
            return EvaluationResult(passed=True, score=MAX_SCORE)

        results: Dict[str, Any] = {}
        passed_count = 0

        for check in self.checks:
            if check.method == CHECK_METHOD_PROGRAMMATIC:
                check_passed = self._run_programmatic(check, output)
            elif check.method == CHECK_METHOD_LLM:
                check_passed = self._run_llm_check(check, output)
            else:
                logger.warning("Unknown check method: %s", check.method)
                check_passed = False

            results[check.name] = check_passed
            if check_passed:
                passed_count += 1

        total = len(self.checks)
        score = passed_count / total if total > 0 else MIN_SCORE
        all_passed = passed_count == total

        return EvaluationResult(
            passed=all_passed,
            score=score,
            details={"checks": results},
        )

    def compare(
        self,
        output_a: Dict[str, Any],
        output_b: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Compare by score: more checks passed wins."""
        result_a = self.evaluate(output_a, context)
        result_b = self.evaluate(output_b, context)
        if result_a.score > result_b.score:
            return FIRST_BETTER
        if result_b.score > result_a.score:
            return 1
        return TIE

    def _run_programmatic(
        self, check: CheckConfig, output: Dict[str, Any]
    ) -> bool:
        """Run a programmatic check via subprocess."""
        if not check.command:
            return False
        try:
            args = shlex.split(check.command)
            result = subprocess.run(  # noqa: S603 — args from shlex.split, no shell
                args,
                input=json.dumps(output),
                capture_output=True,
                text=True,
                timeout=check.timeout,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logger.warning("Programmatic check %s failed: %s", check.name, exc)
            return False

    def _run_llm_check(
        self, check: CheckConfig, output: Dict[str, Any]
    ) -> bool:
        """Run an LLM-based yes/no check."""
        if not self.llm or not check.prompt:
            return False
        try:
            prompt = f"{check.prompt}\n\nOutput:\n{json.dumps(output, indent=2)}\n\nAnswer YES or NO."
            response: str = self.llm.generate(prompt)
            answer = response.strip().upper()
            return bool(answer.startswith("YES"))
        except (AttributeError, TypeError, RuntimeError) as exc:
            logger.warning("LLM check %s failed: %s", check.name, exc)
            return False
