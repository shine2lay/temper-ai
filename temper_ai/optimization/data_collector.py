"""Training data collector for DSPy prompt optimization."""

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Optional

from temper_ai.optimization._schemas import TrainingExample
from temper_ai.optimization.constants import (
    DEFAULT_FALLBACK_QUALITY_SCORE,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MIN_QUALITY_SCORE,
)

logger = logging.getLogger(__name__)

MAX_EXAMPLES_DEFAULT = 100


class TrainingDataCollector:
    """Collects training examples from agent execution history."""

    def __init__(self, session_factory: Optional[Callable] = None) -> None:
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
    ) -> List[TrainingExample]:
        """Query AgentExecution table for completed, high-quality examples."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        with self._session_factory() as session:
            return self._query_examples(
                session, agent_name, min_quality_score, max_examples, cutoff,
            )

    def _query_examples(
        self,
        session: Any,
        agent_name: str,
        min_quality_score: float,
        max_examples: int,
        cutoff: datetime,
    ) -> List[TrainingExample]:
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

    def _fallback_query(
        self, session: Any, agent_name: str, max_examples: int, cutoff: datetime,
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
        self, session: Any, executions: list, use_fallback_score: bool,
    ) -> List[TrainingExample]:
        from sqlmodel import select

        from temper_ai.storage.database.models import LLMCall

        examples = []
        for execution in executions:
            input_text = self._serialize_data(execution.input_data)
            output_text = self._serialize_data(execution.output_data)
            if not input_text or not output_text:
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

            examples.append(TrainingExample(
                input_text=input_text,
                output_text=output_text,
                metric_score=score,
                agent_name=execution.agent_name,
                prompt_template_hash=template_hash,
            ))
        return examples

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
