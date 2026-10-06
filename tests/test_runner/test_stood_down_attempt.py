"""An attempt that stood down for a later one, outside Pi: its endings, its notes, its spend.

Since SW-84 (queue #61) an attempt whose wait a later attempt of the same run took over
raises ``ReplacedByLaterAttempt`` and stands down: it writes down only its own events, as
``cancelled`` marked ``replaced_by_later_attempt``, and leaves the run to the newer attempt.
Architecture's land check of #61 (architecture-check-61.json, notes 1-3) asked for three
things, which these tests hold (queue #64):

1. the two endings that aren't Pi's, which nothing tested: a box (``temper run-workflow``)
   writes no end into the run's row and sends the run's viewers no end-of-stream sentinel,
   and a server thread leaves the newer attempt its place, its live buffers and its wait;
2. writing a stood-down event down is best-effort: when the write fails (a database
   hiccup), the attempt still stands down. Before, the write's error took the place of the
   stand-down, so the attempt ended the run as failed: the newer attempt's run (SW-84);
3. the attempt's own event says what the attempt spent, as a parked or ended one does.

Model-free: every step is an agent node whose run is a mock. The gate is real, and so is the
take-over: a later attempt closes the older one's open wait as ``replaced`` in the database,
as stage/gate.py does when it reaches the same gate.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from temper_ai.cli.run_workflow import _update_run_row, cmd_run_workflow
from temper_ai.database import get_session
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import (
    decide_event,
    gate_events,
    get_event,
    get_events,
)
from temper_ai.observability.webhook_notifier import WEBHOOK_ENV_VAR
from temper_ai.runner.attempts import REPLACED_STATUS
from temper_ai.runner.execute import ExecuteResult
from temper_ai.runner.execute import execute_workflow as real_execute_workflow
from temper_ai.runner.models import WorkflowRun
from temper_ai.shared.types import ExecutionContext, Status
from temper_ai.stage import executor as executor_mod
from temper_ai.stage.exceptions import REPLACED_MARK, ReplacedByLaterAttempt
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.gate import REPLACED, WAITING
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.stage_node import StageNode
from temper_ai.streaming import RedisChunkNotifier
from tests.test_stage.test_executor import _make_agent_node
from tests.test_stage.test_loop_feedback import (
    FINDINGS,
    REQUEST_CHANGES,
    _node,
    _result,
)

RUN = "run-stood-down-1"
# The box a later attempt of the run started in: once it has, the run's row is its own.
LATER_BOX = "temper-run-the-later-attempt"


@pytest.fixture(autouse=True)
def _a_box_or_a_thread_and_a_later_attempt(request, tmp_path, monkeypatch):
    """The attempt waits at its gate in one thread while a later attempt takes the wait over
    from another, so both share the database: Postgres in the tier, else a SQLite file (an
    in-memory one is a single connection). The gate looks for its answer every 20 ms."""
    from temper_ai.database import init_database, reset_database
    from tests.conftest import TEST_DATABASE_URL

    if request.node.stash.get(TEST_DATABASE_URL, "").startswith("sqlite"):
        reset_database()
        init_database(f"sqlite:///{tmp_path / 'stood_down.db'}")
    monkeypatch.setattr(executor_mod, "GATE_POLL_SECONDS", 0.02)
    # The box's own sinks: its log file in the test's folder, no webhook.
    monkeypatch.setenv("TEMPER_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv(WEBHOOK_ENV_VAR, raising=False)
    # Left out as in tests/test_cli/test_run_workflow.py: the process-wide MCP manager, and
    # the signal handlers, which only the main thread may set (the box runs in a thread here).
    monkeypatch.setattr("temper_ai.cli.run_workflow._start_mcp_manager", lambda config_dir: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._stop_mcp_manager", lambda: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._install_signal_handlers", lambda *a: None)


def _workflow() -> tuple[list, MagicMock]:
    """``draft``, which spends, then stage ``review`` holding ``approve``, which waits on the
    owner first. Returns the workflow's steps and the gated step (to see it never ran)."""
    draft = _make_agent_node("draft", cost=0.25, tokens=300)
    approve = _make_agent_node("approve")
    approve.config.gate = True
    review = StageNode(NodeConfig(name="review", type="stage", depends_on=["draft"]), [approve])
    return [draft, review], approve


