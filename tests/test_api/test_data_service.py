"""Tests for api/data_service.py — event hierarchy reconstruction."""

from unittest.mock import patch

from temper_ai.api.data_service import (
    _build_agent_execution,
    _build_node_execution,
    _find_children,
    _find_event_by_type,
    _get_end_time,
    _resolve_status,
    get_agent_index,
    get_workflow_execution,
    list_workflow_executions,
)
from temper_ai.observability.event_types import EventType


def _evt(id, type, parent_id=None, execution_id="run-1", status="running", data=None, timestamp="2026-01-01T00:00:00"):
    """Helper to build event dicts."""
    return {
        "id": id,
        "type": type,
        "parent_id": parent_id,
        "execution_id": execution_id,
        "status": status,
        "data": data or {},
        "timestamp": timestamp,
    }


class TestHelpers:
    def test_find_event_by_type(self):
        events = [
            _evt("1", "agent.started"),
            _evt("2", "workflow.started"),
        ]
        assert _find_event_by_type(events, "workflow.")["id"] == "2"

    def test_find_event_by_type_not_found(self):
        assert _find_event_by_type([_evt("1", "agent.started")], "workflow.") is None

    def test_find_children(self):
        events = [
            _evt("wf", "workflow.started"),
            _evt("s1", "stage.started", parent_id="wf"),
            _evt("s2", "stage.started", parent_id="wf"),
            _evt("s1c", "stage.completed", parent_id="wf"),  # should be excluded (completed)
            _evt("a1", "agent.started", parent_id="s1"),  # wrong parent
        ]
        children = _find_children(events, "wf", "stage.")
        assert len(children) == 2
        assert {c["id"] for c in children} == {"s1", "s2"}

    def test_resolve_status(self):
        assert _resolve_status({"status": "completed"}) == "completed"
        assert _resolve_status({}) == "pending"

    def test_get_end_time(self):
        events = [
            _evt("wf", "workflow.started", timestamp="T1"),
            _evt("wfc", "workflow.completed", parent_id="wf", timestamp="T2"),
        ]
        assert _get_end_time(events, "wf", "workflow.") == "T2"

    def test_get_end_time_not_found(self):
        events = [_evt("wf", "workflow.started")]
        assert _get_end_time(events, "wf", "workflow.") is None


class TestBuildAgentExecution:
    def test_basic_agent(self):
        agent_started = _evt("a1", "agent.started", parent_id="s1", data={
            "agent_name": "planner",
            "input_data": {"task": "plan"},
            "agent_config": {"type": "llm", "model": "gpt-4o"},
        })
        agent_completed = _evt("a1c", "agent.completed", parent_id="a1", status="completed", data={
            "agent_name": "planner",
            "output": "Here is the plan",
            "tokens": 150,
            "cost_usd": 0.01,
        })
        all_events = [agent_started, agent_completed]

        result = _build_agent_execution(agent_started, all_events)

        assert result["agent_name"] == "planner"
        assert result["status"] == "completed"
        assert result["output"] == "Here is the plan"
        assert result["total_tokens"] == 150
        assert result["estimated_cost_usd"] == 0.01
        assert result["input_data"] == {"task": "plan"}
        assert result["agent_config_snapshot"]["agent"]["model"] == "gpt-4o"

    def test_agent_with_llm_and_tool_calls(self):
        agent = _evt("a1", "agent.started", parent_id="s1", data={"agent_name": "coder"})
        llm1 = _evt("l1", "llm.call.started", parent_id="a1", data={"iteration": 1})
        llm1c = _evt("l1c", "llm.call.completed", parent_id="a1", data={
            "iteration": 1, "total_tokens": 100,
        })
        tool1 = _evt("t1", "tool.call.started", parent_id="a1", data={"tool_name": "Bash"})
        all_events = [agent, llm1, llm1c, tool1]

        result = _build_agent_execution(agent, all_events)

        assert result["total_llm_calls"] == 1
        assert result["total_tool_calls"] == 1

    def test_agent_no_config_snapshot(self):
        agent = _evt("a1", "agent.started", data={})
        result = _build_agent_execution(agent, [agent])
        assert result["agent_config_snapshot"] is None


