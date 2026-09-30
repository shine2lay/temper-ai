"""Tests for temper_ai/observability/trim.py — trimming old runs' sent material.

The choosing is a plain function, so every refusal is tested on made-up
runs with no database at all. The trimming itself runs against the test
database (SQLite by default, real Postgres in the database tier).

Covers:
- decide(): the plain case, and every "never trim this" case on its own
- keep_whole globs and exact names
- rank_by_recency: the newest of each workflow
- trimmed_data(): what comes out and what stays, for both bulky event kinds
- trimmed_output(): checkpoint outputs cut to the same length events use
- parse_policy(): the config shape, and what it refuses
- run_trim() end to end: refusals honoured, outcomes kept, idempotent,
  and a run that started again between choosing and trimming is skipped
"""

from datetime import UTC, datetime, timedelta

import pytest

from temper_ai.checkpoint.models import Checkpoint
from temper_ai.database import get_session
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import get_events, record
from temper_ai.observability.trim import (
    COMPLETED,
    DEFAULT_KEEP_WHOLE,
    DEFAULT_OLDER_THAN_DAYS,
    RunFacts,
    TrimError,
    TrimPolicy,
    decide,
    load_facts,
    parse_policy,
    rank_by_recency,
    run_trim,
    trimmed_data,
    trimmed_output,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=90)


def facts(**overrides) -> RunFacts:
    """A plain old routine run: trimmable unless a test says otherwise."""
    base = {
        "execution_id": "run-1",
        "workflow_name": "tp_v5_axis_extractor",
        "status": COMPLETED,
        "asked_a_person": False,
        "started_at": OLD,
        "recency_rank": 42,
        "already_trimmed": False,
    }
    return RunFacts(**{**base, **overrides})


# ---------------------------------------------------------------------------
# decide() — the plain case
# ---------------------------------------------------------------------------

class TestPlainCase:
    def test_old_routine_completed_run_is_trimmed(self):
        verdict = decide(facts(), TrimPolicy(), NOW)
        assert verdict.trim is True
        assert verdict.reason == "old routine run"

    def test_exactly_at_the_cutoff_is_trimmed(self):
        policy = TrimPolicy(older_than_days=30)
        just_over = NOW - timedelta(days=30, seconds=1)
        assert decide(facts(started_at=just_over), policy, NOW).trim is True

    def test_naive_timestamps_are_read_as_utc(self):
        naive = (NOW - timedelta(days=90)).replace(tzinfo=None)
        assert decide(facts(started_at=naive), TrimPolicy(), NOW).trim is True


# ---------------------------------------------------------------------------
# decide() — every refusal, each on its own
# ---------------------------------------------------------------------------

