"""Tests for EvaluationDispatcher."""

import threading
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from temper_ai.optimization._evaluation_schemas import (
    AgentEvaluationConfig,
    EvaluationMapping,
)
from temper_ai.optimization.evaluation_dispatcher import (
    EvaluationDispatcher,
)


def _make_mapping(**kwargs):
    """Build a minimal EvaluationMapping for testing."""
    return EvaluationMapping(**kwargs)


def _make_config(eval_type="scored", rubric="Rate quality", **kwargs):
    """Build a minimal AgentEvaluationConfig."""
    return AgentEvaluationConfig(type=eval_type, rubric=rubric, **kwargs)


class TestResolveEvaluations:
    """Tests for _resolve_evaluations fallback logic."""

    def test_agent_specific_mapping(self):
        mapping = _make_mapping(
            evaluations={"q1": _make_config()},
            agent_evaluations={"researcher": ["q1"]},
        )
        dispatcher = EvaluationDispatcher(config=mapping)
        assert dispatcher._resolve_evaluations("researcher") == ["q1"]

    def test_default_fallback(self):
        mapping = _make_mapping(
            evaluations={"balanced": _make_config()},
            agent_evaluations={"_default": ["balanced"]},
        )
        dispatcher = EvaluationDispatcher(config=mapping)
        assert dispatcher._resolve_evaluations("unknown_agent") == ["balanced"]

    def test_agent_specific_overrides_default(self):
        mapping = _make_mapping(
            evaluations={
                "q1": _make_config(),
                "q2": _make_config(),
            },
            agent_evaluations={
                "researcher": ["q1"],
                "_default": ["q2"],
            },
        )
        dispatcher = EvaluationDispatcher(config=mapping)
        assert dispatcher._resolve_evaluations("researcher") == ["q1"]

    def test_no_mapping_returns_empty(self):
        mapping = _make_mapping(evaluations={"q1": _make_config()})
        dispatcher = EvaluationDispatcher(config=mapping)
        assert dispatcher._resolve_evaluations("any_agent") == []


class TestDispatch:
    """Tests for dispatch method."""

    def test_dispatch_submits_futures(self):
        mapping = _make_mapping(
            evaluations={"q1": _make_config()},
            agent_evaluations={"researcher": ["q1"]},
        )
        dispatcher = EvaluationDispatcher(config=mapping)

        with patch.object(dispatcher, "_run_evaluation", return_value={"score": 0.9}):
            dispatcher.dispatch(
                agent_name="researcher",
                agent_execution_id="exec-1",
                input_data={"task": "test"},
                output_data="result",
                metrics={"tokens": 100},
            )
            assert len(dispatcher._futures) == 1

        dispatcher.shutdown()

    def test_dispatch_skips_undefined_evaluation(self):
        mapping = _make_mapping(
            evaluations={},
            agent_evaluations={"researcher": ["nonexistent"]},
        )
        dispatcher = EvaluationDispatcher(config=mapping)
        dispatcher.dispatch(
            agent_name="researcher",
            agent_execution_id="exec-1",
            input_data={},
            output_data="result",
        )
        # No futures submitted because eval config not found
        assert len(dispatcher._futures) == 0
        dispatcher.shutdown()

    def test_dispatch_no_mapping_no_futures(self):
        mapping = _make_mapping(evaluations={"q1": _make_config()})
        dispatcher = EvaluationDispatcher(config=mapping)
        dispatcher.dispatch(
            agent_name="unmapped",
            agent_execution_id="exec-1",
            input_data={},
            output_data="result",
        )
        assert len(dispatcher._futures) == 0
        dispatcher.shutdown()


class TestWaitAll:
    """Tests for wait_all method."""

    def test_wait_all_collects_results(self):
        mapping = _make_mapping(
            evaluations={"q1": _make_config()},
            agent_evaluations={"researcher": ["q1"]},
        )
        dispatcher = EvaluationDispatcher(config=mapping)

        with patch.object(
            dispatcher,
            "_run_evaluation",
            return_value={"score": 0.85, "evaluation_name": "q1"},
        ):
            dispatcher.dispatch(
                agent_name="researcher",
                agent_execution_id="exec-1",
                input_data={},
                output_data="output",
            )
            results = dispatcher.wait_all(timeout=10)

        assert len(results) == 1
        assert results[0]["score"] == 0.85
        dispatcher.shutdown()

    def test_wait_all_handles_exception(self):
        mapping = _make_mapping(
            evaluations={"q1": _make_config()},
            agent_evaluations={"researcher": ["q1"]},
        )
        dispatcher = EvaluationDispatcher(config=mapping)

        with patch.object(
            dispatcher,
            "_run_evaluation",
            side_effect=RuntimeError("eval failed"),
        ):
            dispatcher.dispatch(
                agent_name="researcher",
                agent_execution_id="exec-1",
                input_data={},
                output_data="output",
            )
            results = dispatcher.wait_all(timeout=10)

        # Exception is caught, no results
        assert len(results) == 0
        dispatcher.shutdown()

    def test_wait_all_clears_futures(self):
        mapping = _make_mapping(
            evaluations={"q1": _make_config()},
            agent_evaluations={"researcher": ["q1"]},
        )
        dispatcher = EvaluationDispatcher(config=mapping)

        with patch.object(dispatcher, "_run_evaluation", return_value={"score": 0.5}):
            dispatcher.dispatch(
                agent_name="researcher",
                agent_execution_id="exec-1",
                input_data={},
                output_data="output",
            )
            dispatcher.wait_all(timeout=10)

        assert len(dispatcher._futures) == 0
        dispatcher.shutdown()