class TestBuildNodeExecution:
    def test_agent_node(self):
        stage = _evt("s1", "stage.started", parent_id="wf", data={"name": "planner"})
        agent = _evt("a1", "agent.started", parent_id="s1", data={
            "agent_name": "planner", "tokens": 100,
        })
        agent_c = _evt("a1c", "agent.completed", parent_id="a1", status="completed", data={
            "tokens": 100, "cost_usd": 0.01,
        })
        all_events = [stage, agent, agent_c]

        result = _build_node_execution(stage, all_events)

        assert result["name"] == "planner"
        assert result["type"] == "agent"
        assert result["agent"] is not None  # single agent → goes to "agent" field
        assert result["agents"] is None

    def test_stage_with_multiple_agents(self):
        stage = _evt("s1", "stage.started", parent_id="wf", data={"name": "code"})
        a1 = _evt("a1", "agent.started", parent_id="s1", data={"agent_name": "coder_a"})
        a2 = _evt("a2", "agent.started", parent_id="s1", data={"agent_name": "coder_b"})
        all_events = [stage, a1, a2]

        result = _build_node_execution(stage, all_events)

        assert result["agents"] is not None
        assert len(result["agents"]) == 2


class TestGetWorkflowExecution:
    @patch("temper_ai.api.data_service.get_events")
    def test_full_workflow(self, mock_get_events):
        mock_get_events.return_value = [
            _evt("wf", "workflow.started", execution_id="run-1", data={"name": "test_wf"}),
            _evt("s1", "stage.started", parent_id="wf", execution_id="run-1", data={"name": "plan"}),
            _evt("a1", "agent.started", parent_id="s1", execution_id="run-1", data={
                "agent_name": "planner", "tokens": 50,
            }),
            _evt("a1c", "agent.completed", parent_id="a1", execution_id="run-1", status="completed", data={
                "tokens": 50, "cost_usd": 0.005,
            }),
        ]

        result = get_workflow_execution("run-1")

        assert result is not None
        assert result["id"] == "run-1"
        assert result["workflow_name"] == "test_wf"
        assert len(result["nodes"]) == 1

    def _rewound_run(self, wf_data: dict) -> list[dict]:
        """One node that ran twice under the same name, with one llm and one
        tool call surviving in the tree. A loop rewind discarded the first
        attempt, so only the second is reachable by name.
        """
        return [
            _evt("wf", "workflow.started", execution_id="run-1", data=wf_data),
            _evt("s1", "stage.started", parent_id="wf", data={"name": "implement"}),
            _evt("a1", "agent.started", parent_id="s1", data={"agent_name": "coder"}),
            _evt("l1", "llm.call.started", parent_id="a1", data={"iteration": 1}),
            _evt("t1", "tool.call.started", parent_id="a1", data={"tool_name": "Bash"}),
        ]

    @patch("temper_ai.api.data_service.get_events")
    def test_discarded_attempts_are_added_to_the_call_counts(self, mock_get_events):
        """The node tree keeps one entry per name, so a rewound node's earlier
        attempt is invisible to it. The executor publishes that share on the
        workflow event and it has to be added, or the run under-reports.
        """
        mock_get_events.return_value = self._rewound_run({
            "name": "test_wf", "retired_llm_calls": 4, "retired_tool_calls": 6,
        })

        result = get_workflow_execution("run-1")

        assert result is not None
        assert result["total_llm_calls"] == 5  # 1 surviving + 4 discarded
        assert result["total_tool_calls"] == 7  # 1 surviving + 6 discarded

    @patch("temper_ai.api.data_service.get_events")
    def test_a_run_that_never_rewound_counts_only_the_tree(self, mock_get_events):
        """No key on the event (every run before this change, and every run
        without a loop) must be left exactly as it was."""
        mock_get_events.return_value = self._rewound_run({"name": "test_wf"})

        result = get_workflow_execution("run-1")

        assert result is not None
        assert result["total_llm_calls"] == 1
        assert result["total_tool_calls"] == 1

    @patch("temper_ai.api.data_service.get_events")
    def test_no_events_returns_none(self, mock_get_events):
        mock_get_events.return_value = []
        assert get_workflow_execution("nonexistent") is None

    @patch("temper_ai.api.data_service.get_events")
    def test_no_workflow_event_returns_none(self, mock_get_events):
        mock_get_events.return_value = [
            _evt("a1", "agent.started"),  # no workflow event
        ]
        assert get_workflow_execution("run-1") is None


