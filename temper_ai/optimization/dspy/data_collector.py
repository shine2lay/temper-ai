"""Training data collector for DSPy prompt optimization."""

import json
import logging
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from temper_ai.optimization.dspy._schemas import TrainingExample
from temper_ai.optimization.dspy.constants import (
    DEFAULT_FALLBACK_QUALITY_SCORE,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MIN_QUALITY_SCORE,
)

logger = logging.getLogger(__name__)

MAX_EXAMPLES_DEFAULT = 100


class TrainingDataCollector:
    """Collects training examples from agent execution history."""

    def __init__(self, session_factory: Callable | None = None) -> None:
        self._session_factory = session_factory or self._default_session_factory

    @staticmethod
    @contextmanager
    def _default_session_factory():  # type: ignore[no-untyped-def]
        from temper_ai.storage.database.manager import get_session

        with get_session() as session:
            yield session

    def collect_examples(
        self,
        agent_name: str,
        min_quality_score: float = DEFAULT_MIN_QUALITY_SCORE,
        max_examples: int = MAX_EXAMPLES_DEFAULT,
        lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
        evaluation_name: str | None = None,
    ) -> list[TrainingExample]:
        """Query AgentExecution table for completed, high-quality examples.

        When ``evaluation_name`` is provided, scores are read from the
        AgentEvaluationResult table (per-agent evaluation) instead of
        the heuristic output_quality_score on AgentExecution.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)

        with self._session_factory() as session:
            if evaluation_name:
                return self._query_with_evaluation(
                    session,
                    agent_name,
                    evaluation_name,
                    min_quality_score,
                    max_examples,
                    cutoff,
                )
            return self._query_examples(
                session,
                agent_name,
                min_quality_score,
                max_examples,
                cutoff,
            )

    def _query_examples(
        self,
        session: Any,
        agent_name: str,
        min_quality_score: float,
        max_examples: int,
        cutoff: datetime,
    ) -> list[TrainingExample]:
        from sqlmodel import col, select

        from temper_ai.storage.database.models import AgentExecution

        stmt = (
            select(AgentExecution)
            .where(AgentExecution.agent_name == agent_name)
            .where(AgentExecution.status == "completed")
            .where(col(AgentExecution.start_time) >= cutoff)
            .where(col(AgentExecution.output_quality_score) >= min_quality_score)
            .order_by(col(AgentExecution.start_time).desc())
            .limit(max_examples)
        )
        results = session.exec(stmt).all()

        if not results:
            results = self._fallback_query(session, agent_name, max_examples, cutoff)
            return self._convert_examples(session, results, use_fallback_score=True)

        return self._convert_examples(session, results, use_fallback_score=False)

    def _query_with_evaluation(
        self,
        session: Any,
        agent_name: str,
        evaluation_name: str,
        min_quality_score: float,
        max_examples: int,
        cutoff: datetime,
    ) -> list[TrainingExample]:
        """Query examples using AgentEvaluationResult scores."""
        from sqlmodel import col, select

        from temper_ai.storage.database.models import AgentExecution
        from temper_ai.storage.database.models_evaluation import AgentEvaluationResult

        stmt = (
            select(AgentExecution, AgentEvaluationResult.score)
            .join(
                AgentEvaluationResult,
                AgentEvaluationResult.agent_execution_id == AgentExecution.id,  # type: ignore[arg-type]
            )
            .where(AgentExecution.agent_name == agent_name)
            .where(AgentExecution.status == "completed")
            .where(col(AgentExecution.start_time) >= cutoff)
            .where(AgentEvaluationResult.evaluation_name == evaluation_name)
            .where(col(AgentEvaluationResult.score) >= min_quality_score)
            .order_by(col(AgentExecution.start_time).desc())
            .limit(max_examples)
        )
        rows = session.exec(stmt).all()

        if not rows:
            # Fall back to standard query without evaluation filter
            return self._query_examples(
                session,
                agent_name,
                min_quality_score,
                max_examples,
                cutoff,
            )

        return self._convert_evaluation_examples(session, rows)

    def _convert_evaluation_examples(
        self,
        session: Any,
        rows: list,
    ) -> list[TrainingExample]:
        """Convert AgentExecution + evaluation score tuples to TrainingExample."""
        from sqlmodel import select

        from temper_ai.storage.database.models import LLMCall

        examples = []
        for execution, eval_score in rows:
            output_text = self._serialize_data(execution.output_data)
            if not output_text:
                continue

            llm_stmt = (
                select(LLMCall)
                .where(LLMCall.agent_execution_id == execution.id)
                .limit(1)
            )
            llm_call = session.exec(llm_stmt).first()
            template_hash = llm_call.prompt_template_hash if llm_call else None

            # Prefer the rendered LLM prompt over raw input_data.
            # input_data contains the full workflow state (100K+ chars)
            # which is too large for DSPy; the prompt is the actual
            # context sent to the model (typically 2-10K chars).
            input_text = self._get_prompt_text(llm_call, execution)
            if not input_text:
                continue

            examples.append(
                TrainingExample(
                    input_text=input_text,
                    output_text=output_text,
                    metric_score=eval_score,
                    agent_name=execution.agent_name,
                    prompt_template_hash=template_hash,
                )
            )
        return examples

    def _fallback_query(
        self,
        session: Any,
        agent_name: str,
        max_examples: int,
        cutoff: datetime,
    ) -> list:
        from sqlmodel import col, select

        from temper_ai.storage.database.models import AgentExecution

        stmt = (
            select(AgentExecution)
            .where(AgentExecution.agent_name == agent_name)
            .where(AgentExecution.status == "completed")
            .where(col(AgentExecution.start_time) >= cutoff)
            .order_by(col(AgentExecution.start_time).desc())
            .limit(max_examples)
        )
        return list(session.exec(stmt).all())

    def _convert_examples(
        self,
        session: Any,
        executions: list,
        use_fallback_score: bool,
    ) -> list[TrainingExample]:
        from sqlmodel import select

        from temper_ai.storage.database.models import LLMCall

        examples = []
        for execution in executions:
            output_text = self._serialize_data(execution.output_data)
            if not output_text:
                continue

            if use_fallback_score:
                score = DEFAULT_FALLBACK_QUALITY_SCORE
            else:
                score = execution.output_quality_score or DEFAULT_FALLBACK_QUALITY_SCORE

            llm_stmt = (
                select(LLMCall)
                .where(LLMCall.agent_execution_id == execution.id)
                .limit(1)
            )
            llm_call = session.exec(llm_stmt).first()
            template_hash = llm_call.prompt_template_hash if llm_call else None

            input_text = self._get_prompt_text(llm_call, execution)
            if not input_text:
                continue

            examples.append(
                TrainingExample(
                    input_text=input_text,
                    output_text=output_text,
                    metric_score=score,
                    agent_name=execution.agent_name,
                    prompt_template_hash=template_hash,
                )
            )
        return examples

    @staticmethod
    def _get_prompt_text(llm_call: Any, execution: Any) -> str:
        """Get the best available input text for a training example.

        Prefers the rendered LLM prompt (compact, 2-10K chars) over
        the raw input_data (full workflow state, often 100K+ chars).
        Falls back to a truncated input_data if no LLM prompt exists.
        """
        if llm_call is not None:
            prompt = getattr(llm_call, "prompt", None)
            if prompt:
                return str(prompt) if not isinstance(prompt, str) else prompt

        # Fallback: serialize input_data but truncate to keep DSPy happy
        max_input_chars = 10000
        raw = execution.input_data
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw[:max_input_chars]
        try:
            serialized = json.dumps(raw, default=str)
            return serialized[:max_input_chars]
        except (TypeError, ValueError):
            return str(raw)[:max_input_chars]

    @staticmethod
    def _serialize_data(data: Any) -> str:
        if data is None:
            return ""
        if isinstance(data, str):
            return data
        try:
            return json.dumps(data, default=str)
        except (TypeError, ValueError):
            return str(data)