class TestRefusals:
    def test_a_run_still_going_is_kept(self):
        verdict = decide(facts(status="running"), TrimPolicy(), NOW)
        assert verdict.trim is False
        assert "did not complete" in verdict.reason

    def test_a_failed_run_is_kept(self):
        verdict = decide(facts(status="failed"), TrimPolicy(), NOW)
        assert verdict.trim is False
        assert "did not complete (failed)" == verdict.reason

    @pytest.mark.parametrize("status", ["cancelled", "interrupted", "orphaned", ""])
    def test_any_other_outcome_is_kept(self, status):
        assert decide(facts(status=status), TrimPolicy(), NOW).trim is False

    def test_a_run_where_a_person_was_asked_is_kept(self):
        verdict = decide(facts(asked_a_person=True), TrimPolicy(), NOW)
        assert verdict.trim is False
        assert verdict.reason == "a person was asked something"

    def test_a_keep_whole_workflow_is_kept(self):
        verdict = decide(facts(workflow_name="epd_task"), TrimPolicy(), NOW)
        assert verdict.trim is False
        assert verdict.reason == "workflow is kept whole"

    def test_keep_whole_matches_globs_and_exact_names(self):
        policy = TrimPolicy(keep_whole=("epd_*", "nightly_report"))
        assert decide(facts(workflow_name="epd_build_grade"), policy, NOW).trim is False
        assert decide(facts(workflow_name="nightly_report"), policy, NOW).trim is False
        assert decide(facts(workflow_name="epdsomething"), policy, NOW).trim is True
        assert decide(facts(workflow_name="nightly_report_2"), policy, NOW).trim is True

    def test_every_epd_workflow_is_kept_by_default(self):
        for name in ("epd_task", "epd_build_new", "epd_build_grade", "epd_plan_grade",
                     "epd_pitch_grade", "epd_structure_grade", "epd_lens_grade", "epd_scorecard"):
            assert decide(facts(workflow_name=name), TrimPolicy(), NOW).trim is False, name

    def test_a_young_run_is_kept(self):
        verdict = decide(facts(started_at=NOW - timedelta(days=3)), TrimPolicy(), NOW)
        assert verdict.trim is False
        assert verdict.reason == "younger than 30 days"

    def test_age_is_settable(self):
        run = facts(started_at=NOW - timedelta(days=45))
        assert decide(run, TrimPolicy(older_than_days=30), NOW).trim is True
        assert decide(run, TrimPolicy(older_than_days=60), NOW).trim is False

    def test_the_newest_of_its_workflow_is_kept(self):
        policy = TrimPolicy(keep_recent_per_workflow=5)
        for rank in range(5):
            verdict = decide(facts(recency_rank=rank), policy, NOW)
            assert verdict.trim is False
            assert verdict.reason == "one of the newest 5 of its workflow"
        assert decide(facts(recency_rank=5), policy, NOW).trim is True

    def test_an_already_trimmed_run_is_left_alone(self):
        verdict = decide(facts(already_trimmed=True), TrimPolicy(), NOW)
        assert verdict.trim is False
        assert verdict.reason == "already trimmed"

    def test_the_defaults_are_thirty_days_and_epd(self):
        assert DEFAULT_OLDER_THAN_DAYS == 30
        assert DEFAULT_KEEP_WHOLE == ("epd_*",)


class TestPolicyGuards:
    def test_age_must_be_at_least_a_day(self):
        with pytest.raises(TrimError):
            TrimPolicy(older_than_days=0)

    def test_keep_recent_cannot_be_negative(self):
        with pytest.raises(TrimError):
            TrimPolicy(keep_recent_per_workflow=-1)

    def test_batch_size_must_be_positive(self):
        with pytest.raises(TrimError):
            TrimPolicy(batch_size=0)


# ---------------------------------------------------------------------------
# rank_by_recency()
# ---------------------------------------------------------------------------

class TestRankByRecency:
    def test_newest_run_of_each_workflow_ranks_zero(self):
        runs = [
            facts(execution_id="a", workflow_name="w1", started_at=NOW - timedelta(days=1)),
            facts(execution_id="b", workflow_name="w1", started_at=NOW - timedelta(days=2)),
            facts(execution_id="c", workflow_name="w2", started_at=NOW - timedelta(days=9)),
        ]
        ranked = {run.execution_id: run.recency_rank for run in rank_by_recency(runs)}
        assert ranked == {"a": 0, "b": 1, "c": 0}

    def test_a_lone_run_of_a_workflow_is_always_kept(self):
        runs = [facts(execution_id="only", workflow_name="rare", started_at=OLD)]
        [ranked] = rank_by_recency(runs)
        assert decide(ranked, TrimPolicy(), NOW).trim is False


# ---------------------------------------------------------------------------
# trimmed_data() — what goes and what stays
# ---------------------------------------------------------------------------

