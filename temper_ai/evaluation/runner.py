"""Prompt test runner — loads agent config, renders prompt, calls LLM, validates output."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import yaml
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.evaluation._schemas import (
    SuiteResult,
    TestCase,
    TestCaseValidator,
    TestResult,
    TestSuite,
)
from temper_ai.evaluation.constants import STATUS_ERROR, STATUS_FAIL, STATUS_PASS

logger = logging.getLogger(__name__)

_JINJA_ENV = SandboxedEnvironment()


class PromptTestRunner:
    """Runs test cases against an agent's prompt + LLM."""

    def __init__(self, agent_config_path: str) -> None:
        self._config_path = agent_config_path
        self._agent_config = self._load_config(agent_config_path)
        self._prompt_template = self._extract_prompt_template()
        self._inference_config = self._build_inference_config()

    def run_suite(self, suite: TestSuite) -> SuiteResult:
        """Run all test cases and aggregate results."""
        agent_name = Path(self._config_path).stem
        suite_start = time.monotonic()
        results: list[TestResult] = []

        for case in suite.test_cases:
            result = self.run_case(case)
            results.append(result)

        duration = time.monotonic() - suite_start
        passed = sum(1 for r in results if r.status == STATUS_PASS)
        failed = sum(1 for r in results if r.status == STATUS_FAIL)
        errors = sum(1 for r in results if r.status == STATUS_ERROR)

        return SuiteResult(
            agent_name=agent_name,
            agent_config=self._config_path,
            total=len(results),
            passed=passed,
            failed=failed,
            errors=errors,
            results=results,
            duration_seconds=duration,
        )

    def run_case(self, case: TestCase) -> TestResult:
        """Run a single test case: render → call LLM → extract answer → validate."""
        start = time.monotonic()
        try:
            rendered = self._render_prompt(case)
            raw_output, answer_text = self._call_llm(rendered)
            validator_results, status = self._validate_output(
                answer_text, case.validators
            )
        except (OSError, yaml.YAMLError, ValueError, RuntimeError) as exc:
            logger.warning("Test case '%s' raised error: %s", case.name, exc)
            duration = time.monotonic() - start
            return TestResult(
                test_name=case.name,
                status=STATUS_ERROR,
                duration_seconds=duration,
                error=str(exc),
            )

        duration = time.monotonic() - start
        return TestResult(
            test_name=case.name,
            status=status,
            duration_seconds=duration,
            validator_results=validator_results,
            raw_output=raw_output,
            answer_text=answer_text,
        )

    def _render_prompt(self, case: TestCase) -> str:
        """Render the Jinja2 prompt template with test case input vars."""
        template = _JINJA_ENV.from_string(self._prompt_template)
        return template.render(**case.input_vars)

    def _call_llm(self, rendered_prompt: str) -> tuple[str, str]:
        """Call LLM and extract final answer. Returns (raw_output, answer_text)."""
        from temper_ai.llm.providers.factory import create_llm_from_config
        from temper_ai.llm.response_parser import extract_final_answer
        from temper_ai.llm.service import LLMService

        llm = create_llm_from_config(self._inference_config)
        service = LLMService(llm=llm, inference_config=self._inference_config)
        result = service.run(rendered_prompt)
        raw_output = result.output
        answer_text = extract_final_answer(raw_output)
        return raw_output, answer_text

    def _validate_output(
        self,
        answer_text: str,
        validators: list[TestCaseValidator],
    ) -> tuple[list, str]:
        """Run guardrail checks and determine pass/fail status."""
        from temper_ai.agent.guardrails import (
            has_blocking_failures,
            run_guardrail_checks,
        )
        from temper_ai.storage.schemas.agent_config import GuardrailCheck

        checks = [
            GuardrailCheck(
                name=v.name,
                type="regex",
                pattern=v.pattern,
                severity=v.severity,
            )
            for v in validators
        ]
        guardrail_results = run_guardrail_checks(answer_text, checks)
        validator_results = [
            {
                "name": r.check_name,
                "passed": r.passed,
                "severity": r.severity,
                "message": r.message,
            }
            for r in guardrail_results
        ]
        status = (
            STATUS_FAIL if has_blocking_failures(guardrail_results) else STATUS_PASS
        )
        return validator_results, status

    @staticmethod
    def _load_config(path: str) -> dict[str, Any]:
        """Load agent YAML config."""
        with open(path) as f:
            result: dict[str, Any] = yaml.safe_load(f)
            return result

    def _extract_prompt_template(self) -> str:
        """Get inline prompt from agent config."""
        agent_data = self._agent_config.get("agent", {})
        prompt_data = agent_data.get("prompt", {})
        template: str = prompt_data.get("inline", "")
        return template

    def _build_inference_config(self) -> Any:
        """Build InferenceConfig from agent config."""
        from temper_ai.storage.schemas.agent_config import InferenceConfig

        agent_data = self._agent_config.get("agent", {})
        inference_raw = agent_data.get("inference", {})
        return InferenceConfig(**inference_raw)