class TestListWorkflowExecutions:
    @patch("temper_ai.api.data_service.get_events")
    def test_list_runs(self, mock_get_events):
        mock_get_events.return_value = [
            _evt("wf1", "workflow.started", execution_id="run-1", status="completed",
                 data={"name": "wf1", "cost_usd": 0.1}, timestamp="2026-01-01T00:00:01"),
            _evt("wf2", "workflow.started", execution_id="run-2", status="running",
                 data={"name": "wf2"}, timestamp="2026-01-01T00:00:02"),
        ]

        result = list_workflow_executions()

        assert result["total"] == 2
        assert len(result["runs"]) == 2
        # Most recent first
        assert result["runs"][0]["id"] == "run-2"

    @patch("temper_ai.api.data_service.get_events")
    def test_list_requests_newest_events(self, mock_get_events):
        """Regression: the listing MUST fetch newest-first. Ordered ascending +
        limited, it returns the oldest N once the events table grows past the
        limit — which froze the dashboard on month-old runs for ~3 weeks."""
        mock_get_events.return_value = []
        list_workflow_executions()
        assert mock_get_events.call_args.kwargs.get("newest_first") is True

    @patch("temper_ai.api.data_service.get_events")
    def test_filter_by_status(self, mock_get_events):
        mock_get_events.return_value = [
            _evt("wf1", "workflow.started", execution_id="run-1", status="completed",
                 data={"name": "wf1"}, timestamp="T1"),
            _evt("wf2", "workflow.started", execution_id="run-2", status="running",
                 data={"name": "wf2"}, timestamp="T2"),
        ]

        result = list_workflow_executions(status="completed")

        assert result["total"] == 1
        assert result["runs"][0]["status"] == "completed"

    @patch("temper_ai.api.data_service.get_events")
    def test_pagination(self, mock_get_events):
        mock_get_events.return_value = [
            _evt(f"wf{i}", "workflow.started", execution_id=f"run-{i}", status="completed",
                 data={"name": f"wf{i}"}, timestamp=f"2026-01-01T00:00:{i:02d}")
            for i in range(10)
        ]

        result = list_workflow_executions(limit=3, offset=2)

        assert result["total"] == 10
        assert len(result["runs"]) == 3

    @patch("temper_ai.api.data_service.get_events")
    def test_empty(self, mock_get_events):
        mock_get_events.return_value = []
        result = list_workflow_executions()
        assert result == {"runs": [], "total": 0}


def _listing_where(started, gates):
    """Answer the listing's two queries: the runs, then the gates still open."""
    def _dispatch(*_args, **kwargs):
        if kwargs.get("event_type") == EventType("stage.started"):
            return gates if kwargs.get("status") == "waiting" else []
        return started
    return _dispatch