class TestTrimmedData:
    def test_llm_call_started_loses_only_its_transcript(self):
        data = {
            "agent_name": "planner", "model": "opus-5-5", "provider": "anthropic",
            "token": "slot-0", "temperature": 0.2, "max_tokens": 8000, "iteration": 3,
            "message_count": 12, "messages": [{"role": "user", "content": "x" * 5000}],
            "tools_available": 7, "streaming": True, "node_path": "plan",
        }
        out = trimmed_data("llm.call.started", data)
        assert "messages" not in out
        assert out["trimmed"] == ["messages"]
        for key in ("agent_name", "model", "provider", "token", "iteration",
                    "message_count", "tools_available", "streaming", "node_path"):
            assert out[key] == data[key]

    def test_agent_started_loses_its_input_and_templates(self):
        data = {
            "agent_name": "planner", "provider": "anthropic", "model": "opus-5-5",
            "node_path": "plan", "role": "planner",
            "input_data": {"task": "y" * 4000},
            "agent_config": {
                "type": "llm", "provider": "anthropic", "model": "opus-5-5",
                "temperature": 0.2, "max_tokens": 8000, "token_budget": 100,
                "max_iterations": 20, "tools": ["Bash", "Read"], "memory": None,
                "system_prompt": "z" * 9000, "task_template": "{{ task }}",
            },
        }
        out = trimmed_data("agent.started", data)
        assert "input_data" not in out
        assert "system_prompt" not in out["agent_config"]
        assert "task_template" not in out["agent_config"]
        assert out["trimmed"] == ["input_data", "agent_config.system_prompt", "agent_config.task_template"]
        assert out["agent_config"]["tools"] == ["Bash", "Read"]
        assert out["agent_config"]["model"] == "opus-5-5"
        assert out["model"] == "opus-5-5"
        assert out["role"] == "planner"

    def test_outcome_kinds_are_never_touched(self):
        for kind in ("agent.completed", "agent.failed", "llm.call.completed",
                     "llm.call.failed", "tool.call.completed", "workflow.started",
                     "stage.started"):
            assert trimmed_data(kind, {"output": "o", "messages": ["m"], "input_data": {}}) is None

    def test_an_already_trimmed_row_is_left_alone(self):
        once = trimmed_data("llm.call.started", {"messages": [1], "model": "m"})
        assert trimmed_data("llm.call.started", once) is None

    def test_a_row_without_the_bulky_keys_is_left_alone(self):
        assert trimmed_data("agent.started", {"agent_name": "a", "model": "m"}) is None

    def test_a_flat_agent_config_survives(self):
        out = trimmed_data("agent.started", {"input_data": {"a": 1}, "agent_config": "not-a-dict"})
        assert out["agent_config"] == "not-a-dict"
        assert out["trimmed"] == ["input_data"]

    def test_the_original_dict_is_not_changed(self):
        data = {"messages": [1], "model": "m"}
        trimmed_data("llm.call.started", data)
        assert data == {"messages": [1], "model": "m"}


class TestTrimmedOutput:
    def test_a_short_output_is_left_alone(self):
        assert trimmed_output("small") is None

    def test_a_long_output_is_cut_and_says_so(self):
        cut = trimmed_output("x" * 12000)
        assert cut.startswith("x" * 5000)
        assert "[trimmed: 7000 more characters]" in cut

    def test_an_empty_output_is_left_alone(self):
        assert trimmed_output(None) is None
        assert trimmed_output("") is None


# ---------------------------------------------------------------------------
# parse_policy()
# ---------------------------------------------------------------------------

