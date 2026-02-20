"""Tests for events/_cross_workflow.py."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

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

    def test_run_workflow_logs(self, caplog):
        import logging

        trigger = CrossWorkflowTrigger()
        with caplog.at_level(logging.INFO, logger="temper_ai.events._cross_workflow"):
            trigger._run_workflow("wf.yaml", {"a": 1}, "tid-1")

        assert "tid-1" in caplog.text