def _take_over(name: str, *, mark_row: bool = True) -> None:
    """A later attempt of the run reaches the gate at ``name`` and takes the older attempt's
    open wait over: the wait is closed as ``replaced`` (stage/gate.py). A later attempt in a
    box of its own has marked the run's row as its own by then."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        waits = [ev for ev in gate_events(RUN, name) if ev["status"] == WAITING]
        if waits:
            if mark_row:
                _update_run_row(RUN, spawner_handle=LATER_BOX, attempts=2)
            decide_event(waits[0]["id"], expect=(WAITING,), status=REPLACED,
                         data={"gate_status": REPLACED, "gate_replaced_by": "a later attempt"})
            return
        time.sleep(0.01)
    raise AssertionError(f"the wait at {name!r} never opened: {gate_events(RUN)}")


class _Viewers:
    """The box's line to the run's viewers (Redis Streams): what it sent them."""

    def __init__(self) -> None:
        self.ended: list[str] = []  # end-of-stream sentinels
        self.closed = 0

    def publish(self, *args, **kwargs) -> None:
        pass

    def publish_script_log(self, *args, **kwargs) -> None:
        pass

    def publish_terminal(self, execution_id: str) -> None:
        self.ended.append(execution_id)

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def queued(tmp_path):
    """The run's row, queued for a box."""
    with get_session() as session:
        session.add(WorkflowRun(execution_id=RUN, workflow_name="wf",
                                workspace_path=str(tmp_path), inputs={}, status="queued"))
    return RUN


def _run_box(steps: list, viewers: _Viewers, *, take_over: str) -> tuple[int, ExecuteResult]:
    """Run ``RUN`` in a box (``temper run-workflow``, in a thread) on ``steps``, with the real
    workflow engine, while a later attempt takes the wait at ``take_over`` over. Returns the
    box's exit code and what execute_workflow told it."""
    config = SimpleNamespace(name="wf", safety=None, outputs=None)
    runner_ctx = SimpleNamespace(
        graph_loader=SimpleNamespace(load_workflow=lambda name, inputs=None, **kw: (steps, config)),
        llm_providers={},
        memory_service=None,
    )
    told: list[ExecuteResult] = []
    ended: dict = {}

    def execute(**kwargs) -> ExecuteResult:
        told.append(real_execute_workflow(**kwargs))
        return told[-1]

    def box() -> None:
        try:
            ended["exit"] = cmd_run_workflow(
                argparse.Namespace(execution_id=RUN, config_dir=None, debug=False))
        except BaseException as exc:  # noqa: BLE001 - the test reads it
            ended["error"] = exc

    with (
        patch("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env",
              return_value=runner_ctx),
        patch("temper_ai.runner.execute.execute_workflow", side_effect=execute),
        patch("temper_ai.streaming.RedisChunkNotifier",
              lambda: RedisChunkNotifier(publisher=viewers)),
    ):
        thread = threading.Thread(target=box, daemon=True)
        thread.start()
        _take_over(take_over)
        thread.join(20)
    assert not thread.is_alive(), "the box never ended"
    if "error" in ended:
        raise ended["error"]
    return ended["exit"], told[0]


def _row() -> dict:
    with get_session() as session:
        row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == RUN)).one()
        return {"status": row.status, "spawner_handle": row.spawner_handle,
                "completed_at": row.completed_at, "result": row.result, "error": row.error}


# What the row says once the later attempt's box has it: nothing of the older box's end.
THE_LATER_ATTEMPTS_ROW = {"status": "running", "spawner_handle": LATER_BOX,
                          "completed_at": None, "result": None, "error": None}


def _level(event_id: str) -> str:
    """Which of the attempt's own events this is: the run's, the stage step's (written by
    _run_node_with_events), or the stage's own graph event."""
    event = get_event(event_id)
    if event["type"] == EventType.WORKFLOW_STARTED:
        return "run"
    parent = get_event(event["parent_id"]) if event["parent_id"] else None
    return "step" if parent and parent["type"] == EventType.WORKFLOW_STARTED else "stage"