class TestParsePolicy:
    def test_empty_settings_give_the_defaults(self):
        assert parse_policy(None) == TrimPolicy()
        assert parse_policy({"retention": None}) == TrimPolicy()

    def test_reads_the_shape_of_the_shipped_file(self):
        policy = parse_policy({
            "retention": {
                "older_than_days": 45,
                "keep_recent_per_workflow": 3,
                "keep_whole": ["epd_*", "nightly_report"],
                "trim_checkpoints": False,
                "batch_size": 50,
            },
        })
        assert policy.older_than_days == 45
        assert policy.keep_recent_per_workflow == 3
        assert policy.keep_whole == ("epd_*", "nightly_report")
        assert policy.trim_checkpoints is False
        assert policy.batch_size == 50

    def test_a_single_keep_whole_string_is_a_list_of_one(self):
        assert parse_policy({"retention": {"keep_whole": "epd_*"}}).keep_whole == ("epd_*",)

    @pytest.mark.parametrize("block", [
        {"older_than_days": "thirty"},
        {"older_than_days": True},
        {"keep_whole": [7]},
        {"keep_whole": ""},
        {"trim_checkpoints": "yes"},
        {"nonsense": 1},
    ])
    def test_a_setting_it_cannot_use_is_an_error(self, block):
        with pytest.raises(TrimError):
            parse_policy({"retention": block})

    def test_the_shipped_file_parses(self):
        import yaml

        from temper_ai.observability.trim import config_path

        path = config_path()
        assert path is not None, "configs/retention/retention.yaml is missing"
        policy = parse_policy(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
        assert policy.older_than_days == 30
        assert "epd_*" in policy.keep_whole


# ---------------------------------------------------------------------------
# End to end, against the test database
# ---------------------------------------------------------------------------

def make_run(execution_id, workflow, *, status=COMPLETED, age_days=90, gate=False,
             llm_calls=2, checkpoint_chars=0):
    """Write one made-up run into the database, with its bulky material."""
    when = NOW - timedelta(days=age_days)
    wf_id = record(
        EventType.WORKFLOW_STARTED, execution_id=execution_id, status=status,
        data={"name": workflow, "cost_usd": 0.5, "total_tokens": 1000,
              "workflow_output": {"text": "the answer"}},
    )
    agent_id = record(
        EventType.AGENT_STARTED, execution_id=execution_id, parent_id=wf_id, status="running",
        data={"agent_name": "planner", "model": "opus-5-5", "provider": "anthropic",
              "input_data": {"task": "y" * 4000},
              "agent_config": {"model": "opus-5-5", "tools": ["Bash"],
                               "system_prompt": "z" * 9000, "task_template": "{{ task }}"}},
    )
    for i in range(llm_calls):
        record(
            EventType.LLM_CALL_STARTED, execution_id=execution_id, parent_id=agent_id, status="running",
            data={"model": "opus-5-5", "iteration": i, "message_count": 4,
                  "messages": [{"role": "user", "content": "x" * 5000}]},
        )
        record(
            EventType.LLM_CALL_COMPLETED, execution_id=execution_id, parent_id=agent_id, status="completed",
            data={"model": "opus-5-5", "iteration": i, "total_tokens": 500, "cost_usd": 0.25,
                  "latency_ms": 1200, "response_content": "what came back", "finish_reason": "stop"},
        )
    record(
        EventType.AGENT_COMPLETED, execution_id=execution_id, parent_id=agent_id, status="completed",
        data={"agent_name": "planner", "output": "the agent's answer", "tokens": 1000,
              "cost_usd": 0.5, "llm_calls": llm_calls, "duration_seconds": 12.5},
    )
    if gate:
        record(
            EventType.STAGE_STARTED, execution_id=execution_id, parent_id=wf_id, status="approved",
            data={"name": "review", "gate": True, "gate_status": "approved",
                  "gate_response": {"answers": {"ship": "yes"}}},
        )
    if checkpoint_chars:
        with get_session() as session:
            session.add(Checkpoint(
                execution_id=execution_id, sequence=0, event_type="node_completed",
                node_name="plan", agent_name="planner", status="completed",
                output="c" * checkpoint_chars, structured_output={"verdict": "ok"},
                cost_usd=0.5, total_tokens=1000, duration_seconds=12.5, timestamp=when,
            ))
            session.commit()

    # Backdate every row of this run: recorder stamps "now".
    with get_session() as session:
        from sqlmodel import col, select

        from temper_ai.observability.models import Event
        for event in session.exec(select(Event).where(col(Event.execution_id) == execution_id)).all():
            event.timestamp = when
            session.add(event)
        session.commit()
    return execution_id


def outcome_of(execution_id):
    """What the run page needs: the figures and the answers, by event type."""
    by_type = {}
    for event in get_events(execution_id=execution_id, limit=1000):
        by_type.setdefault(event["type"], []).append(event["data"])
    return by_type


class TestRunTrimEndToEnd:
    def test_trims_the_plain_run_and_keeps_its_story(self):
        make_run("plain", "tp_v5_axis")
        with get_session() as session:
            report = run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW)

        assert report.stats.runs_trimmed == 1
        assert report.stats.events_trimmed == 3  # one agent.started, two llm.call.started
        assert report.stats.bytes_freed > 0

        data = outcome_of("plain")
        assert "messages" not in data["llm.call.started"][0]
        assert data["llm.call.started"][0]["message_count"] == 4
        assert "input_data" not in data["agent.started"][0]
        assert "system_prompt" not in data["agent.started"][0]["agent_config"]
        # Every outcome is whole.
        assert data["llm.call.completed"][0]["response_content"] == "what came back"
        assert data["llm.call.completed"][0]["cost_usd"] == 0.25
        assert data["llm.call.completed"][0]["latency_ms"] == 1200
        assert data["agent.completed"][0]["output"] == "the agent's answer"
        assert data["agent.completed"][0]["duration_seconds"] == 12.5
        assert data["workflow.started"][0]["workflow_output"] == {"text": "the answer"}
        assert data["workflow.started"][0]["cost_usd"] == 0.5

    def test_leaves_every_refused_run_whole(self):
        make_run("failed-run", "tp_v5_axis", status="failed")
        make_run("going-run", "tp_v5_axis", status="running")
        make_run("gated-run", "tp_v5_axis", gate=True)
        make_run("kept-workflow", "epd_task")
        make_run("young-run", "tp_v5_other", age_days=2)
        with get_session() as session:
            report = run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW)

        assert report.stats.runs_trimmed == 0
        for execution_id in ("failed-run", "going-run", "gated-run", "kept-workflow", "young-run"):
            data = outcome_of(execution_id)
            assert "messages" in data["llm.call.started"][0], execution_id
            assert "input_data" in data["agent.started"][0], execution_id

    def test_keeps_the_newest_few_of_every_workflow(self):
        for i in range(6):
            make_run(f"w-{i}", "tp_v5_axis", age_days=90 + i)
        with get_session() as session:
            run_trim(session, TrimPolicy(keep_recent_per_workflow=2), now=NOW)

        assert "messages" in outcome_of("w-0")["llm.call.started"][0]
        assert "messages" in outcome_of("w-1")["llm.call.started"][0]
        for i in range(2, 6):
            assert "messages" not in outcome_of(f"w-{i}")["llm.call.started"][0]

    def test_a_run_whose_later_attempt_failed_is_kept(self):
        make_run("resumed", "tp_v5_axis")
        record(EventType.WORKFLOW_STARTED, execution_id="resumed", status="failed",
               data={"name": "tp_v5_axis", "resume_of": "resumed"})
        with get_session() as session:
            report = run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW)
        assert report.stats.runs_trimmed == 0

    def test_running_twice_changes_nothing_the_second_time(self):
        make_run("twice", "tp_v5_axis")
        policy = TrimPolicy(keep_recent_per_workflow=0)
        with get_session() as session:
            first = run_trim(session, policy, now=NOW)
            second = run_trim(session, policy, now=NOW)
        assert first.stats.runs_trimmed == 1
        assert second.stats.runs_trimmed == 0
        assert second.stats.kept["already trimmed"] == 1

    def test_a_limit_leaves_the_rest_for_the_next_pass(self):
        for i in range(4):
            make_run(f"lim-{i}", f"wf-{i}")
        policy = TrimPolicy(keep_recent_per_workflow=0)
        with get_session() as session:
            first = run_trim(session, policy, now=NOW, limit=2)
            second = run_trim(session, policy, now=NOW)
        assert first.stats.runs_trimmed == 2
        assert second.stats.runs_trimmed == 2

    def test_a_dry_run_changes_nothing(self):
        make_run("dry", "tp_v5_axis")
        with get_session() as session:
            report = run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW, dry_run=True)
        assert report.stats.runs_trimmed == 1
        assert "messages" in outcome_of("dry")["llm.call.started"][0]

    def test_a_checkpoint_output_is_cut_to_what_the_events_keep(self):
        make_run("cp", "tp_v5_axis", checkpoint_chars=12000)
        with get_session() as session:
            run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW)

        with get_session() as session:
            from sqlmodel import col, select
            [row] = session.exec(
                select(Checkpoint).where(col(Checkpoint.execution_id) == "cp"),
            ).all()
            assert row.output.startswith("c" * 5000)
            assert "[trimmed: 7000 more characters]" in row.output
            # Every outcome column is untouched.
            assert row.structured_output == {"verdict": "ok"}
            assert row.cost_usd == 0.5
            assert row.total_tokens == 1000
            assert row.duration_seconds == 12.5
            assert row.status == "completed"

    def test_checkpoints_of_a_kept_run_are_untouched(self):
        make_run("cp-failed", "tp_v5_axis", status="failed", checkpoint_chars=12000)
        with get_session() as session:
            run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW)
        with get_session() as session:
            from sqlmodel import col, select
            [row] = session.exec(
                select(Checkpoint).where(col(Checkpoint.execution_id) == "cp-failed"),
            ).all()
            assert row.output == "c" * 12000

    def test_a_run_that_started_again_after_being_chosen_is_skipped(self):
        make_run("racing", "tp_v5_axis")
        from temper_ai.observability import trim as trim_module

        real_load = trim_module.load_facts

        def load_then_start_it_again(session):
            found = real_load(session)
            record(EventType.WORKFLOW_STARTED, execution_id="racing", status="running",
                   data={"name": "tp_v5_axis"})
            return found

        trim_module.load_facts = load_then_start_it_again
        try:
            with get_session() as session:
                report = run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW)
        finally:
            trim_module.load_facts = real_load

        assert report.stats.runs_trimmed == 0
        assert report.stats.kept["outcome changed since it was chosen"] == 1
        assert "messages" in outcome_of("racing")["llm.call.started"][0]

    def test_a_run_that_breaks_is_counted_not_swallowed(self):
        """A pass that fails everywhere must never read as "nothing to do"."""
        make_run("breaks", "tp_v5_axis")
        from temper_ai.observability import trim as trim_module

        real_trim_run = trim_module.trim_run

        def explode(*args, **kwargs):
            raise RuntimeError("the database said no")

        trim_module.trim_run = explode
        try:
            with get_session() as session:
                report = run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW)
        finally:
            trim_module.trim_run = real_trim_run

        assert report.stats.runs_failed == 1
        assert report.stats.runs_trimmed == 0
        assert report.as_dict()["runs_failed"] == 1
        assert "messages" in outcome_of("breaks")["llm.call.started"][0]

    def test_load_facts_reads_the_gate_and_the_workflow_name(self):
        make_run("facts-gate", "tp_v5_axis", gate=True)
        make_run("facts-plain", "other_wf")
        with get_session() as session:
            found = {run.execution_id: run for run in load_facts(session)}
        assert found["facts-gate"].asked_a_person is True
        assert found["facts-gate"].workflow_name == "tp_v5_axis"
        assert found["facts-plain"].asked_a_person is False
        assert found["facts-plain"].status == COMPLETED

    def test_the_report_says_which_database_it_touched(self):
        """Several projects here have a database called temper_ai.

        A pass that quietly went to the wrong one has to be obvious from its
        own log line, so the target is always in the report.
        """
        make_run("named", "tp_v5_axis")
        with get_session() as session:
            report = run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW)
        assert report.database
        assert report.as_dict()["database"] == report.database
        assert "/" in report.database
        # Never the password, whatever the backend.
        assert "@" not in report.database

    def test_the_report_never_carries_run_material(self):
        make_run("secret", "tp_v5_axis")
        with get_session() as session:
            report = run_trim(session, TrimPolicy(keep_recent_per_workflow=0), now=NOW)
        line = report.as_line()
        assert "x" * 100 not in line
        assert "z" * 100 not in line
        assert "y" * 100 not in line
