"""Tests for TrainingDataCollector with evaluation_name JOIN."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from temper_ai.optimization.dspy.data_collector import TrainingDataCollector


def _make_execution(
    exec_id="exec-1",
    agent_name="researcher",
    input_data=None,
    output_data=None,
    quality_score=0.9,
    start_time=None,
):
    """Build a mock AgentExecution."""
    mock = MagicMock()
    mock.id = exec_id
    mock.agent_name = agent_name
    mock.input_data = input_data or {"task": "research AI safety"}
    mock.output_data = output_data or {"analysis": "AI safety is important"}
    mock.output_quality_score = quality_score
    mock.status = "completed"
    mock.start_time = start_time or datetime.now(UTC)
    return mock


def _make_eval_result(score=0.85):
    """Build a mock AgentEvaluationResult."""
    mock = MagicMock()
    mock.score = score
    return mock


class TestCollectWithEvaluationName:
    """Tests for collect_examples with evaluation_name parameter."""

    def test_with_evaluation_name_calls_query_with_evaluation(self):
        collector = TrainingDataCollector()

        with (
            patch.object(
                collector,
                "_query_with_evaluation",
                return_value=[],
            ) as mock_eval,
            patch.object(collector, "_session_factory") as mock_sf,
        ):
            mock_session = MagicMock()

            @contextmanager
            def session_cm():
                yield mock_session

            mock_sf.side_effect = session_cm

            collector.collect_examples(
                agent_name="researcher",
                evaluation_name="research_quality",
            )

        mock_eval.assert_called_once()
        call_args = mock_eval.call_args
        assert call_args[0][1] == "researcher"
        assert call_args[0][2] == "research_quality"

    def test_without_evaluation_name_calls_standard_query(self):
        collector = TrainingDataCollector()

        with (
            patch.object(
                collector,
                "_query_examples",
                return_value=[],
            ) as mock_std,
            patch.object(collector, "_session_factory") as mock_sf,
        ):
            mock_session = MagicMock()

            @contextmanager
            def session_cm():
                yield mock_session

            mock_sf.side_effect = session_cm

            collector.collect_examples(agent_name="researcher")

        mock_std.assert_called_once()


class TestQueryWithEvaluation:
    """Tests for _query_with_evaluation method."""

    def test_returns_examples_via_convert(self):
        collector = TrainingDataCollector()
        mock_session = MagicMock()

        execution = _make_execution()
        eval_score = 0.85

        # Mock the LLM call query for template hash
        llm_call_mock = MagicMock()
        llm_call_mock.prompt_template_hash = "abc123"
        llm_call_mock.prompt = None
        mock_session.exec.return_value.first.return_value = llm_call_mock

        result = collector._convert_evaluation_examples(
            mock_session,
            [(execution, eval_score)],
        )

        assert len(result) == 1
        assert result[0].metric_score == 0.85
        assert result[0].agent_name == "researcher"
        assert result[0].prompt_template_hash == "abc123"

    def test_fallback_when_no_rows(self):
        collector = TrainingDataCollector()
        mock_session = MagicMock()

        # Mock exec().all() to return empty → triggers fallback
        mock_session.exec.return_value.all.return_value = []

        with patch.object(
            collector,
            "_query_examples",
            return_value=[],
        ) as mock_fallback:
            cutoff = datetime.now(UTC) - timedelta(hours=24)

            collector._query_with_evaluation(
                mock_session,
                "researcher",
                "research_quality",
                0.7,
                100,
                cutoff,
            )

        mock_fallback.assert_called_once()


class TestConvertEvaluationExamples:
    """Tests for _convert_evaluation_examples method."""

    def test_skips_empty_input_output(self):
        collector = TrainingDataCollector()
        mock_session = MagicMock()

        execution_no_input = _make_execution(input_data=None, output_data=None)
        execution_no_input.input_data = None
        execution_no_input.output_data = None

        # Ensure the LLM call mock returns None for prompt
        llm_mock = MagicMock()
        llm_mock.prompt = None
        llm_mock.prompt_template_hash = None
        mock_session.exec.return_value.first.return_value = llm_mock

        result = collector._convert_evaluation_examples(
            mock_session,
            [(execution_no_input, 0.9)],
        )
        assert len(result) == 0

    def test_uses_eval_score_not_heuristic(self):
        collector = TrainingDataCollector()
        mock_session = MagicMock()

        execution = _make_execution(quality_score=0.5)  # Heuristic score
        eval_score = 0.95  # Evaluation score (should be used)

        llm_mock = MagicMock()
        llm_mock.prompt_template_hash = None
        llm_mock.prompt = None
        mock_session.exec.return_value.first.return_value = llm_mock

        result = collector._convert_evaluation_examples(
            mock_session,
            [(execution, eval_score)],
        )

        assert len(result) == 1
        assert result[0].metric_score == 0.95  # Uses eval score, not heuristic