class TestARunWaitingForAPerson:
    """The listing is where a person looks, so it must say who is blocked.

    A gated run reported "running" -- identical to one making progress on its
    own. Nothing in the list said a human was needed, so a parked run sat
    there until someone happened to open it. The run page had the modal; the
    page people actually land on never mentioned it.
    """

    _started = [
        _evt("wf1", "workflow.started", execution_id="parked", status="running",
             data={"name": "deploy"}),
        _evt("wf2", "workflow.started", execution_id="busy", status="running",
             data={"name": "build"}),
    ]
    _gate = [_evt("g1", "stage.started", execution_id="parked", status="waiting",
                  data={"name": "plan", "gate": True})]

    def _status(self, runs, run_id):
        return next(r["status"] for r in runs if r["id"] == run_id)

    @patch("temper_ai.api.data_service.get_events")
    def test_it_is_listed_as_waiting_not_running(self, mock_get_events):
        mock_get_events.side_effect = _listing_where(self._started, self._gate)

        runs = list_workflow_executions()["runs"]

        assert self._status(runs, "parked") == "waiting"
        assert self._status(runs, "busy") == "running"

    @patch("temper_ai.api.data_service.get_events")
    def test_the_waiting_filter_finds_it_and_running_does_not(self, mock_get_events):
        mock_get_events.side_effect = _listing_where(self._started, self._gate)
        waiting = list_workflow_executions(status="waiting")["runs"]

        mock_get_events.side_effect = _listing_where(self._started, self._gate)
        running = list_workflow_executions(status="running")["runs"]

        assert [r["id"] for r in waiting] == ["parked"]
        # Someone filtering for "running" is asking what is moving; a run
        # stopped on a question is not an answer to that.
        assert [r["id"] for r in running] == ["busy"]

    @patch("temper_ai.api.data_service.get_events")
    def test_a_finished_run_stays_finished(self, mock_get_events):
        """A leftover gate event must not park a run that already ended."""
        done = [_evt("wf1", "workflow.started", execution_id="parked",
                     status="completed", data={"name": "deploy"})]
        mock_get_events.side_effect = _listing_where(done, self._gate)

        runs = list_workflow_executions()["runs"]

        assert self._status(runs, "parked") == "completed"

    @patch("temper_ai.api.data_service.get_events")
    def test_a_waiting_stage_that_is_not_a_gate_is_ignored(self, mock_get_events):
        """Only a gate waits on a person; other waits are the machine's own."""
        not_a_gate = [_evt("s1", "stage.started", execution_id="parked",
                           status="waiting", data={"name": "plan"})]
        mock_get_events.side_effect = _listing_where(self._started, not_a_gate)

        runs = list_workflow_executions()["runs"]

        assert self._status(runs, "parked") == "running"


def _ts(n: int) -> str:
    return f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}"


def _events_query(events: list[dict]):
    """get_events over a fixed list, honouring the filters a run's loader uses."""
    def query(execution_id=None, event_type=None, parent_id=None, status=None, limit=100,
              newest_first=False, type_prefixes=(), exclude_type_prefixes=()):
        out = [e for e in events if execution_id in (None, e["execution_id"])]
        if type_prefixes:
            out = [e for e in out if e["type"].startswith(tuple(type_prefixes))]
        if exclude_type_prefixes:
            out = [e for e in out if not e["type"].startswith(tuple(exclude_type_prefixes))]
        out = sorted(out, key=lambda e: e["timestamp"], reverse=newest_first)
        return out if limit is None else out[:limit]
    return query


