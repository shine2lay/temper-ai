"""Declared input defaults on every way a run starts, with the committed zero-cost workflow
``ci_input_defaults`` loaded from configs/ as the server loads it (the live check runs the same).

A run that leaves an input out, sends it as null or as empty text records and uses the declared
default; a given value is kept; what the run records is what its script printed, and no script
ever prints the word None. Script agents only: no model, no network.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_pi_agent import support as sup

REPO_CONFIGS = Path(__file__).resolve().parents[2] / "configs"
WORKFLOW = "ci_input_defaults"
WORD, MUST, STAGE_WORD = "from-the-default", "required-but-defaulted", "from-the-stage-default"
DEFAULTS = {"word": WORD, "must": MUST}


def _loader():
    from temper_ai.cli.check import _FileConfigs
    from temper_ai.stage.loader import GraphLoader

    return GraphLoader(_FileConfigs(REPO_CONFIGS))  # type: ignore[arg-type]


@pytest.fixture
def api(tmp_path, request, monkeypatch):
    from fastapi.testclient import TestClient

    from temper_ai.api.app_state import AppState
    from temper_ai.api.routes import init_app_state
    from temper_ai.config import ConfigStore
    from temper_ai.database import init_database, reset_database
    from temper_ai.memory import InMemoryStore, MemoryService
    from temper_ai.server import app
    from tests.conftest import TEST_DATABASE_URL

    url = request.node.stash.get(TEST_DATABASE_URL, "")
    if url.startswith("sqlite"):
        # The run's thread shares the database: a file, not one in-memory connection.
        url = f"sqlite:///{tmp_path / 'defaults.db'}"
        reset_database()
        request.node.stash[TEST_DATABASE_URL] = url
        init_database(url)
    monkeypatch.setenv("TEMPER_DATABASE_URL", url)
    monkeypatch.setenv("TEMPER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "inprocess")
    state = AppState(config_store=ConfigStore(), graph_loader=_loader(), llm_providers={},
                     memory_service=MemoryService(InMemoryStore()))
    init_app_state(state)
    yield SimpleNamespace(client=TestClient(app), state=state, ws=tmp_path / "ws")
    sup.stop_running(state)
    for thread in [t for t in threading.enumerate() if t.name.startswith("temper-run-")]:
        thread.join(timeout=5)
    if url.startswith("sqlite"):
        reset_database()


def _post(api, inputs: dict) -> dict:
    api.ws.mkdir(parents=True, exist_ok=True)
    r = api.client.post("/api/runs", json={"workflow": WORKFLOW, "inputs": inputs,
                                           "workspace_path": str(api.ws)})
    assert r.status_code == 200, r.text
    return r.json()


def _printed(eid: str) -> tuple[dict[str, dict], list[str]]:
    """What each echo step printed, by where it ran (workflow / stage), and the raw outputs."""
    done = sup.events(eid, event_type="agent.completed")
    outputs = [str((e["data"] or {}).get("output", "")) for e in done]
    seen = {}
    for text in outputs:
        line = json.loads(text.strip().splitlines()[-1])
        seen[line["where"]] = line
    return seen, outputs


def _recorded(eid: str, attempt: int = -1) -> dict:
    return dict((sup.attempts(eid)[attempt]["data"] or {}).get("input_data") or {})


CASES = [
    # (what the run sends, what it records, what the workflow's step prints for word/must/plain)
    ({}, DEFAULTS, (WORD, MUST, "")),
    ({"word": None, "must": None, "plain": None}, {**DEFAULTS, "plain": None}, (WORD, MUST, "")),
    ({"word": "", "must": "", "plain": ""}, {**DEFAULTS, "plain": ""}, (WORD, MUST, "")),
    ({"word": "given", "must": "given too", "plain": "plain given"},
     {"word": "given", "must": "given too", "plain": "plain given"},
     ("given", "given too", "plain given")),
    # the dashboard's form: defaults pre-filled, a field the owner cleared left out
    (dict(DEFAULTS), DEFAULTS, (WORD, MUST, "")),
    ({"must": MUST}, DEFAULTS, (WORD, MUST, "")),
]


@pytest.mark.parametrize("sent, recorded, printed", CASES,
                         ids=["absent", "null", "empty", "given", "form", "form-cleared"])
def test_a_run_records_and_uses_the_declared_defaults(api, sent, recorded, printed):
    eid = _post(api, sent)["execution_id"]
    assert sup.wait_ended(eid)[-1]["status"] == "completed"
    assert _recorded(eid) == recorded
    seen, outputs = _printed(eid)
    word, must, plain = printed
    assert seen["workflow"] == {"where": "workflow", "word": word, "must": must, "plain": plain,
                                "plain_bare": plain, "word_env": word, "plain_env": plain}
    # what the run recorded is what its script got
    assert (seen["workflow"]["word"], seen["workflow"]["must"]) == (recorded["word"],
                                                                    recorded["must"])
    # the stage's input_map leaves word out: its own default, whatever the run sent
    assert seen["stage"] == {"where": "stage", "word": STAGE_WORD, "must": must, "plain": plain,
                             "plain_bare": plain, "word_env": STAGE_WORD, "plain_env": plain}
    assert len(outputs) == 2 and not any("None" in text for text in outputs)


def test_a_run_queued_for_a_box_carries_the_defaults(api, monkeypatch):
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    started = _post(api, {"word": "", "plain": None})
    assert started["status"] == "queued"
    with get_session() as session:
        row = session.exec(select(WorkflowRun).where(
            WorkflowRun.execution_id == started["execution_id"])).one()
        assert row.inputs == {**DEFAULTS, "plain": None}


# --- a resume and a fork of a run that started without the input -------------------------------


def _queued_inputs(execution_id: str) -> dict:
    from sqlmodel import select

    from temper_ai.database import get_session
    from temper_ai.runner.models import WorkflowRun

    with get_session() as session:
        return session.exec(select(WorkflowRun).where(
            WorkflowRun.execution_id == execution_id)).one().inputs


def _checkpoint(execution_id: str, node: str) -> int:
    from temper_ai.checkpoint.service import CheckpointService
    from temper_ai.stage.executor import NodeResult, Status

    service = CheckpointService(execution_id)
    service.save_node_completed(node, NodeResult(status=Status.COMPLETED, output=f"{node} done"))
    return service.get_latest_sequence()


def test_a_resume_of_a_run_started_without_the_input_is_queued_with_the_default(api, monkeypatch):
    from temper_ai.api import routes

    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    _checkpoint("old-1", "echo")
    # a run started before defaults were filled in recorded only what it was sent
    earlier = {"workflow_name": WORKFLOW, "status": "interrupted", "input_data": {"plain": "p"},
               "workspace_path": str(api.ws)}
    from tests.test_runner.resume_support import seed_legacy_interrupted_run

    # Server Start's original records, without any post-deploy resume credentials.
    seed_legacy_interrupted_run("old-1", WORKFLOW, str(api.ws), {"plain": "p"})
    monkeypatch.setattr(routes, "get_workflow_execution", lambda _eid: dict(earlier))
    resp = routes.resume_run("old-1")
    assert resp.status == "queued"
    assert _queued_inputs("old-1") == {**DEFAULTS, "plain": "p"}


def test_a_fork_that_leaves_the_input_out_is_queued_with_the_default(api, monkeypatch):
    from temper_ai.api import routes

    monkeypatch.setenv("TEMPER_EXECUTION_MODE", "external")
    at = _checkpoint("src-1", "echo")
    resp = routes.fork_run(routes.ForkRequest(workflow=WORKFLOW, source_execution_id="src-1",
                                              sequence=at, inputs={"word": None}))
    assert resp.status == "queued"
    assert _queued_inputs(resp.execution_id) == DEFAULTS


def _box_run(tmp_path, execution_id: str, inputs: dict, initial_outputs: dict | None):
    """What a run's box does (temper run-workflow): execute_workflow on what was queued."""
    from temper_ai.runner.execute import execute_workflow

    ctx = SimpleNamespace(graph_loader=_loader(), llm_providers={}, memory_service=None)
    (tmp_path / "ws").mkdir(exist_ok=True)
    return execute_workflow(execution_id=execution_id, workflow_name=WORKFLOW,
                            workspace_path=str(tmp_path / "ws"), inputs=inputs, runner_ctx=ctx,
                            initial_outputs=initial_outputs)


