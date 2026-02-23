"""Async, non-blocking per-agent evaluation dispatch.

Runs evaluations in background threads (ThreadPoolExecutor) after
each agent completes. Never blocks workflow execution.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

from temper_ai.optimization._evaluation_schemas import (
    DEFAULT_EVALUATION_KEY,
    AgentEvaluationConfig,
    EvaluationMapping,
)
from temper_ai.optimization._schemas import EvaluationResult
from temper_ai.optimization.engine_constants import MAX_SCORE, MIN_SCORE

logger = logging.getLogger(__name__)

DEFAULT_MAX_WORKERS = 2
DEFAULT_WAIT_TIMEOUT = 30


class EvaluationDispatcher:
    """Dispatch per-agent evaluations in background threads.

    Each evaluation writes its own ``AgentEvaluationResult`` row to the DB.
    The dispatcher never blocks the calling thread (workflow execution).
    """

    def __init__(
        self,
        config: EvaluationMapping,
        llm_factory: Any | None = None,
        session_factory: Any | None = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        self._config = config
        self._llm_factory = llm_factory
        self._session_factory = session_factory
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: list[Future] = []  # type: ignore[type-arg]
        self._futures_lock = threading.Lock()

    def dispatch(
        self,
        agent_name: str,
        agent_execution_id: str,
        input_data: Any,
        output_data: Any,
        metrics: dict[str, Any] | None = None,
        agent_context: dict[str, Any] | None = None,
    ) -> None:
        """Submit evaluation tasks for this agent (non-blocking)."""
        eval_names = self._resolve_evaluations(agent_name)
        if not eval_names:
            return

        for eval_name in eval_names:
            eval_config = self._config.evaluations.get(eval_name)
            if eval_config is None:
                logger.warning(
                    "Evaluation '%s' referenced for agent '%s' but not defined",
                    eval_name,
                    agent_name,
                )
                continue

            future = self._executor.submit(
                self._run_evaluation,
                eval_name,
                eval_config,
                agent_execution_id,
                input_data,
                output_data,
                metrics or {},
                agent_context or {},
            )
            with self._futures_lock:
                self._futures.append(future)

    def wait_all(self, timeout: int = DEFAULT_WAIT_TIMEOUT) -> list[dict[str, Any]]:
        """Wait for pending evaluations and return results.

        Call at workflow end to ensure all evaluations are persisted.
        """
        with self._futures_lock:
            futures_snapshot = list(self._futures)
            self._futures.clear()

        results: list[dict[str, Any]] = []
        for future in as_completed(futures_snapshot, timeout=timeout):
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except (
                Exception
            ):  # noqa: BLE001 — evaluation failures must not crash workflow
                logger.warning("Evaluation future failed", exc_info=True)
        return results

    def shutdown(self) -> None:
        """Clean shutdown of thread pool."""
        self._executor.shutdown(wait=False)

    def _resolve_evaluations(self, agent_name: str) -> list[str]:
        """Look up eval names: agent-specific first, then _default."""
        agent_evals = self._config.agent_evaluations
        if agent_name in agent_evals:
            return agent_evals[agent_name]
        if DEFAULT_EVALUATION_KEY in agent_evals:
            return agent_evals[DEFAULT_EVALUATION_KEY]
        return []

    def _run_evaluation(
        self,
        eval_name: str,
        config: AgentEvaluationConfig,
        agent_execution_id: str,
        input_data: Any,
        output_data: Any,
        metrics: dict[str, Any],
        agent_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Run a single evaluation and persist to AgentEvaluationResult."""
        try:
            result = self._evaluate(
                config, output_data, input_data, metrics, agent_context
            )
            row = self._persist_result(
                eval_name,
                config.type,
                agent_execution_id,
                result,
            )
            logger.info(
                "Evaluation '%s': score=%.2f passed=%s",
                eval_name,
                result.score,
                result.passed,
            )
            return row
        except Exception:  # noqa: BLE001 — evaluation failures must not crash workflow
            logger.warning(
                "Evaluation '%s' failed for execution %s",
                eval_name,
                agent_execution_id,
                exc_info=True,
            )
            return None

    def _evaluate(
        self,
        config: AgentEvaluationConfig,
        output_data: Any,
        input_data: Any,
        metrics: dict[str, Any],
        agent_context: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        """Build and run the appropriate evaluator."""
        from temper_ai.optimization._schemas import EvaluatorConfig

        output_dict = (
            output_data
            if isinstance(output_data, dict)
            else {"output": str(output_data)}
        )
        ctx = agent_context or {}
        if ctx.get("prompt"):
            output_dict["prompt"] = ctx["prompt"]
        if ctx.get("reasoning"):
            output_dict["reasoning"] = ctx["reasoning"]
        if ctx.get("tool_calls"):
            output_dict["tool_calls"] = ctx["tool_calls"]
        context = {
            "input": input_data,
            "metrics": metrics,
            "agent": ctx,
        }

        if config.type == "criteria":
            from temper_ai.optimization.evaluators.criteria import CriteriaEvaluator

            evaluator_config = EvaluatorConfig(
                type="criteria",
                checks=config.checks,
            )
            evaluator = CriteriaEvaluator(evaluator_config, llm=self._llm_factory)
            return evaluator.evaluate(output_dict, context)

        if config.type == "scored":
            from temper_ai.optimization.evaluators.scored import ScoredEvaluator

            evaluator_config = EvaluatorConfig(
                type="scored",
                rubric=config.rubric,
                prompt=config.prompt,
            )
            scored_evaluator = ScoredEvaluator(evaluator_config, llm=self._llm_factory)
            return scored_evaluator.evaluate(output_dict, context)

        if config.type == "composite":
            from temper_ai.optimization.evaluators.composite import CompositeEvaluator

            composite_evaluator = CompositeEvaluator(config, llm=self._llm_factory)
            return composite_evaluator.evaluate(output_dict, context)

        logger.warning("Unknown evaluator type: %s, defaulting to pass", config.type)
        return EvaluationResult(passed=True, score=MAX_SCORE)

    def _persist_result(
        self,
        eval_name: str,
        evaluator_type: str,
        agent_execution_id: str,
        result: EvaluationResult,
    ) -> dict[str, Any]:
        """Write AgentEvaluationResult row to DB."""
        row_data = {
            "id": str(uuid.uuid4()),
            "agent_execution_id": agent_execution_id,
            "evaluation_name": eval_name,
            "evaluator_type": evaluator_type,
            "score": max(MIN_SCORE, min(MAX_SCORE, result.score)),
            "passed": result.passed,
            "details": result.details,
        }

        if self._session_factory is not None:
            try:
                self._write_to_db(row_data)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to persist evaluation result for %s",
                    eval_name,
                    exc_info=True,
                )

        return row_data

    def _write_to_db(self, row_data: dict[str, Any]) -> None:
        """Write evaluation result to database."""
        from temper_ai.storage.database.models_evaluation import AgentEvaluationResult

        if self._session_factory is None:
            return
        with self._session_factory() as session:
            record = AgentEvaluationResult(**row_data)
            session.add(record)
            session.commit()
