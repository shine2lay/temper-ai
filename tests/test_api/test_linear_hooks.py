"""POST /api/hooks/linear: the one public path, and what a delivery starts.

Pinned: nothing unsigned, stale or tampered gets past the handler; a retry of
a delivery starts nothing twice; one that came before the secret was set is
kept and handled once it is, if genuine; temper's own changes never start a
workflow (and when temper cannot tell, a guarded rule does not fire); and
the rest of the API stays behind the token.
"""

import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from temper_ai.api import hooks
from temper_ai.api.auth import TokenAuthMiddleware
from temper_ai.integrations.inbox import service as inbox
from temper_ai.integrations.inbox import store as inbox_store
from temper_ai.triggers import linear

SECRET = "whsec-test"  # noqa: S105
RULE = """
trigger:
  name: {name}
  source: linear
  on:
    type: Issue
    label_added: temper
  workflow: {workflow}
  ignore_self: {ignore_self}
  inputs:
    issue_id: "{{{{ data.id }}}}"
"""


def _event(**overrides):
    event = {
        "type": "Issue",
        "action": "create",
        "actor": {"id": "person-1", "name": "Ada"},
        "data": {"id": "iss-1", "identifier": "ENG-1", "labels": [{"id": "l1", "name": "temper"}]},
        "url": "https://linear.app/acme/issue/ENG-1",
        "webhookTimestamp": int(time.time() * 1000),
    }
    event.update(overrides)
    return event


def _post(client, event, *, secret=SECRET, delivery="d-1", raw=None):
    body = raw if raw is not None else json.dumps(event).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        hooks.LINEAR_PATH,
        content=body,
        headers={"Linear-Signature": signature, "Linear-Delivery": delivery,
                 "Content-Type": "application/json"},
    )


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    hooks.reset_state()
    monkeypatch.setenv(linear.SIGNING_SECRET_ENV, SECRET)
    monkeypatch.delenv("TEMPER_API_TOKEN", raising=False)
    yield
    hooks.reset_state()


@pytest.fixture
def dispatched(monkeypatch):
    seen = []
    monkeypatch.setattr(hooks, "dispatch", lambda event, record: seen.append(event))
    return seen


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(hooks.router)
    app.add_middleware(TokenAuthMiddleware)
    return TestClient(app)