def test_a_resume_in_its_box_runs_with_the_defaults_a_run_queued_before_them_lacks(tmp_path):
    # queued before the fix: only what the run was sent; a resume restores what had finished
    result = _box_run(tmp_path, "resume-1", {"word": ""}, initial_outputs={})
    assert result.status == "completed", result.error
    assert _recorded("resume-1") == DEFAULTS
    seen, outputs = _printed("resume-1")
    assert (seen["workflow"]["word"], seen["workflow"]["must"]) == (WORD, MUST)
    assert not any("None" in text for text in outputs)


def test_a_fork_in_its_box_gives_the_steps_it_reruns_the_defaults(tmp_path):
    from temper_ai.checkpoint.service import CheckpointService

    # the server copied the source's checkpoints up to the fork point under the fork's id
    _checkpoint("fork-1", "echo")
    restored = CheckpointService("fork-1").reconstruct()
    result = _box_run(tmp_path, "fork-1", {}, initial_outputs=restored)
    assert result.status == "completed", result.error
    assert _recorded("fork-1") == DEFAULTS
    seen, outputs = _printed("fork-1")
    assert list(seen) == ["stage"]  # the step before the fork point is not run again
    assert seen["stage"]["must"] == MUST and seen["stage"]["word"] == STAGE_WORD
    assert not any("None" in text for text in outputs)
