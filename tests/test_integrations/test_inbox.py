"""The event inbox: every event is kept before it is handled, handled once,
retried after a failure or a restart, never starts a run twice, and old rows
are cleaned up. Plus the /api/events endpoints and ``temper events``."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from temper_ai.integrations.inbox import service as inbox
from temper_ai.integrations.inbox import store

SRC = "test"
T0 = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


class Crash(BaseException):
    """The server process dying mid-handling (nothing catches it)."""


class Handler:
    def __init__(self, script=None):
        self.calls = 0
        self.script = list(script or [])

    def __call__(self, event):
        self.calls += 1
        step = self.script.pop(0) if self.script else "done it"
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step(event)
        return step


@pytest.fixture
def source():
    made = []

    def make(script=None, **kwargs):
        handler = Handler(script)
        inbox.register(SRC, handler, **kwargs)
        made.append(handler)
        return handler

    yield make
    inbox.unregister(SRC)


def _receive(delivery="d-1", **kwargs):
    row, new = inbox.receive(SRC, delivery, kind="thing.happened", subject="ENG-1", payload={"n": 1}, **kwargs)
    return row, new


def _start(workflow, execution_id):
    """What routes.start_run does for the inbox when a run starts."""
    inbox.note_run(workflow, execution_id)


class TestHandledOnce:
    def test_a_delivery_sent_twice_is_one_event_handled_once(self, source):
        handler = source()
        first, new = _receive()
        assert new and first.status == "new"
        assert inbox.process(first.id) == "done"
        again, new_again = _receive()
        assert not new_again and again.id == first.id
        assert inbox.process(again.id) == ""  # nothing to take
        assert handler.calls == 1
        row = store.get(first.id)
        assert (row.status, row.tries, row.outcome) == ("done", 1, "done it")

    def test_an_outcome_that_did_nothing_is_skipped(self, source):
        source(["no trigger matched"])
        row, _ = _receive()
        assert inbox.process(row.id) == "skipped"

    def test_an_event_without_its_source_running_waits(self):
        row, _ = inbox.receive("nobody", "d-1")
        assert inbox.process(row.id) == "new"
        assert store.due(inbox.WORKER, inbox.sources(), now=T0 + timedelta(days=1)) == []


class TestFailures:
    def test_back_off_then_give_up(self, source):
        handler = source([RuntimeError(f"down {i}") for i in range(1, 6)])
        row, _ = _receive()
        now = T0
        waits = []
        for _ in range(4):
            assert inbox.process(row.id, now=now) == "failed"
            ev = store.get(row.id)
            waits.append((ev.next_try_at - now).total_seconds())
            assert store.due(inbox.WORKER, [SRC], now=ev.next_try_at - timedelta(seconds=1)) == []
            assert store.due(inbox.WORKER, [SRC], now=ev.next_try_at) == [row.id]
            now = ev.next_try_at
        assert waits == [60, 300, 1800, 7200]
        assert inbox.process(row.id, now=now) == "gave_up"
        ev = store.get(row.id)
        assert (ev.status, ev.tries, ev.error) == ("gave_up", 5, "RuntimeError: down 5")
        assert store.due(inbox.WORKER, [SRC], now=now + timedelta(days=1)) == []
        assert handler.calls == 5

    def test_retry_says_why(self, source):
        source([inbox.Retry("rule_x failed: workflow config 'missing' not found"), "started it"])
        row, _ = _receive()
        assert inbox.process(row.id, now=T0) == "failed"
        ev = store.get(row.id)
        assert ev.outcome.startswith("rule_x failed") and ev.error.startswith("rule_x failed")
        assert inbox.process(row.id, now=ev.next_try_at) == "done"
        assert store.get(row.id).error == ""


class TestRestarts:
    def test_cut_off_mid_handling_it_is_picked_up_and_its_run_is_not_started_twice(self, source, monkeypatch):
        def starts_then_dies(event):
            _start("notion_qa", "exec-1-0000")
            raise Crash()

        handler = source([starts_then_dies])
        row, _ = _receive()
        with pytest.raises(Crash):
            inbox.process(row.id)
        assert store.get(row.id).status == "handling"

        # The server comes back: a new process, whose sweeper finds the row.
        monkeypatch.setattr(inbox, "WORKER", "new-process")
        taken = []
        got = inbox.Sweeper(run=taken.append).sweep_once(prune=False)
        assert got["retried"] == 1 and taken == [row.id]
        assert inbox.process(row.id) == "done"
        ev = store.get(row.id)
        assert ev.outcome == "already started notion_qa exec-1-0; not started again"
        assert ev.started == [{"workflow": "notion_qa", "execution_id": "exec-1-0000"}]
        assert handler.calls == 1

    def test_a_source_that_can_redo_is_handed_what_already_started(self, source, monkeypatch):
        seen = []

        def first(event):
            _start("linear_reply", "exec-1")
            raise Crash()

        def second(event):
            seen.append(inbox.already_started())
            return "started the rest"

        source([first, second], redo_safe=True)
        row, _ = _receive()
        with pytest.raises(Crash):
            inbox.process(row.id)
        monkeypatch.setattr(inbox, "WORKER", "new-process")
        assert inbox.process(row.id) == "done"
        assert seen == [[{"workflow": "linear_reply", "execution_id": "exec-1"}]]

    def test_a_row_this_process_is_handling_is_not_taken_twice(self):
        row, _ = _receive()
        assert store.claim(row.id, inbox.WORKER) is not None
        assert store.claim(row.id, inbox.WORKER) is None
        assert store.due(inbox.WORKER, [SRC], now=T0 + timedelta(days=1)) == []
        assert store.claim(row.id, "another-process") is not None  # a gone process's row is taken

    def test_one_stopped_part_way_too_often_gives_up(self, source, monkeypatch):
        source()
        row, _ = _receive()
        for n in range(store.MAX_TRIES):
            assert store.claim(row.id, f"process-{n}") is not None
        monkeypatch.setattr(inbox, "WORKER", "the-last-one")
        assert inbox.process(row.id) == "gave_up"
        assert "stopped part-way" in store.get(row.id).error

    def test_a_new_row_nobody_took_is_picked_up(self, source):
        row, _ = _receive()
        assert store.due(inbox.WORKER, [SRC], now=datetime.now(UTC)) == []
        assert store.due(inbox.WORKER, [SRC], now=datetime.now(UTC) + timedelta(minutes=3)) == [row.id]


class TestReplay:
    def test_replays_a_finished_event(self, source, monkeypatch):
        handler = source(["did it", "did it again"])
        monkeypatch.setattr(inbox, "submit", lambda event_id: inbox.process(event_id))
        row, _ = _receive()
        inbox.process(row.id)
        ok, why = inbox.replay(row.id)
        assert ok and why == "queued to be handled again"
        ev = store.get(row.id)
        assert (ev.status, ev.outcome, ev.tries) == ("done", "did it again", 1)
        assert handler.calls == 2

    def test_refuses_what_would_start_a_run_twice_and_says_why(self, source):
        def starts(event):
            _start("notion_qa", "abcdef12-3456")
            return "started notion_qa abcdef12"

        source([starts])
        row, _ = _receive()
        inbox.process(row.id)
        ok, why = inbox.replay(row.id)
        assert not ok and why.startswith("it already started notion_qa abcdef12")
        assert inbox.replay(999)[0] is False

    def test_refuses_one_being_handled_or_waiting_for_its_key(self, source):
        row, _ = _receive()
        assert inbox.replay(row.id) == (False, "it is new right now")
        held, _ = store.save(SRC, "h-1", status=store.HELD, raw="{}")
        assert "signing key" in inbox.replay(held.id)[1]


class TestHeld:
    def test_limits(self, monkeypatch):
        assert inbox.hold(SRC, "h-1", b"x" * (inbox.MAX_BODY + 1), "sig")[0] == 413
        monkeypatch.setattr(inbox, "MAX_HELD", 1)
        assert inbox.hold(SRC, "h-1", b"{}", "sig") == (202, "kept until the signing key is set")
        assert inbox.hold(SRC, "h-1", b"{}", "sig")[0] == 503  # full
        monkeypatch.setattr(inbox, "MAX_HELD", 5)
        assert inbox.hold(SRC, "h-1", b"{}", "sig") == (202, "already kept")
        assert inbox.hold(SRC, "h-2", b"\xff", "sig")[0] == 400

    def test_checked_once_the_key_is_there(self, source):
        handler = source()
        verdicts = {"good": ({"ok": 1}, "thing.happened", "ENG-2"), "bad": inbox.Bad("signature does not match")}
        waiting = {"yes": True}

        def check(ev):
            if waiting["yes"]:
                return None
            verdict = verdicts[ev.delivery]
            if isinstance(verdict, Exception):
                raise verdict
            return verdict

        inbox.register_checker(SRC, check)
        try:
            for name in ("good", "bad"):
                inbox.hold(SRC, name, b"{}", "sig")
            sweeper = inbox.Sweeper(run=inbox.process)
            assert sweeper.sweep_once(prune=False)["checked"] == 0
            waiting["yes"] = False
            assert sweeper.sweep_once(prune=False) == {"checked": 1, "dropped": 1, "retried": 0, "pruned": 0}
            good = store.find(SRC, "good")
            assert (good.status, good.payload, good.subject, good.raw) == ("done", {"ok": 1}, "ENG-2", "")
            assert store.find(SRC, "bad") is None and handler.calls == 1
        finally:
            inbox._checkers.pop(SRC, None)


class TestCleanUp:
    def test_deletes_the_right_rows(self):
        now = datetime.now(UTC)
        ages = {"done": 15, "skipped": 15, "expired": 15, "failed": 31, "gave_up": 31, store.HELD: 31}
        for status, days in ages.items():
            store.save(SRC, f"old-{status}", status=status, received_at=now - timedelta(days=days))
            store.save(SRC, f"kept-{status}", status=status, received_at=now - timedelta(days=days - 2))
        store.save(SRC, "old-new", status="new", received_at=now - timedelta(days=60))
        assert store.prune(now) == len(ages)
        left = {e.delivery for e in store.listing(source=SRC, limit=100)}
        assert left == {f"kept-{s}" for s in ages} | {"old-new"}


class TestNoteRun:
    def test_outside_an_event_it_does_nothing(self):
        inbox.note_run("wf", "exec-1")  # e.g. a run started from the CLI

    def test_start_run_notes_the_run_on_the_event(self, source, monkeypatch):
        from temper_ai.api import routes

        monkeypatch.setattr(routes, "_start_run",
                            lambda body: routes.RunResponse(execution_id="exec-9-0000", status="running"))

        def starts(event):
            routes.start_run(routes.RunRequest(workflow="demo", inputs={}))
            return "started demo"

        source([starts])
        row, _ = _receive()
        inbox.process(row.id)
        assert store.get(row.id).started == [{"workflow": "demo", "execution_id": "exec-9-0000"}]


def _app():
    from temper_ai.api.events import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestApiAndCommand:
    def test_list_show_and_replay(self, source, monkeypatch):
        source(["no trigger matched", "started nothing new"])
        monkeypatch.setattr(inbox, "submit", lambda event_id: inbox.process(event_id))
        row, _ = _receive()
        inbox.process(row.id)
        client = _app()

        listed = client.get("/api/events", params={"source": SRC, "status": "skipped", "since": "1h"}).json()
        assert [e["id"] for e in listed["events"]] == [row.id]
        assert listed["events"][0]["outcome"] == "no trigger matched"
        assert client.get("/api/events", params={"status": "weird"}).status_code == 400
        assert client.get("/api/events", params={"since": "soon"}).status_code == 400
        assert client.get("/api/events", params={"since": "2h", "source": "linear"}).json()["events"] == []

        shown = client.get(f"/api/events/{row.id}").json()
        assert shown["payload"] == {"n": 1} and shown["kind"] == "thing.happened"
        assert client.get("/api/events/999").status_code == 404

        replayed = client.post(f"/api/events/{row.id}/replay")
        assert replayed.json() == {"replayed": True, "message": "queued to be handled again"}
        assert store.get(row.id).outcome == "started nothing new"
        assert client.post("/api/events/999/replay").status_code == 404

    def test_the_command(self, source, monkeypatch, capsys):
        from temper_ai.cli import events as cli

        def starts(event):
            _start("notion_qa", "abcdef12-3456")
            return "started notion_qa abcdef12"

        source([starts])
        row, _ = _receive()
        inbox.process(row.id)
        client = _app()

        def request(method, url, headers=None, timeout=None, params=None):
            return client.request(method, url.replace("http://temper.test", ""), params=params)

        monkeypatch.setattr(cli.httpx, "request", request)
        parser = argparse.ArgumentParser()
        cli.add_parser(parser.add_subparsers(dest="command"))

        def run(*argv):
            code = cli.cmd_events(parser.parse_args(["events", *argv, "--server", "http://temper.test"]))
            return code, capsys.readouterr()

        code, out = run("list")
        assert code == 0 and "thing.happened" in out.out and "started notion_qa abcdef12" in out.out
        assert "sweeper is not running" in out.out
        code, out = run("show", str(row.id))
        assert code == 0 and "runs started:  notion_qa abcdef12" in out.out and '"n": 1' in out.out
        code, out = run("replay", str(row.id))
        assert code == 1 and "Not replayed: it already started notion_qa abcdef12" in out.out
        code, out = run("show", "999")
        assert code == 1 and "404" in out.err
        code, out = run("list", "--status", "gave_up")
        assert code == 0 and "No events match." in out.out


def test_parse_since():
    assert store.parse_since("30m", now=T0) == T0 - timedelta(minutes=30)
    assert store.parse_since("1w", now=T0) == T0 - timedelta(weeks=1)
    assert store.parse_since("2026-09-27") == datetime(2026, 9, 27, tzinfo=UTC)
    assert store.parse_since("") is None
    with pytest.raises(ValueError):
        store.parse_since("yesterday")