class TestTheDoor:
    def test_before_the_secret_is_set_a_delivery_is_kept_not_handled(self, client, dispatched, monkeypatch):
        monkeypatch.delenv(linear.SIGNING_SECRET_ENV)
        kept = _post(client, _event(), delivery="early")
        assert kept.status_code == 202, kept.text
        assert kept.json()["held"] is True
        forged = _post(client, _event(), secret="guess", delivery="forged")
        assert forged.status_code == 202
        assert dispatched == []
        assert client.post(hooks.LINEAR_PATH, content=b"{}").status_code == 401  # no signature: refused
        kept_rows = inbox_store.listing(source="linear", status="unverified")
        assert len(kept_rows) == 2
        assert all(r.payload == {} and r.raw for r in kept_rows)  # the body is kept as it came, unread

        sweeper = inbox.Sweeper(run=inbox.process)
        assert sweeper.sweep_once()["checked"] == 0  # still no secret: they wait
        monkeypatch.setenv(linear.SIGNING_SECRET_ENV, SECRET)
        got = sweeper.sweep_once()
        assert (got["checked"], got["dropped"]) == (1, 1)
        assert [e["data"]["id"] for e in dispatched] == ["iss-1"]
        assert inbox_store.find("linear", "early").status == "done"
        assert inbox_store.find("linear", "forged") is None

    def test_a_kept_delivery_is_judged_fresh_as_of_when_it_came(self, client, dispatched, monkeypatch):
        monkeypatch.delenv(linear.SIGNING_SECRET_ENV)
        assert _post(client, _event(), delivery="early").status_code == 202
        monkeypatch.setenv(linear.SIGNING_SECRET_ENV, SECRET)
        monkeypatch.setattr(time, "time", lambda: 10**10)  # the secret was set long after
        assert inbox.Sweeper(run=inbox.process).sweep_once()["checked"] == 1
        assert len(dispatched) == 1

    def test_a_genuine_delivery_is_accepted_and_handed_on(self, client, dispatched):
        response = _post(client, _event())
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["ok"], body["delivery"]) == (True, "d-1")
        assert [e["data"]["id"] for e in dispatched] == ["iss-1"]
        row = inbox_store.get(body["event"])
        assert (row.source, row.kind, row.subject, row.status) == ("linear", "Issue.create", "ENG-1", "done")

    def test_a_delivery_that_cannot_be_saved_is_not_answered_got_it(self, client, dispatched, monkeypatch):
        def down(*args, **kwargs):
            raise RuntimeError("database gone")

        monkeypatch.setattr(inbox_store, "save", down)
        response = _post(client, _event())
        assert response.status_code == 500  # Linear sends it again later
        assert dispatched == []

    def test_wrong_secret(self, client, dispatched):
        assert _post(client, _event(), secret="guess").status_code == 401
        assert dispatched == []

    def test_a_body_changed_after_signing(self, client, dispatched):
        event = _event()
        signed = json.dumps(event).encode()
        signature = hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
        tampered = json.dumps({**event, "action": "remove"}).encode()
        response = client.post(hooks.LINEAR_PATH, content=tampered,
                               headers={"Linear-Signature": signature})
        assert response.status_code == 401
        assert dispatched == []

    def test_a_replay_older_than_a_minute(self, client, dispatched):
        stale = _event(webhookTimestamp=int((time.time() - 120) * 1000))
        assert _post(client, stale).status_code == 401
        assert dispatched == []

    def test_not_json(self, client, dispatched):
        assert _post(client, None, raw=b"not json").status_code == 400
        assert _post(client, None, raw=b"[1, 2]").status_code == 400
        assert dispatched == []

    def test_a_retry_starts_nothing_twice(self, client, dispatched):
        assert _post(client, _event(), delivery="same").status_code == 200
        again = _post(client, _event(), delivery="same")
        assert again.status_code == 200
        assert again.json()["duplicate"] is True
        assert len(dispatched) == 1


class TestTheRestOfTheApiStaysLocked:
    def test_the_hook_is_public_its_history_is_not(self, client, dispatched, monkeypatch):
        monkeypatch.setenv("TEMPER_API_TOKEN", "api-token")
        assert _post(client, _event()).status_code == 200
        assert client.get(hooks.LINEAR_PATH + "/recent").status_code == 401
        recent = client.get(hooks.LINEAR_PATH + "/recent",
                            headers={"Authorization": "Bearer api-token"})
        assert recent.status_code == 200
        assert recent.json()["deliveries"][0]["delivery"] == "d-1"


@pytest.fixture
def rules(tmp_path):
    folder = tmp_path / "triggers"
    folder.mkdir()

    def add(name, workflow="linear_reply", ignore_self="true"):
        (folder / f"{name}.yaml").write_text(
            RULE.format(name=name, workflow=workflow, ignore_self=ignore_self)
        )

    add.root = tmp_path
    return add


@pytest.fixture
def started(monkeypatch):
    from temper_ai.api import routes

    runs = []

    def fake_start_run(body):
        if body.workflow == "missing":
            raise HTTPException(status_code=400, detail="workflow config 'missing' not found")
        runs.append((body.workflow, body.inputs))
        return routes.RunResponse(execution_id=f"exec-{len(runs)}-0000", status="running")

    monkeypatch.setattr(routes, "start_run", fake_start_run)
    return runs


def _record(event):
    return {"delivery": "d", "type": event.get("type"), "action": event.get("action"),
            "outcome": "received", "runs": []}