def _stood_down() -> dict[str, dict]:
    """The attempt's events written down as stood down, by level."""
    return {_level(ev["id"]): ev for ev in get_events(execution_id=RUN, limit=None)
            if (ev["data"] or {}).get(REPLACED_MARK)}


# --- 1. The endings outside Pi -------------------------------------------------------------


def test_a_box_whose_gate_a_later_attempt_took_over_leaves_the_run_s_row_and_viewers_alone(
    queued,
):
    """execute_workflow says ``replaced``; the box writes no end into the run's row and sends
    no end-of-stream sentinel: both are the later attempt's (SW-84)."""
    steps, approve = _workflow()
    viewers = _Viewers()

    exit_code, told = _run_box(steps, viewers, take_over="approve")

    assert told.status == REPLACED_STATUS and told.exit_code == 0, told
    assert exit_code == 0
    approve.run.assert_not_called()
    assert _row() == THE_LATER_ATTEMPTS_ROW
    assert viewers.ended == [], "the later attempt's viewers were told the run is over"
    assert viewers.closed == 1, "the box's own connection is still closed"
    # Its own events, and only those, say it stood down: the run's, the step's, the stage's.
    stood_down = _stood_down()
    assert sorted(stood_down) == ["run", "stage", "step"]
    assert {ev["status"] for ev in stood_down.values()} == {Status.CANCELLED.value}


def test_a_server_thread_whose_gate_a_later_attempt_took_over_skips_the_run_s_end_steps(
    monkeypatch,
):
    """The server's own thread (api/routes.py) stands down too: the run's place stays the
    later attempt's, and so do its live buffers and its parked wait. Its own tool pool ends."""
    from temper_ai.api import routes

    later = threading.Event()  # the later attempt's cancel signal: its place in running
    state = SimpleNamespace(running={RUN: later})
    monkeypatch.setattr(routes, "_app_state", state)
    cleaned, seen_to = [], []
    monkeypatch.setattr(routes.ws_manager, "cleanup", cleaned.append)
    monkeypatch.setattr(routes, "_see_to_parked", lambda eid, ctx: seen_to.append(eid))
    context = ExecutionContext(
        run_id=RUN, workflow_name="wf", node_path="", agent_name="",
        event_recorder=EventRecorder(RUN), tool_executor=MagicMock(),
        cancel_event=threading.Event(), gate_registry={},
    )
    steps, approve = _workflow()

    thread = threading.Thread(target=routes._run_workflow_now,
                              args=(steps, {}, context, "wf", RUN), daemon=True)
    thread.start()
    _take_over("approve", mark_row=False)
    thread.join(20)

    assert not thread.is_alive(), "the thread never ended"
    approve.run.assert_not_called()
    assert state.running == {RUN: later}, "the later attempt's place was freed"
    assert cleaned == [], "the later attempt's live buffers were cleaned up"
    assert seen_to == [], "the later attempt's parked wait was seen to"
    context.tool_executor.shutdown.assert_called_once_with(wait=False)
    assert sorted(_stood_down()) == ["run", "stage", "step"]


def test_a_thread_that_stood_down_frees_its_own_place_and_never_a_later_attempt_s(monkeypatch):
    """_let_go(stood_down=True) frees the run's place only while it is the attempt's own."""
    from temper_ai.api import routes

    mine = SimpleNamespace(cancel_event=threading.Event(), park_at_gates=False)
    later = threading.Event()
    state = SimpleNamespace(running={RUN: later})
    monkeypatch.setattr(routes, "_app_state", state)

    routes._let_go(RUN, mine, stood_down=True)
    assert state.running == {RUN: later}

    state.running[RUN] = mine.cancel_event  # no later attempt has taken the place yet
    routes._let_go(RUN, mine, stood_down=True)
    assert RUN not in state.running

    # Without the stand-down, a thread of a run outside Pi frees the place whoever holds it
    # (the run is over): the flag is what keeps the later attempt's.
    state.running[RUN] = later
    routes._let_go(RUN, mine, stood_down=False)
    assert RUN not in state.running


