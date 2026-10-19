"""Every way a run ends leaves what it spent, and the run list says the same as the run's page.

Before queue #65 (Design's rm-518f5f25, item 1) a run thrown out (cancelled by hand, or
broken) wrote no totals on its workflow event (stage/executor.py ``_end_graph``), and the
run list read a missing total as 0: d3c7305b listed $0 while its page said $8.61, which
itself left out a rewound attempt (its model calls add up to $9.03).

Now:

- a thrown-out run's event carries ``cost_usd`` / ``total_tokens`` by the completed-run rule
  (finished steps, rewound attempts) plus what the step in flight had spent;
- a run whose event has none (every run from before, a box that died) is read through one
  rule (observability/run_totals.py), the same for the list and the page, one query a page;
- runs that ended keep the totals their events carry.

Queue #104 (Frontend's page-truth check rm-3423c6d1): Team run 38ba79c6 parked on the owner
with its team's step in flight, then was cancelled, and listed $0 while its model calls add
up to $10.22. A park note counts the finished steps only (``_note_parked``) and
``cancel_parked`` writes no totals, so a note's figure is now a floor: a run waiting on the
owner, or cancelled while it waited, shows the larger of the note's and its recorded spend,
cost and tokens each, read in the same one query.

Model-free: every step is an agent node whose run is a function that records what a real
agent records (its start, its model calls with their cost, its end) and hands a result back.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from temper_ai.api import data_service
from temper_ai.api.data_service import (
    _sum_node_metric,
    get_workflow_execution,
    list_workflow_executions,
)
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import get_events, record
from temper_ai.runner import parked
from temper_ai.shared.types import (
    AgentResult,
    ExecutionContext,
    NodeResult,
    Status,
    TokenUsage,
)
from temper_ai.stage import executor as executor_mod
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import RunParked
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.models import NodeConfig

RUN = "run-end-totals-1"


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id=RUN, workflow_name="wf", node_path="", agent_name="",
        event_recorder=EventRecorder(RUN), tool_executor=MagicMock(),
        cancel_event=threading.Event(),
    )


def _spends(ctx: ExecutionContext, name: str, cost: float, tokens: int) -> str:
    """An agent of the step starts and makes one model call that costs this much."""
    agent_id = ctx.event_recorder.record(
        EventType.AGENT_STARTED, parent_id=ctx.parent_event_id, execution_id=ctx.run_id,
        status="running", data={"agent_name": name})
    ctx.event_recorder.record(
        EventType.LLM_CALL_COMPLETED, parent_id=agent_id, execution_id=ctx.run_id,
        status="completed", data={"iteration": 1, "cost_usd": cost, "total_tokens": tokens})
    return agent_id


def _step(name: str, cost: float, tokens: int, *, structured: list[dict] | None = None,
          then: Callable[[ExecutionContext, str], NodeResult] | None = None, **config) -> AgentNode:
    """A step whose agent spends ``cost``/``tokens`` each go and says so at its end, as
    agent/llm_agent.py does; ``then`` replaces the end (a step thrown out in flight)."""
    node = AgentNode(NodeConfig(name=name, **config), {"name": name, "type": "llm"})
    outputs = list(structured or [])

    def run(_resolved, ctx: ExecutionContext) -> NodeResult:
        agent_id = _spends(ctx, name, cost, tokens)
        if then is not None:
            return then(ctx, agent_id)
        ctx.event_recorder.record(
            EventType.AGENT_COMPLETED, parent_id=agent_id, execution_id=ctx.run_id,
            status="completed",
            data={"agent_name": name, "cost_usd": cost, "tokens": tokens, "llm_calls": 1})
        out = outputs.pop(0) if outputs else None
        return NodeResult(
            status=Status.COMPLETED, output="ok", structured_output=out,
            agent_results=[AgentResult(status=Status.COMPLETED, output="ok", structured_output=out,
                                       tokens=TokenUsage(total_tokens=tokens), cost_usd=cost,
                                       llm_calls=1, tool_calls=2)],
            cost_usd=cost, total_tokens=tokens,
        )

    node.run = MagicMock(side_effect=run)
    return node


def _stopped_in_flight(ctx: ExecutionContext, agent_id: str) -> NodeResult:
    """Someone stops the run while the step's model call is out: the agent ends failed with no
    cost said and hands back a result that cost nothing (agent/llm_agent.py on an error)."""
    ctx.cancel_event.set()
    ctx.event_recorder.record(
        EventType.AGENT_FAILED, parent_id=agent_id, execution_id=ctx.run_id, status="failed",
        data={"agent_name": "build", "error": "cancelled", "error_type": "CancellationError"})
    return NodeResult(status=Status.FAILED, error="cancelled")


def _run_event() -> dict:
    return next(e for e in get_events(execution_id=RUN, limit=None)
                if e["type"] == EventType.WORKFLOW_STARTED.value)


def _listed() -> dict:
    return next(r for r in list_workflow_executions(limit=50)["runs"] if r["id"] == RUN)


def _list_and_page_agree(cost: float, tokens: int) -> dict:
    """The run list and the run's page give the run the same totals, these."""
    listed, page = _listed(), get_workflow_execution(RUN)
    assert page is not None
    assert listed["total_cost_usd"] == pytest.approx(cost)
    assert page["total_cost_usd"] == pytest.approx(cost)
    assert listed["total_tokens"] == page["total_tokens"] == tokens
    return page