class TestDispatch:
    def test_a_matching_rule_starts_its_workflow_with_the_inputs(self, rules, started, monkeypatch):
        rules("reply")
        monkeypatch.setattr(linear, "app_user_id", lambda: "temper-app")
        record = hooks.dispatch(_event(), _record(_event()), config_dir=rules.root)
        assert started == [("linear_reply", {"issue_id": "iss-1"})]
        assert record["runs"] == [{"trigger": "reply", "workflow": "linear_reply", "issue": "iss-1",
                                   "execution_id": "exec-1-0000"}]
        assert record["outcome"].startswith("started linear_reply exec-1-0")

    def test_no_rule_matches(self, rules, started):
        rules("reply")
        event = _event(type="Comment")
        record = hooks.dispatch(event, _record(event), config_dir=rules.root)
        assert started == []
        assert record["outcome"] == "no trigger matched"

    def test_temper_s_own_change_starts_nothing(self, rules, started, monkeypatch):
        rules("reply")
        monkeypatch.setattr(linear, "app_user_id", lambda: "temper-app")
        event = _event(actor={"id": "temper-app", "name": "Temper"})
        record = hooks.dispatch(event, _record(event), config_dir=rules.root)
        assert started == []
        assert record["outcome"] == "ignored: temper's own change"

    def test_when_temper_cannot_tell_a_guarded_rule_does_not_fire(self, rules, started, monkeypatch):
        rules("reply")
        monkeypatch.setattr(linear, "app_user_id", lambda: None)
        record = hooks.dispatch(_event(), _record(_event()), config_dir=rules.root)
        assert started == []
        assert record["outcome"].startswith("skipped:")

    def test_when_linear_does_not_answer_a_guarded_rule_does_not_fire(self, rules, started, monkeypatch):
        rules("reply")

        def down():
            raise RuntimeError("503 from api.linear.app")

        monkeypatch.setattr(linear, "app_user_id", down)
        record = hooks.dispatch(_event(), _record(_event()), config_dir=rules.root)
        assert started == []
        assert "503 from api.linear.app" in record["outcome"]

    def test_an_unguarded_rule_fires_either_way(self, rules, started, monkeypatch):
        rules("guarded")
        rules("open", workflow="audit", ignore_self="false")
        monkeypatch.setattr(linear, "app_user_id", lambda: "temper-app")
        event = _event(actor={"id": "temper-app"})
        hooks.dispatch(event, _record(event), config_dir=rules.root)
        assert started == [("audit", {"issue_id": "iss-1"})]

    def test_one_rule_failing_does_not_stop_the_others(self, rules, started, monkeypatch):
        rules("a_broken", workflow="missing")
        rules("b_fine")
        monkeypatch.setattr(linear, "app_user_id", lambda: "temper-app")
        record = hooks.dispatch(_event(), _record(_event()), config_dir=rules.root)
        assert started == [("linear_reply", {"issue_id": "iss-1"})]
        assert "failed a_broken: workflow config 'missing' not found" in record["outcome"]

    def test_an_exception_is_recorded_not_raised(self, monkeypatch):
        def explode(*args, **kwargs):
            raise OSError("disk gone")

        monkeypatch.setattr(hooks, "load_triggers", explode)
        record = hooks.dispatch(_event(), _record(_event()))
        assert record["outcome"] == "error: disk gone"


COMMENT_RULE = """
trigger:
  name: work_comment
  source: linear
  on:
    type: Comment
    action: create
    has_label: temper
    actor_type: user
  workflow: linear_work
  inputs:
    issue_id: "{{ data.issueId }}"
    identifier: "{{ data.issue.identifier }}"
    comment_id: "{{ data.id }}"
"""


def _comment(**overrides):
    event = {
        "type": "Comment",
        "action": "create",
        "actor": {"id": "person-1", "name": "Ada", "type": "user"},
        "data": {"id": "com-1", "body": "go ahead", "issueId": "iss-1", "userId": "person-1"},
        "webhookTimestamp": int(time.time() * 1000),
    }
    event.update(overrides)
    return event


@pytest.fixture
def comment_rule(tmp_path, monkeypatch):
    folder = tmp_path / "triggers"
    folder.mkdir()
    (folder / "work_comment.yaml").write_text(COMMENT_RULE)
    monkeypatch.setattr(linear, "app_user_id", lambda: "temper-app")
    asked = []

    def fake_graphql(query, variables=None, creds=None):
        asked.append(variables)
        labels = [{"id": "l1", "name": "temper"}] if variables["id"] == "iss-1" else []
        return {"issue": {"id": variables["id"], "identifier": "ROA-5", "title": "t",
                          "labels": {"nodes": labels}, "team": {"key": "ROA"}}}

    monkeypatch.setattr(linear, "graphql", fake_graphql)
    return {"root": tmp_path, "asked": asked}


