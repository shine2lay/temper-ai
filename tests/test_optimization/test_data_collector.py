"""Tests for TrainingDataCollector."""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock

from temper_ai.optimization.dspy.constants import DEFAULT_FALLBACK_QUALITY_SCORE
from temper_ai.optimization.dspy.data_collector import TrainingDataCollector

_MISSING = object()


def _make_execution(
    agent_name="researcher",
    status="completed",
    input_data=_MISSING,
    output_data=_MISSING,
    quality_score=0.9,
    start_time=None,
    exec_id="exec-1",
):
    """Create a mock AgentExecution."""
    mock = MagicMock()
    mock.id = exec_id
    mock.agent_name = agent_name
    mock.status = status
    mock.input_data = {"topic": "AI safety"} if input_data is _MISSING else input_data
    mock.output_data = (
        {"analysis": "AI safety is critical"}
        if output_data is _MISSING
        else output_data
    )
    mock.output_quality_score = quality_score
    mock.start_time = start_time or datetime.now(UTC)
    return mock


def _make_llm_call(template_hash="abc123", prompt=None):
    mock = MagicMock()
    mock.prompt_template_hash = template_hash
    mock.prompt = prompt
    return mock


class TestTrainingDataCollector:

    def _make_collector_with_mock_session(self, executions, llm_calls=None):
        """Create collector with mocked session that returns given executions."""
        session = MagicMock()
        result_proxy = MagicMock()
        result_proxy.all.return_value = executions

        llm_proxy = MagicMock()
        llm_proxy.first.return_value = llm_calls[0] if llm_calls else None

        call_count = {"n": 0}

        def side_effect(stmt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return result_proxy
            return llm_proxy

        session.exec.side_effect = side_effect

        @contextmanager
        def factory():
            yield session

        return TrainingDataCollector(session_factory=factory), session

    def test_collect_with_quality_scores(self):
        exec1 = _make_execution(quality_score=0.95)
        llm = _make_llm_call("hash1")
        collector, _ = self._make_collector_with_mock_session([exec1], [llm])

        examples = collector.collect_examples("researcher")
        assert len(examples) == 1
        assert examples[0].agent_name == "researcher"
        assert examples[0].metric_score == 0.95

    def test_collect_empty_results_triggers_fallback(self):
        """When quality query returns empty, fallback query runs."""
        session = MagicMock()
        call_count = {"n": 0}

        def side_effect(stmt):
            call_count["n"] += 1
            proxy = MagicMock()
            if call_count["n"] == 1:
                proxy.all.return_value = []
                return proxy
            elif call_count["n"] == 2:
                proxy.all.return_value = [_make_execution(quality_score=None)]
                return proxy
            else:
                proxy.first.return_value = None
                return proxy

        session.exec.side_effect = side_effect

        @contextmanager
        def factory():
            yield session

        collector = TrainingDataCollector(session_factory=factory)
        examples = collector.collect_examples("researcher")
        assert len(examples) == 1
        assert examples[0].metric_score == DEFAULT_FALLBACK_QUALITY_SCORE

    def test_collect_skips_null_input_output(self):
        exec1 = _make_execution(input_data=None, output_data=None)
        collector, _ = self._make_collector_with_mock_session([exec1])
        examples = collector.collect_examples("researcher")
        assert len(examples) == 0

    def test_collect_serializes_dict_input(self):
        exec1 = _make_execution(
            input_data={"topic": "ML"},
            output_data={"result": "analysis"},
        )
        llm = _make_llm_call()
        collector, _ = self._make_collector_with_mock_session([exec1], [llm])
        examples = collector.collect_examples("researcher")
        assert len(examples) == 1
        assert '"topic"' in examples[0].input_text
        assert '"result"' in examples[0].output_text

    def test_collect_handles_string_data(self):
        exec1 = _make_execution(input_data="raw input", output_data="raw output")
        llm = _make_llm_call()
        collector, _ = self._make_collector_with_mock_session([exec1], [llm])
        examples = collector.collect_examples("researcher")
        assert len(examples) == 1
        assert examples[0].input_text == "raw input"
        assert examples[0].output_text == "raw output"

    def test_collect_includes_template_hash(self):
        exec1 = _make_execution()
        llm = _make_llm_call("myhash")
        collector, _ = self._make_collector_with_mock_session([exec1], [llm])
        examples = collector.collect_examples("researcher")
        assert len(examples) == 1
        assert examples[0].prompt_template_hash == "myhash"

    def test_collect_no_llm_call_null_hash(self):
        exec1 = _make_execution()
        collector, _ = self._make_collector_with_mock_session([exec1], [])
        examples = collector.collect_examples("researcher")
        assert len(examples) == 1
        assert examples[0].prompt_template_hash is None

    def test_custom_parameters(self):
        exec1 = _make_execution(quality_score=0.99)
        llm = _make_llm_call()
        collector, _ = self._make_collector_with_mock_session([exec1], [llm])
        examples = collector.collect_examples(
            "researcher",
            min_quality_score=0.95,
            max_examples=5,
            lookback_hours=48,
        )
        assert len(examples) == 1

    def test_serialize_data_handles_non_json(self):
        """_serialize_data handles objects that aren't JSON-serializable."""
        obj = object()
        result = TrainingDataCollector._serialize_data(obj)
        assert isinstance(result, str)
        assert "object" in result  # Should contain repr/str of the object

    def test_serialize_data_none(self):
        result = TrainingDataCollector._serialize_data(None)
        assert result == ""