class TestRunEvaluation:
    """Tests for _run_evaluation method."""

    def test_runs_evaluation_and_persists(self):
        mapping = _make_mapping(evaluations={})
        dispatcher = EvaluationDispatcher(config=mapping)

        eval_config = _make_config(eval_type="scored", rubric="Rate it")

        with (
            patch.object(dispatcher, "_evaluate") as mock_eval,
            patch.object(dispatcher, "_persist_result") as mock_persist,
        ):
            from temper_ai.optimization._schemas import EvaluationResult

            mock_eval.return_value = EvaluationResult(passed=True, score=0.9)
            mock_persist.return_value = {"score": 0.9}

            result = dispatcher._run_evaluation(
                "q1",
                eval_config,
                "exec-1",
                {},
                "output",
                {},
                {},
            )

        assert result is not None
        assert result["score"] == 0.9
        mock_eval.assert_called_once()
        mock_persist.assert_called_once()
        dispatcher.shutdown()

    def test_returns_none_on_exception(self):
        mapping = _make_mapping(evaluations={})
        dispatcher = EvaluationDispatcher(config=mapping)

        eval_config = _make_config()

        with patch.object(dispatcher, "_evaluate", side_effect=RuntimeError("fail")):
            result = dispatcher._run_evaluation(
                "q1",
                eval_config,
                "exec-1",
                {},
                "output",
                {},
                {},
            )

        assert result is None
        dispatcher.shutdown()


class TestPersistResult:
    """Tests for DB persistence."""

    def test_persist_result_returns_row_data(self):
        mapping = _make_mapping(evaluations={})
        dispatcher = EvaluationDispatcher(config=mapping)

        from temper_ai.optimization._schemas import EvaluationResult

        result = EvaluationResult(passed=True, score=0.85, details={"raw": "good"})

        row = dispatcher._persist_result("q1", "scored", "exec-1", result)

        assert row["evaluation_name"] == "q1"
        assert row["evaluator_type"] == "scored"
        assert row["agent_execution_id"] == "exec-1"
        assert row["score"] == 0.85
        assert row["passed"] is True
        assert row["details"] == {"raw": "good"}
        dispatcher.shutdown()

    def test_persist_with_session_factory(self):
        mock_session = MagicMock()

        @contextmanager
        def mock_factory():
            yield mock_session

        mapping = _make_mapping(evaluations={})
        dispatcher = EvaluationDispatcher(
            config=mapping,
            session_factory=mock_factory,
        )

        from temper_ai.optimization._schemas import EvaluationResult

        result = EvaluationResult(passed=True, score=0.75)

        with patch(
            "temper_ai.storage.database.models_evaluation.AgentEvaluationResult"
        ):
            row = dispatcher._persist_result("q1", "scored", "exec-1", result)

        assert row["score"] == 0.75
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        dispatcher.shutdown()

    def test_persist_db_error_swallowed(self):
        @contextmanager
        def failing_factory():
            raise RuntimeError("DB error")
            yield  # noqa: unreachable — needed for generator structure

        mapping = _make_mapping(evaluations={})
        dispatcher = EvaluationDispatcher(
            config=mapping,
            session_factory=failing_factory,
        )

        from temper_ai.optimization._schemas import EvaluationResult

        result = EvaluationResult(passed=True, score=0.5)

        # Should not raise
        row = dispatcher._persist_result("q1", "scored", "exec-1", result)
        assert row["score"] == 0.5
        dispatcher.shutdown()


class TestShutdown:
    """Tests for clean shutdown."""

    def test_shutdown_cleans_up(self):
        mapping = _make_mapping(evaluations={})
        dispatcher = EvaluationDispatcher(config=mapping)
        dispatcher.shutdown()
        # Should not raise on double shutdown
        dispatcher.shutdown()
        assert dispatcher._executor._shutdown  # executor marked as shut down


class TestBackgroundExecution:
    """Integration test: verify evaluations run in background threads."""

    def test_evaluation_runs_in_different_thread(self):
        eval_thread_ids = []

        def capture_thread(*args, **kwargs):
            eval_thread_ids.append(threading.current_thread().ident)
            return {"score": 0.9}

        mapping = _make_mapping(
            evaluations={"q1": _make_config()},
            agent_evaluations={"researcher": ["q1"]},
        )
        dispatcher = EvaluationDispatcher(config=mapping)

        with patch.object(dispatcher, "_run_evaluation", side_effect=capture_thread):
            dispatcher.dispatch(
                agent_name="researcher",
                agent_execution_id="exec-1",
                input_data={},
                output_data="output",
            )
            dispatcher.wait_all(timeout=10)

        main_thread_id = threading.current_thread().ident
        assert len(eval_thread_ids) == 1
        assert eval_thread_ids[0] != main_thread_id
        dispatcher.shutdown()