class TestComments:
    """A person's comment on a `temper` issue continues the work; temper's own never does."""

    def test_a_person_s_comment_on_a_labelled_issue_starts_the_work(self, comment_rule, started):
        event = _comment()
        record = hooks.dispatch(event, _record(event), config_dir=comment_rule["root"])
        assert started == [("linear_work", {"issue_id": "iss-1", "identifier": "ROA-5", "comment_id": "com-1"})]
        assert comment_rule["asked"] == [{"id": "iss-1"}]
        assert record["outcome"].startswith("started linear_work")

    def test_a_comment_on_an_unlabelled_issue_starts_nothing(self, comment_rule, started):
        event = _comment(data={"id": "com-2", "body": "hi", "issueId": "iss-9", "userId": "person-1"})
        record = hooks.dispatch(event, _record(event), config_dir=comment_rule["root"])
        assert started == []
        assert record["outcome"] == "no trigger matched"

    def test_temper_s_own_comment_starts_nothing(self, comment_rule, started):
        # As Linear sent it on 2026-09-26: the app user is a user, so actor_type alone
        # does not tell; the author's id does.
        event = _comment(actor={"id": "temper-app", "name": "Temper- Roamee", "type": "user"},
                         data={"id": "com-3", "body": "Plan...", "issueId": "iss-1", "userId": "temper-app"})
        record = hooks.dispatch(event, _record(event), config_dir=comment_rule["root"])
        assert started == []
        assert record["outcome"] == "ignored: temper's own change"

    def test_a_comment_authored_by_temper_is_its_own_whoever_the_actor_is(self, comment_rule, started):
        event = _comment(actor={"id": "someone-else", "type": "user"},
                         data={"id": "com-4", "body": "x", "issueId": "iss-1", "userId": "temper-app"})
        hooks.dispatch(event, _record(event), config_dir=comment_rule["root"])
        assert started == []

    def test_an_integration_s_comment_starts_nothing(self, comment_rule, started):
        event = _comment(actor={"id": "gh", "name": "GitHub", "type": "integration"})
        record = hooks.dispatch(event, _record(event), config_dir=comment_rule["root"])
        assert started == []
        assert record["outcome"] == "no trigger matched"

    def test_when_linear_cannot_say_whose_issue_nothing_starts(self, comment_rule, started, monkeypatch):
        def down(*args, **kwargs):
            raise RuntimeError("503 from api.linear.app")

        monkeypatch.setattr(linear, "graphql", down)
        event = _comment()
        record = hooks.dispatch(event, _record(event), config_dir=comment_rule["root"])
        assert started == []
        assert record["outcome"].startswith("skipped: could not read the comment's issue")

    def test_no_comment_rule_no_lookup(self, rules, started, monkeypatch):
        rules("reply")  # an Issue rule only
        monkeypatch.setattr(linear, "graphql", lambda *a, **k: pytest.fail("asked Linear for nothing"))
        event = _comment()
        record = hooks.dispatch(event, _record(event), config_dir=rules.root)
        assert record["outcome"] == "no trigger matched"


