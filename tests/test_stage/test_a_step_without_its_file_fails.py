"""A step that completes without the file it had to write fails (required_files).

b010 on 2026-09-22: the tasks stage said it completed but never wrote tasks.json, its one
output, and the run went on as if it had.
"""

from temper_ai.shared.types import Status
from temper_ai.stage.executor import execute_graph
from tests.test_stage.test_executor import _make_agent_node, _make_context

OWED_WHEN_COMPLETE = {
    "path": "input.tasks_path",
    "when": {"source": "tasks.structured.status", "operator": "equals", "value": "COMPLETE"},
}


def _run(tmp_path, status, *, write, required=None):
    tasks_path = tmp_path / "tasks.json"
    if write:
        tasks_path.write_text('{"tasks": []}')
    tasks = _make_agent_node("tasks", structured_output={"status": status})
    tasks.config.required_files = [OWED_WHEN_COMPLETE] if required is None else required
    build = _make_agent_node("build", depends_on=["tasks"])
    result = execute_graph([tasks, build], {"tasks_path": str(tasks_path)}, _make_context(),
                           graph_name="loop", is_workflow=True)
    return result, tasks, build, tasks_path


def test_a_complete_plan_that_wrote_no_tasks_fails_and_nothing_builds(tmp_path):
    result, _, build, tasks_path = _run(tmp_path, "COMPLETE", write=False)

    got = result.node_results["tasks"]
    assert got.status == Status.FAILED
    assert got.error == f"it completed without writing {tasks_path} (input.tasks_path)"
    assert build.run.call_count == 0
    assert result.status == Status.FAILED


def test_a_complete_plan_that_wrote_its_tasks_goes_on(tmp_path):
    result, _, build, _ = _run(tmp_path, "COMPLETE", write=True)

    assert result.node_results["tasks"].status == Status.COMPLETED
    assert build.run.call_count == 1
    assert result.status == Status.COMPLETED


def test_a_blocked_plan_owes_no_tasks(tmp_path):
    result, _, _, _ = _run(tmp_path, "BLOCKED", write=False)

    assert result.node_results["tasks"].status == Status.COMPLETED


def test_a_file_whose_path_was_never_given_fails_too(tmp_path):
    tasks = _make_agent_node("tasks", structured_output={"status": "COMPLETE"})
    tasks.config.required_files = ["tasks.structured.tasks_path"]
    result = execute_graph([tasks], {}, _make_context(), graph_name="loop", is_workflow=True)

    got = result.node_results["tasks"]
    assert got.status == Status.FAILED
    assert got.error == "it completed without saying where tasks.structured.tasks_path is"


def test_the_loop_workflow_owes_its_tasks_when_the_plan_is_complete():
    from pathlib import Path

    import yaml

    loop = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "configs/epd/workflows/epd_loop.yaml").read_text())
    tasks = next(n for n in loop["workflow"]["nodes"] if n["name"] == "tasks")
    assert tasks["required_files"] == [OWED_WHEN_COMPLETE]
