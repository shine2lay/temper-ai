"""Script agents' saved logs: rows stored, read back a page at a time, kept out of everything else.

In the database tier (tests/pgtier.py): with TEMPER_TEST_DATABASE_URL set these run against a
throwaway Postgres, never a live database.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from temper_ai.observability import record
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import copy_events_for_fork, get_events
from temper_ai.observability.script_logs import (
    LIVE_ROW_MAX_BYTES,
    SCRIPT_LOG,
    live_row,
    read_script_log,
    save_script_log_row,
    save_script_log_rows,
    script_log_event_id,
)

RUN = "run-logs"


def _row(attempt: str, seq: int, text: str, **extra) -> dict:
    size = len(text.encode())
    return {
        "attempt_id": attempt, "seq": seq,
        "entries": [{"stream": "stdout", "t": "2026-10-02T12:00:00.000+00:00", "text": text}],
        "bytes": size, "saved_bytes": size * seq, "dropped_bytes": 0, "lost_bytes": 0,
        "limit": 10_000_000, "truncated": False, **extra,
    }


def _agent(run: str = RUN, name: str = "talker", parent: str | None = None) -> str:
    return record(EventType.AGENT_STARTED, parent_id=parent, execution_id=run, status="running",
                  data={"agent_name": name})


def _texts(page: dict) -> list[str]:
    return [e["text"] for row in page["rows"] for e in row["entries"]]


def _fill(attempt: str, n: int, size: int = 10) -> None:
    save_script_log_rows(RUN, attempt, [(i, _row(attempt, i, f"{i:0{size}d}")) for i in range(1, n + 1)])


class TestPaging:
    def test_with_no_cursor_the_page_is_the_newest_rows(self):
        attempt = _agent()
        _fill(attempt, 10)
        page = read_script_log(RUN, attempt, max_bytes=30)
        assert [r["seq"] for r in page["rows"]] == [8, 9, 10]
        assert (page["first_seq"], page["last_seq"], page["newest_seq"]) == (8, 10, 10)
        assert page["has_more_before"] is True and page["has_more_after"] is False
        assert page["page_bytes"] == 30

    def test_paging_back_and_catching_up_visit_every_row_once(self):
        attempt = _agent()
        _fill(attempt, 10)
        back = read_script_log(RUN, attempt, before_seq=8, max_bytes=30)
        assert [r["seq"] for r in back["rows"]] == [5, 6, 7]
        assert back["has_more_before"] is True and back["has_more_after"] is True
        seen: list[int] = []
        after = 0
        while True:
            page = read_script_log(RUN, attempt, after_seq=after, max_bytes=25)
            seen += [r["seq"] for r in page["rows"]]
            if not page["has_more_after"]:
                break
            after = page["last_seq"]
        assert seen == list(range(1, 11))

    def test_a_page_holds_at_least_one_row_however_small_the_budget(self):
        attempt = _agent()
        save_script_log_row(RUN, attempt, 1, _row(attempt, 1, "x" * 5000))
        page = read_script_log(RUN, attempt, max_bytes=1)
        assert [r["seq"] for r in page["rows"]] == [1]

    def test_catching_up_from_the_newest_row_finds_nothing_more(self):
        attempt = _agent()
        _fill(attempt, 3)
        page = read_script_log(RUN, attempt, after_seq=3)
        assert page["rows"] == [] and page["has_more_after"] is False and page["newest_seq"] == 3

    def test_an_attempt_with_no_rows_yet_reads_as_empty(self):
        attempt = _agent()
        page = read_script_log(RUN, attempt)
        assert page["rows"] == [] and page["newest_seq"] == 0
        assert page["has_more_before"] is False and page["has_more_after"] is False

    def test_many_small_rows_come_in_order(self):
        attempt = _agent()
        _fill(attempt, 600, size=4)
        page = read_script_log(RUN, attempt, after_seq=0, max_bytes=4 * 1024 * 1024)
        assert [r["seq"] for r in page["rows"]] == list(range(1, 601))


class TestAttempts:
    def test_two_attempts_of_one_agent_name_keep_their_own_logs(self):
        first, retry = _agent(name="talker"), _agent(name="talker")
        save_script_log_row(RUN, first, 1, _row(first, 1, "first try\n"))
        save_script_log_row(RUN, retry, 1, _row(retry, 1, "second try\n"))
        assert _texts(read_script_log(RUN, first)) == ["first try\n"]
        assert _texts(read_script_log(RUN, retry)) == ["second try\n"]

    def test_a_log_is_read_only_through_its_own_run(self):
        attempt = _agent()
        save_script_log_row(RUN, attempt, 1, _row(attempt, 1, "mine\n"))
        assert read_script_log("another-run", attempt) is None

    def test_only_an_agent_has_a_log(self):
        stage = record(EventType.STAGE_STARTED, execution_id=RUN, data={"name": "s"})
        assert read_script_log(RUN, stage) is None
        assert read_script_log(RUN, "no-such-event") is None


class TestSaving:
    def test_saving_a_row_twice_keeps_one(self):
        attempt = _agent()
        save_script_log_row(RUN, attempt, 1, _row(attempt, 1, "once\n"))
        save_script_log_row(RUN, attempt, 1, _row(attempt, 1, "once\n"))
        save_script_log_rows(RUN, attempt, [(1, _row(attempt, 1, "once\n")), (2, _row(attempt, 2, "two\n"))])
        assert _texts(read_script_log(RUN, attempt)) == ["once\n", "two\n"]

    def test_row_ids_sort_in_order(self):
        assert script_log_event_id("a", 9) < script_log_event_id("a", 10) < script_log_event_id("a", 100)

    def test_rows_are_events_of_their_attempt(self):
        attempt = _agent()
        save_script_log_row(RUN, attempt, 1, _row(attempt, 1, "x\n"))
        [event] = get_events(execution_id=RUN, event_type=SCRIPT_LOG)
        assert (event["id"], event["parent_id"]) == (script_log_event_id(attempt, 1), attempt)


class TestLiveRows:
    def test_a_small_row_goes_out_whole(self):
        row = _row("a", 1, "hello\n")
        assert live_row(row) is row

    def test_a_large_row_goes_out_without_its_text(self):
        row = _row("a", 1, "x" * (LIVE_ROW_MAX_BYTES + 1))
        slim = live_row(row)
        assert slim["stub"] is True and "entries" not in slim
        assert (slim["seq"], slim["bytes"]) == (1, LIVE_ROW_MAX_BYTES + 1)
        assert "entries" in row, "the saved row is untouched"


class TestRecorder:
    def test_rows_are_saved_then_sent_with_their_ids(self):
        attempt = _agent()
        notifier = MagicMock()
        rec = EventRecorder(RUN, notifier=notifier)
        ids = rec.record_script_log_rows(attempt, [(1, _row(attempt, 1, "a\n")), (2, _row(attempt, 2, "b\n"))],
                                         execution_id=RUN)
        assert ids == [script_log_event_id(attempt, 1), script_log_event_id(attempt, 2)]
        assert _texts(read_script_log(RUN, attempt)) == ["a\n", "b\n"]
        sent = [c.args for c in notifier.notify_script_log.call_args_list]
        assert [(run, row["seq"], row["id"], row["attempt_id"]) for run, row in sent] == [
            (RUN, 1, ids[0], attempt), (RUN, 2, ids[1], attempt)]
        notifier.notify_event.assert_not_called()

    def test_rows_that_were_not_saved_are_not_sent(self, monkeypatch):
        import temper_ai.observability.script_logs as script_logs

        def broken(*a, **kw):
            raise RuntimeError("database down")

        monkeypatch.setattr(script_logs, "save_script_log_rows", broken)
        notifier = MagicMock()
        with pytest.raises(RuntimeError):
            EventRecorder(RUN, notifier=notifier).record_script_log_rows("a", [(1, _row("a", 1, "x"))])
        notifier.notify_script_log.assert_not_called()

    def test_a_viewer_that_fails_does_not_unsave_the_row(self):
        attempt = _agent()
        notifier = MagicMock()
        notifier.notify_script_log.side_effect = RuntimeError("socket gone")
        rec = EventRecorder(RUN, notifier=notifier)
        assert rec.record_script_log(attempt, 1, _row(attempt, 1, "kept\n"), execution_id=RUN)
        assert _texts(read_script_log(RUN, attempt)) == ["kept\n"]


class TestLeftOutOfTheRun:
    """Rows are many per agent: a run's structure, its activity and its forks leave them out."""

    def _run_with_a_log(self) -> tuple[str, str]:
        wf = record(EventType.WORKFLOW_STARTED, execution_id=RUN, status="running", data={"name": "w"})
        stage = record(EventType.STAGE_STARTED, parent_id=wf, execution_id=RUN, status="running",
                       data={"name": "talk"})
        attempt = _agent(parent=stage)
        _fill(attempt, 5)
        return wf, attempt

    def test_the_run_detail_and_agent_index_have_no_log_rows(self):
        from temper_ai.api.data_service import _load_run_events, get_agent_index

        _, attempt = self._run_with_a_log()
        assert SCRIPT_LOG not in {e["type"] for e in _load_run_events(RUN)}
        assert [a["id"] for a in get_agent_index(RUN)] == [attempt]

    def test_the_completion_s_log_figures_reach_the_run_detail(self):
        from temper_ai.api.data_service import get_workflow_execution

        _, attempt = self._run_with_a_log()
        summary = {"rows": 5, "saved_bytes": 50, "dropped_bytes": 0, "lost_bytes": 0,
                   "limit": 10_000_000, "truncated": False, "complete": True}
        record(EventType.AGENT_COMPLETED, parent_id=attempt, execution_id=RUN, status="completed",
               data={"agent_name": "talker", "output": "x", "log": summary})
        detail = get_workflow_execution(RUN)
        agents = [n["agent"] for n in detail["nodes"] if n.get("agent")]
        assert [a["log"] for a in agents if a["id"] == attempt] == [summary]

    def test_a_fork_copies_the_agent_but_no_log_rows(self):
        self._run_with_a_log()
        assert copy_events_for_fork(RUN, "fork-run", {"talk"})
        copied = get_events(execution_id="fork-run", limit=None)
        assert EventType.AGENT_STARTED.value in {e["type"] for e in copied}
        assert SCRIPT_LOG not in {e["type"] for e in copied}

    def test_activity_is_the_run_s_steps_not_its_output(self):
        from datetime import datetime

        from temper_ai.runner.quiet import activity_of
        from temper_ai.shared.clock import as_utc
        from temper_ai.triggers.scheduler import _last_activity

        self._run_with_a_log()
        events = get_events(execution_id=RUN, limit=None)
        latest_step = max(as_utc(datetime.fromisoformat(e["timestamp"])) for e in events
                          if e["type"] != SCRIPT_LOG)
        latest_row = max(as_utc(datetime.fromisoformat(e["timestamp"])) for e in events
                         if e["type"] == SCRIPT_LOG)
        assert latest_row > latest_step
        assert as_utc(_last_activity(RUN)) == latest_step
        activity = activity_of([RUN])[RUN]
        assert as_utc(activity.at) == latest_step and "script.log" not in activity.step
