"""Tests for events/_cross_workflow.py."""

import threading
import time
from unittest.mock import MagicMock, patch

from temper_ai.events._cross_workflow import CrossWorkflowTrigger


class TestCrossWorkflowTrigger:
    def test_trigger_returns_str_id(self):
        trigger = CrossWorkflowTrigger()
        result = trigger.trigger("workflow.yaml")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_trigger_spawns_daemon_thread(self):
        trigger = CrossWorkflowTrigger()
        spawned_threads = []
        original_start = threading.Thread.start

        def patched_start(self):
            spawned_threads.append(self)
            original_start(self)

        with patch.object(threading.Thread, "start", patched_start):
            trigger.trigger("workflow.yaml")

        assert len(spawned_threads) == 1
        assert spawned_threads[0].daemon is True

    def test_trigger_passes_inputs(self):
        trigger = CrossWorkflowTrigger()
        called_with = []

        def fake_run(workflow_path, inputs, trigger_id):
            called_with.append((workflow_path, inputs))

        with patch.object(trigger, "_run_workflow", side_effect=fake_run):
            trigger.trigger("some/workflow.yaml", inputs={"key": "val"})
            time.sleep(0.05)  # wait for daemon thread

        assert len(called_with) == 1
        assert called_with[0][0] == "some/workflow.yaml"
        assert called_with[0][1] == {"key": "val"}

    def test_trigger_unique_ids(self):
        trigger = CrossWorkflowTrigger()
        id1 = trigger.trigger("wf.yaml")
        id2 = trigger.trigger("wf.yaml")
        assert id1 != id2

    def test_trigger_empty_inputs_default(self):
        trigger = CrossWorkflowTrigger()
        called_with = []

        def fake_run(workflow_path, inputs, trigger_id):
            called_with.append(inputs)

        with patch.object(trigger, "_run_workflow", side_effect=fake_run):
            trigger.trigger("wf.yaml")
            time.sleep(0.05)  # wait for daemon thread

        assert called_with[0] == {}

    @patch("temper_ai.interfaces.server.workflow_runner.WorkflowRunner")
    def test_run_workflow_logs(self, mock_runner_cls, caplog):
        import logging

        mock_runner = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_runner.run.return_value = mock_result
        mock_runner_cls.return_value = mock_runner

        trigger = CrossWorkflowTrigger()
        with caplog.at_level(logging.INFO, logger="temper_ai.events._cross_workflow"):
            trigger._run_workflow("wf.yaml", {"a": 1}, "tid-1")

        assert "tid-1" in caplog.text

    @patch("temper_ai.interfaces.server.workflow_runner.WorkflowRunner")
    def test_run_workflow_delegates_to_workflow_runner(self, mock_runner_cls):
        """_run_workflow executes via WorkflowRunner."""
        mock_runner = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_runner.run.return_value = mock_result
        mock_runner_cls.return_value = mock_runner

        trigger = CrossWorkflowTrigger()
        trigger._run_workflow("path/to/wf.yaml", {"key": "val"}, "tid-42")

        mock_runner.run.assert_called_once_with(
            "path/to/wf.yaml",
            input_data={"key": "val"},
            run_id="tid-42",
        )

    @patch("temper_ai.interfaces.server.workflow_runner.WorkflowRunner")
    def test_run_workflow_sets_trigger_type_event(self, mock_runner_cls):
        """WorkflowRunnerConfig uses trigger_type='event'."""
        mock_runner = MagicMock()
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_runner.run.return_value = mock_result
        mock_runner_cls.return_value = mock_runner

        trigger = CrossWorkflowTrigger()
        trigger._run_workflow("wf.yaml", {}, "tid-1")

        config = mock_runner_cls.call_args.kwargs["config"]
        assert config.trigger_type == "event"

    @patch("temper_ai.interfaces.server.workflow_runner.WorkflowRunner")
    def test_run_workflow_file_not_found_logs_error(self, mock_runner_cls, caplog):
        """FileNotFoundError is caught and logged, not raised."""
        import logging

        mock_runner = MagicMock()
        mock_runner.run.side_effect = FileNotFoundError("not found")
        mock_runner_cls.return_value = mock_runner

        trigger = CrossWorkflowTrigger()
        with caplog.at_level(logging.ERROR, logger="temper_ai.events._cross_workflow"):
            trigger._run_workflow("nonexistent.yaml", {}, "tid-err")

        assert "not found" in caplog.text

    @patch("temper_ai.interfaces.server.workflow_runner.WorkflowRunner")
    def test_run_workflow_generic_error_logs(self, mock_runner_cls, caplog):
        """Generic exceptions are caught and logged, not raised."""
        import logging

        mock_runner = MagicMock()
        mock_runner.run.side_effect = RuntimeError("boom")
        mock_runner_cls.return_value = mock_runner

        trigger = CrossWorkflowTrigger()
        with caplog.at_level(logging.ERROR, logger="temper_ai.events._cross_workflow"):
            trigger._run_workflow("wf.yaml", {}, "tid-err2")

        assert "boom" in caplog.text


class TestCrossWorkflowTriggerWithExecutionService:
    """Tests for trigger() with execution_service delegation."""

    def test_trigger_delegates_to_execution_service(self):
        """When execution_service is provided, trigger() calls submit_workflow."""
        mock_svc = MagicMock()
        mock_svc.submit_workflow.return_value = "exec-abc"

        trigger = CrossWorkflowTrigger(execution_service=mock_svc)
        result = trigger.trigger("some/workflow.yaml", inputs={"key": "val"})

        assert isinstance(result, str)
        mock_svc.submit_workflow.assert_called_once()
        call_kwargs = mock_svc.submit_workflow.call_args
        assert call_kwargs[0][0] == "some/workflow.yaml"
        assert call_kwargs[1]["input_data"] == {"key": "val"}

    def test_trigger_with_service_no_thread_spawn(self):
        """With execution_service, no daemon thread should be spawned."""
        mock_svc = MagicMock()
        mock_svc.submit_workflow.return_value = "exec-xyz"

        trigger = CrossWorkflowTrigger(execution_service=mock_svc)
        spawned = []
        original_start = threading.Thread.start

        def patched_start(self):
            spawned.append(self)
            original_start(self)

        with patch.object(threading.Thread, "start", patched_start):
            trigger.trigger("wf.yaml")

        assert len(spawned) == 0

    def test_trigger_without_service_falls_back_to_thread(self):
        """Without execution_service, trigger() should spawn a daemon thread."""
        trigger = CrossWorkflowTrigger(execution_service=None)
        spawned = []
        original_start = threading.Thread.start

        def patched_start(self):
            spawned.append(self)
            original_start(self)

        with patch.object(threading.Thread, "start", patched_start):
            trigger.trigger("wf.yaml")

        assert len(spawned) == 1
        assert spawned[0].daemon is True

    def test_trigger_with_service_passes_run_id(self):
        """The trigger_id should be passed as run_id to submit_workflow."""
        mock_svc = MagicMock()
        mock_svc.submit_workflow.return_value = "exec-123"

        trigger = CrossWorkflowTrigger(execution_service=mock_svc)
        trigger_id = trigger.trigger("wf.yaml")

        call_kwargs = mock_svc.submit_workflow.call_args
        assert call_kwargs[1]["run_id"] == trigger_id