class TestOneRunPerIssue:
    def test_a_second_event_while_the_run_is_going_is_skipped(self, comment_rule, started, monkeypatch):
        going = {"exec-1-0000"}
        monkeypatch.setattr(hooks, "_run_still_going", lambda eid: eid if eid in going else None)
        first = _comment()
        hooks.dispatch(first, _record(first), config_dir=comment_rule["root"])
        second = _comment(data={"id": "com-5", "body": "also this", "issueId": "iss-1", "userId": "person-1"})
        record = hooks.dispatch(second, _record(second), config_dir=comment_rule["root"])
        assert len(started) == 1
        assert record["outcome"] == "skipped work_comment: linear_work run exec-1-0 for this issue is still going"

        going.clear()  # the first run finished
        third = _comment(data={"id": "com-6", "body": "now?", "issueId": "iss-1", "userId": "person-1"})
        hooks.dispatch(third, _record(third), config_dir=comment_rule["root"])
        assert len(started) == 2

    def test_an_unknown_run_is_not_going(self, monkeypatch):
        from temper_ai.api import routes

        def not_found(execution_id):
            raise HTTPException(status_code=404, detail="not found")

        monkeypatch.setattr(routes, "get_workflow", not_found)
        assert hooks._run_still_going("nope") is None
        assert hooks._run_still_going(None) is None

    def test_a_run_the_database_says_is_running_is_going(self, monkeypatch):
        from temper_ai.api import routes

        monkeypatch.setattr(routes, "get_workflow", lambda eid: {"status": "running"})
        assert hooks._run_still_going("abc") == "abc"
        monkeypatch.setattr(routes, "get_workflow", lambda eid: {"status": "completed"})
        assert hooks._run_still_going("abc") is None

    def test_after_a_restart_the_inbox_remembers_the_issue_s_run(self, comment_rule, started, monkeypatch, client):
        going = {"exec-1-0000"}
        monkeypatch.setattr(hooks, "_run_still_going", lambda eid: eid if eid in going else None)
        monkeypatch.setattr(hooks, "load_triggers",
                            lambda config_dir=None, source=None: _load(comment_rule["root"], source))
        assert _post(client, _comment(), delivery="c-1").status_code == 200
        hooks.reset_state()  # a restart: the memory of which run works which issue is gone
        second = _comment(data={"id": "com-5", "body": "more", "issueId": "iss-1", "userId": "person-1"})
        assert _post(client, second, delivery="c-2").status_code == 200
        assert len(started) == 1
        assert inbox_store.find("linear", "c-2").outcome.startswith("skipped work_comment")


def _load(root, source):
    from temper_ai.triggers.rules import load_triggers

    return load_triggers(root, source=source)


class TestTheInbox:
    """A delivery handled from the inbox: tried again when a rule fails to start,
    never starting a run twice."""

    def test_a_rule_that_failed_to_start_is_tried_again_without_redoing_the_others(
            self, client, rules, monkeypatch):
        from temper_ai.api import routes

        runs = []
        broken = {"linear_fix"}

        def fake_start(body):
            if body.workflow in broken:
                raise HTTPException(status_code=400, detail=f"workflow config '{body.workflow}' not found")
            runs.append(body.workflow)
            return routes.RunResponse(execution_id=f"exec-{len(runs)}-0000", status="running")

        monkeypatch.setattr(routes, "_start_run", fake_start)  # start_run itself notes the run on the event
        monkeypatch.setattr(hooks, "_run_still_going", lambda eid: None)
        monkeypatch.setattr(linear, "app_user_id", lambda: "temper-app")
        monkeypatch.setattr(hooks, "load_triggers", lambda config_dir=None, source=None: _load(rules.root, source))
        rules("a_reply")
        rules("b_fix", workflow="linear_fix")

        body = _post(client, _event(), delivery="d-9").json()
        row = inbox_store.get(body["event"])
        assert row.status == "failed" and row.tries == 1
        assert "workflow config 'linear_fix' not found" in row.error
        assert row.started == [{"workflow": "linear_reply", "execution_id": "exec-1-0000"}]
        assert runs == ["linear_reply"]

        broken.clear()  # the rule is fixed
        assert inbox.process(row.id, now=row.next_try_at) == "done"
        assert runs == ["linear_reply", "linear_fix"]  # the first run was not started again
        row = inbox_store.get(row.id)
        assert [s["workflow"] for s in row.started] == ["linear_reply", "linear_fix"]
        assert row.outcome.startswith("started linear_reply exec-1-0")

    def test_the_recent_list_reads_the_inbox(self, client, dispatched):
        assert _post(client, _event(), delivery="r-1").status_code == 200
        assert _post(client, _event(action="update"), delivery="r-2").status_code == 200
        recent = client.get(hooks.LINEAR_PATH + "/recent").json()["deliveries"]
        assert [(d["delivery"], d["action"], d["status"]) for d in recent] == [
            ("r-2", "update", "done"), ("r-1", "create", "done")]
        assert recent[0]["actor"] == "Ada"