def test_a_run_cancelled_mid_step_writes_what_its_steps_and_the_step_in_flight_spent():
    draft = _step("draft", 0.25, 300)
    build = _step("build", 0.4, 500, depends_on=["draft"], then=_stopped_in_flight)
    ship = _step("ship", 9.0, 9000, depends_on=["build"])

    result = execute_graph([draft, build, ship], {}, _context(), graph_name="wf", is_workflow=True)

    assert result.status == Status.CANCELLED
    assert ship.run.call_count == 0
    data = _run_event()["data"]
    assert _run_event()["status"] == Status.CANCELLED.value
    # draft's finished step, and the $0.40 build's model call cost before the stop.
    assert data["cost_usd"] == pytest.approx(0.65)
    assert data["total_tokens"] == 800
    assert result.cost_usd == pytest.approx(0.65)
    _list_and_page_agree(0.65, 800)


def test_a_cancelled_run_counts_the_attempts_a_loop_rewound():
    implement = _step("implement", 0.1, 100)
    review = _step(
        "review", 0.05, 50, depends_on=["implement"], loop_to="implement", max_loops=2,
        structured=[{"verdict": "request_changes"}, {"verdict": "approve"}],
        loop_condition={"source": "review.structured.verdict", "operator": "equals",
                        "value": "request_changes"},
    )
    ship = _step("ship", 0.4, 400, depends_on=["review"], then=_stopped_in_flight)

    execute_graph([implement, review, ship], {}, _context(), graph_name="wf", is_workflow=True)

    assert implement.run.call_count == 2 and review.run.call_count == 2
    data = _run_event()["data"]
    # Both goes of implement and of review (the first ones rewound), and ship's call in flight.
    assert data["cost_usd"] == pytest.approx(0.7)
    assert data["total_tokens"] == 700
    # The rewound goes' calls, as a completed run publishes them.
    assert data["retired_llm_calls"] == 2
    assert data["retired_tool_calls"] == 4
    page = _list_and_page_agree(0.7, 700)
    # The page's node tree keeps one go per step; the total is never below what it shows.
    assert page["total_cost_usd"] >= _sum_node_metric(page["nodes"], "cost_usd")


def test_a_run_that_broke_mid_step_writes_what_its_steps_spent(monkeypatch):
    """A failure that throws the run out after a step's agent spent and ended, before the
    step's result was kept: the agent's own record still counts."""
    draft = _step("draft", 0.25, 300)
    build = _step("build", 0.4, 500, depends_on=["draft"])
    real_check = executor_mod._required_file_missing

    def disk_gone(node, *args, **kwargs):
        if node.name == "build":
            raise RuntimeError("the workspace disk went away")
        return real_check(node, *args, **kwargs)

    monkeypatch.setattr(executor_mod, "_required_file_missing", disk_gone)

    result = execute_graph([draft, build], {}, _context(), graph_name="wf", is_workflow=True)

    assert result.status == Status.FAILED
    event = _run_event()
    assert event["status"] == Status.FAILED.value
    assert "the workspace disk went away" in event["data"]["error"]
    assert event["data"]["cost_usd"] == pytest.approx(0.65)
    assert event["data"]["total_tokens"] == 800
    _list_and_page_agree(0.65, 800)