class TestEveryAgentOfARun:
    """The run page names an agent from the run's record. The tree keeps one
    node per name, and one cap on all events cut a long run's newest stages
    off: an agent streaming output was then known only by its id, and its
    panel had nothing to open."""

    def test_a_run_past_the_call_cap_keeps_every_stage_and_agent(self, monkeypatch):
        events = [
            _evt("wf", "workflow.started", data={"name": "big"}, timestamp=_ts(0)),
            _evt("s1", "stage.started", parent_id="wf", data={"name": "implement"}, timestamp=_ts(1)),
            _evt("a1", "agent.started", parent_id="s1", data={"agent_name": "coder"}, timestamp=_ts(2)),
            *[
                _evt(f"l{i}", "llm.call.started", parent_id="a1", data={"iteration": i}, timestamp=_ts(3 + i))
                for i in range(30)
            ],
            _evt("s2", "stage.started", parent_id="wf", data={"name": "review"}, timestamp=_ts(40)),
            _evt("a2", "agent.started", parent_id="s2", data={"agent_name": "reviewer"}, timestamp=_ts(41)),
            _evt("l99", "llm.call.started", parent_id="a2", data={"iteration": 1}, timestamp=_ts(42)),
        ]
        monkeypatch.setattr("temper_ai.api.data_service.MAX_CALL_EVENTS", 10)
        monkeypatch.setattr("temper_ai.api.data_service.get_events", _events_query(events))

        result = get_workflow_execution("run-1")

        assert result is not None
        assert [n["name"] for n in result["nodes"]] == ["implement", "review"]
        assert [a["agent_name"] for a in result["agent_index"]] == ["coder", "reviewer"]
        # The calls kept are the newest: the live agent's, then the tail of the one before.
        assert result["nodes"][1]["agent"]["total_llm_calls"] == 1
        assert result["nodes"][0]["agent"]["total_llm_calls"] == 9

    def test_every_round_of_a_looped_agent_is_in_the_index(self, monkeypatch):
        events = [
            _evt("wf", "workflow.started", data={"name": "loop"}, timestamp=_ts(0)),
            _evt("s1", "stage.started", parent_id="wf", data={"name": "review"}, timestamp=_ts(1)),
            _evt("a1", "agent.started", parent_id="s1", timestamp=_ts(2), data={
                "agent_name": "reviewer", "model": "m", "agent_config": {"type": "llm", "model": "m"},
            }),
            _evt("a1c", "agent.completed", parent_id="a1", status="completed",
                 data={"tokens": 10, "cost_usd": 0.5, "duration_seconds": 3}, timestamp=_ts(5)),
            _evt("s2", "stage.started", parent_id="wf", data={"name": "review"}, timestamp=_ts(6)),
            _evt("a2", "agent.started", parent_id="s2", data={"agent_name": "reviewer"}, timestamp=_ts(7)),
        ]
        monkeypatch.setattr("temper_ai.api.data_service.get_events", _events_query(events))

        result = get_workflow_execution("run-1")

        assert result is not None
        assert len(result["nodes"]) == 1  # the tree keeps the newest round only
        first, second = result["agent_index"]
        assert (first["id"], first["round"], first["status"]) == ("a1", 1, "completed")
        assert (first["node_name"], first["node_id"], first["model"]) == ("review", "s1", "m")
        assert first["agent_type"] == "llm"
        assert (first["total_tokens"], first["estimated_cost_usd"], first["end_time"]) == (10, 0.5, _ts(5))
        assert (second["id"], second["round"], second["status"]) == ("a2", 2, "running")

    def test_an_agent_cut_off_by_a_resume_is_interrupted_not_running(self, monkeypatch):
        events = [
            _evt("wf1", "workflow.started", status="failed", data={"name": "w"}, timestamp=_ts(0)),
            _evt("s1", "stage.started", parent_id="wf1", data={"name": "build"}, timestamp=_ts(1)),
            _evt("a1", "agent.started", parent_id="s1", data={"agent_name": "builder"}, timestamp=_ts(2)),
            _evt("wf2", "workflow.started", data={"name": "w", "resume_of": "x"}, timestamp=_ts(10)),
            _evt("s2", "stage.started", parent_id="wf2", data={"name": "build"}, timestamp=_ts(11)),
            _evt("a2", "agent.started", parent_id="s2", data={"agent_name": "builder"}, timestamp=_ts(12)),
        ]
        monkeypatch.setattr("temper_ai.api.data_service.get_events", _events_query(events))

        index = get_agent_index("run-1")

        assert index is not None
        assert [(a["id"], a["status"]) for a in index] == [("a1", "interrupted"), ("a2", "running")]

    def test_an_agent_still_running_when_the_run_ended_is_interrupted(self, monkeypatch):
        events = [
            _evt("wf", "workflow.started", status="completed", data={"name": "w"}, timestamp=_ts(0)),
            _evt("s1", "stage.started", parent_id="wf", data={"name": "build"}, timestamp=_ts(1)),
            _evt("a1", "agent.started", parent_id="s1", data={"agent_name": "builder"}, timestamp=_ts(2)),
        ]
        monkeypatch.setattr("temper_ai.api.data_service.get_events", _events_query(events))

        index = get_agent_index("run-1")

        assert index is not None
        assert index[0]["status"] == "interrupted"

    def test_the_index_reads_no_calls_and_carries_no_prompts_or_outputs(self, monkeypatch):
        calls: list[dict] = []
        events = [
            _evt("wf", "workflow.started", data={"name": "w"}, timestamp=_ts(0)),
            _evt("s1", "stage.started", parent_id="wf", data={"name": "plan"}, timestamp=_ts(1)),
            _evt("a1", "agent.started", parent_id="s1", timestamp=_ts(2), data={
                "agent_name": "planner", "input_data": {"task": "x"}, "agent_config": {"system_prompt": "p"},
            }),
            _evt("a1c", "agent.completed", parent_id="a1", status="completed", timestamp=_ts(3),
                 data={"output": "the plan", "structured_output": {"a": 1}}),
        ]
        query = _events_query(events)

        def recording_query(**kwargs):
            calls.append(kwargs)
            return query(**kwargs)
        monkeypatch.setattr("temper_ai.api.data_service.get_events", recording_query)

        index = get_agent_index("run-1")

        assert index is not None
        assert [c["exclude_type_prefixes"] for c in calls] == [("llm.", "tool.")]
        assert not {"input_data", "output", "structured_output", "agent_config_snapshot", "llm_calls"} & set(index[0])

    def test_a_run_with_no_events_has_no_index(self, monkeypatch):
        monkeypatch.setattr("temper_ai.api.data_service.get_events", _events_query([]))
        assert get_agent_index("nope") is None