# --- 2. Writing a stand-down down is best-effort ---------------------------------------------


@pytest.mark.parametrize("failing", ["step", "stage", "run"])
def test_a_stand_down_whose_note_cannot_be_written_still_stands_down(
    queued, failing, monkeypatch, caplog,
):
    """The database fails the write of one of the attempt's stood-down events: the step's
    (_run_node_with_events), the stage's or the run's (execute_graph). The attempt still
    stands down: nothing ends the run, its row is the later attempt's, its viewers hear no
    end. Before, the write's error took the place of the stand-down: the step, then the run,
    failed and the box wrote that into the row (#61's note 2)."""
    real_update = EventRecorder.update_event

    def update_event(self, event_id, status=None, data=None):
        if (data or {}).get(REPLACED_MARK) and _level(event_id) == failing:
            raise OperationalError("UPDATE events", {},
                                   Exception("server closed the connection unexpectedly"))
        return real_update(self, event_id, status=status, data=data)

    monkeypatch.setattr(EventRecorder, "update_event", update_event)
    ended_graphs: list[Exception] = []
    real_end_graph = executor_mod._end_graph

    def end_graph(exc, *args, **kwargs):
        ended_graphs.append(exc)
        return real_end_graph(exc, *args, **kwargs)

    monkeypatch.setattr(executor_mod, "_end_graph", end_graph)
    caplog.set_level(logging.WARNING, logger="temper_ai.stage.executor")
    steps, approve = _workflow()
    viewers = _Viewers()

    exit_code, told = _run_box(steps, viewers, take_over="approve")

    assert told.status == REPLACED_STATUS, told
    assert exit_code == 0
    assert ended_graphs == [], "a graph was ended as if the run had stopped or broken"
    approve.run.assert_not_called()
    assert _row() == THE_LATER_ATTEMPTS_ROW
    assert viewers.ended == []
    assert any("stood down" in r.getMessage() and "server closed the connection" in r.getMessage()
               for r in caplog.records), [r.getMessage() for r in caplog.records]
    # The other two are written down as usual.
    assert sorted(_stood_down()) == sorted({"run", "stage", "step"} - {failing})


# --- 3. The stood-down event says what the attempt spent -------------------------------------


def test_a_stood_down_attempt_s_own_event_says_what_it_spent():
    """As a parked or ended attempt's does: every finished step, and the ones a loop rewound
    and threw away (they were paid for), so per-attempt cost reports stay whole (#61's note 3)."""
    implement = _node(
        "implement",
        [_result("first attempt", {"commit": "aaa"}), _result("fix", {"commit": "bbb"})],
        input_map={"review_findings": "review.structured.findings"},
    )
    review = _node(
        "review",
        [_result("r1", {"verdict": "request_changes", "findings": FINDINGS}),
         _result("r2", {"verdict": "approve", "findings": []})],
        depends_on=["implement"], loop_to="implement", max_loops=2,
        loop_condition=REQUEST_CHANGES,
    )
    ship = _node("ship", [], depends_on=["review"])
    # A wait inside the step was taken over by a later attempt (stage/executor.py).
    ship.run.side_effect = ReplacedByLaterAttempt(
        "The approval at 'ship' was taken over by a later attempt of this run")
    context = ExecutionContext(
        run_id=RUN, workflow_name="wf", node_path="", agent_name="",
        event_recorder=EventRecorder(RUN), tool_executor=MagicMock(),
        cancel_event=threading.Event(),
    )

    with pytest.raises(ReplacedByLaterAttempt):
        execute_graph([implement, review, ship], {}, context, graph_name="wf", is_workflow=True)

    run_event = _stood_down()["run"]
    assert run_event["status"] == Status.CANCELLED.value
    # implement twice and review twice, at $0.01 and 10 tokens each: two of them were
    # thrown away by the rewind and are counted all the same.
    assert implement.run.call_count == 2 and review.run.call_count == 2
    assert run_event["data"]["cost_usd"] == pytest.approx(0.04)
    assert run_event["data"]["total_tokens"] == 40
