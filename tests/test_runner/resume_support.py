"""A simulated box gets the actual watcher's reservation and spawner environment.

No hand-made token or baseline: callers first queue through the real server path.
Capture only subprocess creation; the CLI then runs in the fixture's process.
"""

from types import SimpleNamespace
from unittest.mock import patch


def seed_legacy_interrupted_run(execution_id, workflow, workspace_path, inputs):
    """Original records of an intact pre-deploy run, without any resume credential."""
    from temper_ai.api.routes import RunRequest, _start_run_external
    from temper_ai.database import get_session
    from temper_ai.observability.event_recorder import EventRecorder
    from temper_ai.observability.event_types import EventType
    from temper_ai.observability.models import Event
    from temper_ai.runner.models import WorkflowRun

    # The server's actual Start writer; deliberately not Resume/reserve/launch.
    _start_run_external(execution_id, RunRequest(workflow=workflow,
                        workspace_path=workspace_path, inputs=inputs), SimpleNamespace(name=workflow))
    recorder = EventRecorder(execution_id)
    # Same start_data shape/writer as stage.executor.execute_graph, including the
    # original (pre-default-fill) inputs, not the viewer's later reconstruction.
    attempt = recorder.record(EventType.WORKFLOW_STARTED, status="running", data={
        "name": workflow, "node_count": 2, "input_data": inputs, "workspace_path": workspace_path,
    })
    recorder.update_event(attempt, status="interrupted", data={"cost_usd": 0.0, "total_tokens": 0})
    with get_session() as session:
        row = session.get(WorkflowRun, execution_id)
        row.status = "interrupted"
        row.started_at = session.get(Event, attempt).timestamp
        session.add(row)


def install_launch_token(execution_id, monkeypatch, *, lane=None):
    from temper_ai.cli.watch_queue import _load_queued
    from temper_ai.runner.resume_authority import RESERVATION_ENV, bind_resume_launch
    from temper_ai.spawner.subprocess_spawner import SubprocessSpawner

    queued = next(row for row in _load_queued(lane) if row["execution_id"] == execution_id)
    captured = {}

    def create_process(*args, **kwargs):
        captured.update(kwargs["env"])
        return SimpleNamespace(pid=43111, wait=lambda: 0)

    with (patch("temper_ai.spawner.subprocess_spawner.subprocess.Popen", create_process),
          patch("temper_ai.spawner.subprocess_spawner.threading.Thread.start"),
          bind_resume_launch(execution_id, queued.get("resume_token"))):
        SubprocessSpawner().spawn(execution_id)
    if RESERVATION_ENV in captured:
        monkeypatch.setenv(RESERVATION_ENV, captured[RESERVATION_ENV])
    else:
        monkeypatch.delenv(RESERVATION_ENV, raising=False)
