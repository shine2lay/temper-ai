"""execute_workflow — the worker's path (`temper run-workflow`) into a run.

The tool executor is made inside execute_workflow and never leaves it (the
caller gets an ExecuteResult), so execute_workflow is the only thing that can
shut it down. It did not: the API routes and `temper run` shut theirs down
in a `finally`, this path leaked its thread pool — and, once the executor
had a scratch directory, would have leaked one directory per production run.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.runner import execute as execute_mod
from temper_ai.runner.execute import execute_workflow


@pytest.fixture
def runner_ctx():
    """The least a RunnerContext needs to reach execute_graph: an empty workflow."""
    config = SimpleNamespace(name="wf", safety=None, outputs=None)
    return SimpleNamespace(
        graph_loader=SimpleNamespace(load_workflow=lambda name, inputs: ([], config)),
        llm_providers={},
        memory_service=None,
    )


def _run(runner_ctx, monkeypatch, tmp_path, *, graph):
    """Run a workflow whose whole body is `graph(context)`; return (result, scratch)."""
    seen: dict = {}

    def fake_execute_graph(nodes, inputs, context, **kwargs):
        # A node strays: the run now has a scratch directory to clean up.
        seen["scratch"] = Path(context.tool_executor.scratch_dir)
        assert seen["scratch"].is_dir()
        return graph(context)

    monkeypatch.setattr(execute_mod, "execute_graph", fake_execute_graph)
    result = execute_workflow(
        execution_id="run-1",
        workflow_name="wf",
        workspace_path=str(tmp_path),
        inputs={},
        runner_ctx=runner_ctx,
    )
    return result, seen["scratch"]


def test_the_executor_is_shut_down_when_the_run_completes(
    runner_ctx, monkeypatch, tmp_path
):
    done = SimpleNamespace(status="completed", cost_usd=0.0, total_tokens=0)
    result, scratch = _run(runner_ctx, monkeypatch, tmp_path, graph=lambda ctx: done)
    assert result.status == "completed"
    assert not scratch.exists()


def test_the_executor_is_shut_down_when_the_run_raises(
    runner_ctx, monkeypatch, tmp_path
):
    def boom(ctx):
        raise RuntimeError("node exploded")

    result, scratch = _run(runner_ctx, monkeypatch, tmp_path, graph=boom)
    assert result.status == "failed"
    assert result.error == "node exploded"
    assert not scratch.exists()