def test_a_run_whose_event_has_no_totals_is_read_from_what_its_agents_recorded():
    """A run from before #65, cancelled, as d3c7305b: a step that a loop sent round again
    (two goes, one name in the page's tree) and a step in flight with no end. Nothing on the
    event; the list and the page read the same figure from the events."""
    wf = record(EventType.WORKFLOW_STARTED, execution_id=RUN, status="cancelled",
                data={"name": "wf", "error": "Workflow cancelled by user", "duration_seconds": 9.0})
    for cost, tokens in ((0.42, 420), (0.31, 310)):  # copy_revise, twice
        stage = record(EventType.STAGE_STARTED, parent_id=wf, execution_id=RUN, status="completed",
                       data={"name": "copy_revise", "type": "agent", "cost_usd": cost,
                             "total_tokens": tokens})
        agent = record(EventType.AGENT_STARTED, parent_id=stage, execution_id=RUN,
                       status="running", data={"agent_name": "copy_revise"})
        record(EventType.LLM_CALL_COMPLETED, parent_id=agent, execution_id=RUN,
               status="completed", data={"iteration": 1, "cost_usd": cost, "total_tokens": tokens})
        record(EventType.AGENT_COMPLETED, parent_id=agent, execution_id=RUN, status="completed",
               data={"agent_name": "copy_revise", "cost_usd": cost, "tokens": tokens})
    stage = record(EventType.STAGE_STARTED, parent_id=wf, execution_id=RUN, status="running",
                   data={"name": "concepts", "type": "agent"})
    agent = record(EventType.AGENT_STARTED, parent_id=stage, execution_id=RUN, status="running",
                   data={"agent_name": "concepts"})
    record(EventType.LLM_CALL_COMPLETED, parent_id=agent, execution_id=RUN, status="completed",
           data={"iteration": 1, "cost_usd": 1.5, "total_tokens": 1500})

    page = _list_and_page_agree(2.23, 2230)
    assert page["total_cost_usd"] >= _sum_node_metric(page["nodes"], "cost_usd")


def test_a_completed_run_keeps_the_totals_its_end_wrote():
    draft = _step("draft", 0.25, 300)
    build = _step("build", 0.4, 500, depends_on=["draft"])

    execute_graph([draft, build], {}, _context(), graph_name="wf", is_workflow=True)

    event = _run_event()
    assert event["status"] == Status.COMPLETED.value
    assert event["data"]["cost_usd"] == pytest.approx(0.65)
    assert event["data"]["total_tokens"] == 800
    _list_and_page_agree(0.65, 800)


def test_the_list_reads_its_page_s_runs_without_totals_in_one_query(monkeypatch):
    for n in range(3):
        wf = record(EventType.WORKFLOW_STARTED, execution_id=f"old-{n}", status="cancelled",
                    data={"name": "wf"})
        record(EventType.LLM_CALL_COMPLETED, parent_id=wf, execution_id=f"old-{n}",
               status="completed", data={"cost_usd": 0.1 * (n + 1), "total_tokens": n + 1})
    record(EventType.WORKFLOW_STARTED, execution_id="new", status="completed",
           data={"name": "wf", "cost_usd": 2.0, "total_tokens": 20})
    # A run waiting on the owner: its note is a floor, read in the same query (#104).
    wf = record(EventType.WORKFLOW_STARTED, execution_id="parked", status="waiting",
                data={"name": "wf", "parked": {"cost_usd": 0.05, "total_tokens": 5}})
    record(EventType.LLM_CALL_COMPLETED, parent_id=wf, execution_id="parked",
           status="completed", data={"cost_usd": 0.5, "total_tokens": 50})
    asked: list[list[str]] = []
    real = data_service.run_spend

    def spy(ids):
        asked.append(sorted(ids))
        return real(ids)

    monkeypatch.setattr(data_service, "run_spend", spy)

    runs = {r["id"]: r for r in list_workflow_executions(limit=50)["runs"]}

    assert asked == [["old-0", "old-1", "old-2", "parked"]]
    assert runs["old-2"]["total_cost_usd"] == pytest.approx(0.3)
    assert runs["old-2"]["total_tokens"] == 3
    assert runs["new"]["total_cost_usd"] == 2.0 and runs["new"]["total_tokens"] == 20
    assert runs["parked"]["total_cost_usd"] == pytest.approx(0.5)
    assert runs["parked"]["total_tokens"] == 50


# Queue #104: a park note's figure is a floor.