class TestTheAttemptsOfARun:
    """A run cut off and started again keeps its id, so its page holds two attempts.

    The tree merges them by name, which is what a reader wants -- but then a resumed run looks
    like a run that simply took a while. These entries are how the page can say otherwise, and
    say when it was temper that picked the run back up rather than a person.
    """

    def _two_attempts(self, first_data: dict) -> list[dict]:
        return [
            _evt("wf1", "workflow.started", execution_id="run-1", status="interrupted",
                 timestamp="2026-09-28T01:20:00", data={"name": "epd_task", **first_data}),
            _evt("s1", "stage.started", parent_id="wf1", timestamp="2026-09-28T01:21:00",
                 data={"name": "plan"}),
            _evt("wf2", "workflow.started", execution_id="run-1", status="completed",
                 timestamp="2026-09-28T07:05:00",
                 data={"name": "epd_task", "resume_of": "wf1", "restored_node_names": ["plan"],
                       "cost_usd": 0.5}),
            _evt("s2", "stage.started", parent_id="wf2", timestamp="2026-09-28T07:06:00",
                 data={"name": "build"}),
        ]

    def test_a_run_that_ran_once_lists_no_attempts(self, monkeypatch):
        events = [_evt("wf", "workflow.started", execution_id="run-1", data={"name": "epd_task"})]
        monkeypatch.setattr("temper_ai.api.data_service.get_events", _events_query(events))

        assert get_workflow_execution("run-1")["attempts"] == []

    def test_both_attempts_are_listed_oldest_first(self, monkeypatch):
        monkeypatch.setattr("temper_ai.api.data_service.get_events",
                            _events_query(self._two_attempts({})))

        attempts = get_workflow_execution("run-1")["attempts"]

        assert [a["attempt"] for a in attempts] == [1, 2]
        assert [a["event_id"] for a in attempts] == ["wf1", "wf2"]
        assert [a["status"] for a in attempts] == ["interrupted", "completed"]
        assert [a["is_current"] for a in attempts] == [False, True]

    def test_the_attempt_temper_picked_up_says_so(self, monkeypatch):
        stamped = {"auto_resumed": {"at": "2026-09-28T07:04:00+00:00", "attempt": 1},
                   "error": "Interrupted: the server restarted while this run was in progress."}
        monkeypatch.setattr("temper_ai.api.data_service.get_events",
                            _events_query(self._two_attempts(stamped)))

        attempts = get_workflow_execution("run-1")["attempts"]

        assert [a["picked_up_by_temper"] for a in attempts] == [True, False]
        assert attempts[0]["picked_up_at"] == "2026-09-28T07:04:00+00:00"
        assert "restarted" in attempts[0]["error"]

    def test_a_run_a_person_resumed_names_nobody(self, monkeypatch):
        monkeypatch.setattr("temper_ai.api.data_service.get_events",
                            _events_query(self._two_attempts({})))

        assert not any(a["picked_up_by_temper"]
                       for a in get_workflow_execution("run-1")["attempts"])

    def test_the_earlier_attempts_steps_are_still_in_the_tree(self, monkeypatch):
        """What the banner promises the reader: the first attempt is still readable."""
        monkeypatch.setattr("temper_ai.api.data_service.get_events",
                            _events_query(self._two_attempts({})))

        names = [n["name"] for n in get_workflow_execution("run-1")["nodes"]]

        assert names == ["plan", "build"]