def _waits_on_the_owner(ctx: ExecutionContext, agent_id: str) -> NodeResult:
    """The step asks the owner from inside its work, as a Pi team's wait does
    (stage/step_waits.py), after one of its members finished a turn: the run parks with the
    step in flight, and the step's result is never handed back."""
    member = ctx.event_recorder.record(
        EventType.AGENT_STARTED, parent_id=ctx.parent_event_id, execution_id=ctx.run_id,
        status="running", data={"agent_name": "member"})
    ctx.event_recorder.record(
        EventType.LLM_CALL_COMPLETED, parent_id=member, execution_id=ctx.run_id,
        status="completed", data={"iteration": 1, "cost_usd": 0.15, "total_tokens": 150})
    ctx.event_recorder.record(
        EventType.AGENT_COMPLETED, parent_id=member, execution_id=ctx.run_id, status="completed",
        data={"agent_name": "member", "cost_usd": 0.15, "tokens": 150})
    raise RunParked(event_id=f"wait-of-{agent_id}", node="team", path="team", round=1,
                    checkpoint_id="cp-team", wait_id="ask-1")


def test_a_run_cancelled_while_it_waited_on_the_owner_shows_what_its_step_in_flight_spent():
    """As 38ba79c6: parked with the team's step in flight, then cancelled. Waiting and after
    the cancel, the list and the page show the finished step and the calls the step in
    flight recorded, not the note's finished steps alone."""
    draft = _step("draft", 0.25, 300)
    team = _step("team", 0.4, 500, depends_on=["draft"], then=_waits_on_the_owner)
    ship = _step("ship", 9.0, 9000, depends_on=["team"])

    with pytest.raises(RunParked):
        execute_graph([draft, team, ship], {}, _context(), graph_name="wf", is_workflow=True)

    assert ship.run.call_count == 0
    event = _run_event()
    assert event["status"] == "waiting"
    # The note counts the finished step only (no change to how runs park).
    assert event["data"]["parked"]["cost_usd"] == pytest.approx(0.25)
    assert event["data"]["parked"]["total_tokens"] == 300
    # draft's $0.25, the team step's own $0.40 call, its member's $0.15 turn.
    _list_and_page_agree(0.8, 950)

    assert parked.cancel_parked(RUN, "not now") is True

    event = _run_event()
    assert event["status"] == Status.CANCELLED.value
    # The cancel writes no totals (no change to how runs cancel): the reader finds them.
    assert "cost_usd" not in event["data"]
    _list_and_page_agree(0.8, 950)


def test_a_park_note_above_what_the_run_recorded_is_the_floor_cost_and_tokens_each():
    """A note can say more than the run's own calls (a fork's kept steps were paid in its
    source run): each field is the larger of the two."""
    wf = record(EventType.WORKFLOW_STARTED, execution_id=RUN, status="waiting",
                data={"name": "wf", "parked": {"cost_usd": 0.3, "total_tokens": 100},
                      "duration_seconds": 3.0})
    stage = record(EventType.STAGE_STARTED, parent_id=wf, execution_id=RUN, status="waiting",
                   data={"name": "team", "type": "agent"})
    agent = record(EventType.AGENT_STARTED, parent_id=stage, execution_id=RUN, status="running",
                   data={"agent_name": "team"})
    record(EventType.LLM_CALL_COMPLETED, parent_id=agent, execution_id=RUN, status="completed",
           data={"iteration": 1, "cost_usd": 0.1, "total_tokens": 500})

    # The note's cost, the recorded tokens.
    _list_and_page_agree(0.3, 500)


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_a_run_that_ended_keeps_its_end_totals_whatever_its_calls_add_up_to(status):
    """End totals are the run's figure, never a floor, even beside a park note: a completed,
    failed or live-cancelled run lists what it listed before #104."""
    wf = record(EventType.WORKFLOW_STARTED, execution_id=RUN, status=status,
                data={"name": "wf", "cost_usd": 0.5, "total_tokens": 500, "duration_seconds": 3.0,
                      "parked": {"cost_usd": 0.05, "total_tokens": 50}})
    stage = record(EventType.STAGE_STARTED, parent_id=wf, execution_id=RUN, status=status,
                   data={"name": "draft", "type": "agent"})
    agent = record(EventType.AGENT_STARTED, parent_id=stage, execution_id=RUN, status="running",
                   data={"agent_name": "draft"})
    record(EventType.LLM_CALL_COMPLETED, parent_id=agent, execution_id=RUN, status="completed",
           data={"iteration": 1, "cost_usd": 5.0, "total_tokens": 5000})

    _list_and_page_agree(0.5, 500)


def test_a_parked_run_with_no_events_recorded_shows_its_note():
    """Nothing to read (no call recorded, or its events trimmed): the note's figure stands."""
    record(EventType.WORKFLOW_STARTED, execution_id=RUN, status="waiting",
           data={"name": "wf", "parked": {"cost_usd": 0.2, "total_tokens": 200},
                 "duration_seconds": 1.0})

    _list_and_page_agree(0.2, 200)
