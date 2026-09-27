"""The Slack test entry, ``temper slack fake`` and ``temper slack e2e``.

The entry lets a fake in only with its secret (or the API token) and only
while it is on; a fake goes through the event inbox to the socket's own
handler; what temper answers on a fake's reply link is kept (and an answer
for everyone posted); a fake click's form is sent to Slack to check and
kept for a fake submission; the templates carry no token; and the e2e
scores each check from what Slack shows, one failure at a time.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from temper_ai.api import hooks, slack_test
from temper_ai.api.auth import TokenAuthMiddleware, _is_public
from temper_ai.cli import slack as cli_slack
from temper_ai.integrations.inbox import service as inbox
from temper_ai.integrations.inbox import store as inbox_store
from temper_ai.integrations.slack import blocks, door, e2e, fakes
from temper_ai.integrations.slack import service as slack_service
from temper_ai.integrations.slack.client import SlackClient, SlackError
from temper_ai.integrations.slack.config import (
    ConfigWatcher,
    SlackConfigError,
    parse_config,
)
from temper_ai.integrations.slack.handlers import EXPIRES_S, SOURCE, Handler, describe

from .conftest import OTHER, OWNER, FakeSlack

SECRET = "door-secret"  # noqa: S105 - a test value
QA = "CTEMPER-QA"       # what FakeSlack makes of "#temper-qa"
WHERE = fakes.Where(channel=QA, channel_name="#temper-qa", user=OWNER, bot_user="UBOT", team="T1")
LOCAL = "http://127.0.0.1:8420"
QUESTIONS = [
    {"id": "size", "question": "How big?", "options": [{"label": "Small"}, {"label": "Large"}]},
    {"id": "name", "question": "What should it be called?"},
]


class RightAway:
    """The handler's thread pool without the threads: each job runs at once."""

    def submit(self, fn: Any, *args: Any) -> None:
        fn(*args)


class CheckingSlack(FakeSlack):
    """FakeSlack whose views.open answers a fake trigger as Slack does: it
    checks the form, then refuses the trigger (or the form, if told to)."""

    def __init__(self) -> None:
        super().__init__()
        self.refuse = "invalid_trigger_id"
        self.problems: list[str] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.server: TestClient | None = None

    def call(self, method: str, token: str | None = None, **params: Any) -> dict[str, Any]:
        self.calls.append((method, params))
        raise SlackError(method, self.refuse, {"ok": False, "error": self.refuse,
                                               "response_metadata": {"messages": list(self.problems)}})

    def open_view(self, trigger_id: str, view: dict[str, Any]) -> dict[str, Any]:
        if trigger_id.startswith("test."):  # what SlackClient.open_view does
            return door.open_view(self, trigger_id, view)
        return super().open_view(trigger_id, view)

    def respond(self, url: str, payload: dict[str, Any]) -> None:
        super().respond(url, payload)
        if self.server is not None:  # the reply link, called as temper calls it: from 127.0.0.1
            got = self.server.post(httpx.URL(url).path, json=payload)
            if got.status_code >= 400:
                raise SlackError("response_url", f"http_{got.status_code}")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv(door.SECRET_ENV, SECRET)
    for name in ("TEMPER_API_TOKEN", "TEMPER_API_TOKENS_FILE", door.SELF_URL_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(door, "FAKES", door.Fakes())
    monkeypatch.setattr(door, "_channel_ids", {})


@pytest.fixture
def slack() -> CheckingSlack:
    return CheckingSlack()


@pytest.fixture
def handler(slack, ops, slack_config):
    h = Handler(slack, ConfigWatcher(), ops, bot_user="UBOT")
    h._pool = RightAway()
    inbox.register(SOURCE, h.handle_saved, expires_after_s=EXPIRES_S)
    yield h
    inbox.unregister(SOURCE)


@pytest.fixture
def svc(slack, handler, monkeypatch):
    service = SimpleNamespace(client=slack, config=handler.config, handler=handler, bot={"team_id": "T1"})
    monkeypatch.setattr(slack_service, "_service", service)
    return service


@pytest.fixture
def app() -> FastAPI:
    api = FastAPI()
    api.include_router(slack_test.router)
    api.add_middleware(TokenAuthMiddleware)
    return api


@pytest.fixture
def client(app, svc) -> TestClient:
    return TestClient(app)


KEY = {"X-Temper-Test-Token": SECRET}


def send(client: TestClient, envelope: dict[str, Any]) -> dict[str, Any]:
    got = client.post("/api/test/slack", json=envelope, headers=KEY)
    assert got.status_code == 200, got.text
    return got.json()


def question(slack: FakeSlack, ops, questions: list | None = None) -> dict[str, Any]:
    """A question temper posted in the test channel, as Slack's API returns it."""
    from datetime import UTC, datetime

    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    ops.add_run("run-1", "gate_demo", "running", now)
    ops.alive.add("run-1")
    ops.add_gate("ev-1", "run-1", "approve_step", now, questions=questions)
    msg = blocks.gate({"id": "run-1", "workflow": "gate_demo"},
                      {"node_name": "approve_step", "event_id": "ev-1", "questions": questions or []})
    posted = slack.post(QA, msg["text"], msg["blocks"])
    return {"ts": posted["ts"], "text": msg["text"], "blocks": msg["blocks"], "user": "UBOT", "bot_id": "B1"}


class TestSettings:
    def test_on_by_default_in_temper_qa_as_the_owner(self):
        cfg = parse_config({"slack": {"agents": [{"dm": OWNER}]}})
        assert (cfg.test_door.on, cfg.test_door.channel, cfg.test_user()) == (True, "#temper-qa", OWNER)

    def test_false_turns_it_off(self):
        assert parse_config({"slack": {"test_door": False}}).test_door.on is False

    def test_its_channel_and_user_can_be_named(self):
        cfg = parse_config({"slack": {"agents": [{"dm": OWNER}],
                                      "test_door": {"channel": "C0QA00001", "user": OTHER}}})
        assert (cfg.test_door.channel, cfg.test_user()) == ("C0QA00001", OTHER)

    @pytest.mark.parametrize("value", [{"channel": "D0DM"}, {"user": "#nope"}, {"doors": 1}, {"on": "yes"}, 3])
    def test_a_bad_setting_is_an_error(self, value):
        with pytest.raises(SlackConfigError):
            parse_config({"slack": {"test_door": value}})


class TestWhoMayUseIt:
    def test_nothing_until_it_has_a_secret(self, client, monkeypatch):
        monkeypatch.delenv(door.SECRET_ENV)
        got = client.post("/api/test/slack", json=fakes.command(WHERE, "help"), headers=KEY)
        assert got.status_code == 403 and "takes nothing until it has a secret" in got.text
        assert client.get("/api/test/slack").status_code == 403

    def test_only_with_the_secret(self, client):
        assert client.get("/api/test/slack").status_code == 401
        assert client.get("/api/test/slack", headers={"X-Temper-Test-Token": "guess"}).status_code == 401
        got = client.get("/api/test/slack", headers=KEY)
        assert got.status_code == 200
        assert got.json() == {"on": True, "slack": True, "channel": "#temper-qa", "channel_id": QA,
                              "user": OWNER, "bot_user": "UBOT", "team": "T1"}

    def test_or_with_the_api_token(self, client, monkeypatch):
        monkeypatch.delenv(door.SECRET_ENV)
        monkeypatch.setenv("TEMPER_API_TOKEN", "api-token")
        assert client.get("/api/test/slack").status_code == 401
        assert client.get("/api/test/slack", headers={"Authorization": "Bearer api-token"}).status_code == 200

    def test_off_in_the_config_takes_nothing(self, client, slack_config, ops):
        slack_config(f"slack:\n  agents:\n    - dm: {OWNER}\n  test_door: false\n")
        got = client.post("/api/test/slack", json=fakes.command(WHERE, "help"), headers=KEY)
        assert got.status_code == 403 and "test entry is off" in got.text
        assert client.get("/api/test/slack", headers=KEY).json()["on"] is False
        assert inbox_store.get(1) is None

    def test_only_for_the_test_channel(self, client):
        elsewhere = fakes.Where(channel="C0RUNS001", channel_name="#runs", user=OWNER, bot_user="UBOT")
        got = client.post("/api/test/slack", json=fakes.command(elsewhere, "help"), headers=KEY)
        assert got.status_code == 400 and "fakes only go to #temper-qa" in got.text

    def test_only_slack_shaped_envelopes(self, client):
        got = client.post("/api/test/slack", json={"type": "hello", "payload": {}}, headers=KEY)
        assert got.status_code == 400

    def test_not_while_slack_is_not_running(self, client, monkeypatch):
        monkeypatch.setattr(slack_service, "_service", None)
        got = client.post("/api/test/slack", json=fakes.command(WHERE, "help"), headers=KEY)
        assert got.status_code == 503

    def test_never_on_the_public_hook_address(self):
        assert not _is_public("/api/test/slack")
        assert not _is_public("/api/test/slack/fakes/abc")
        assert not any(str(getattr(r, "path", "")).startswith("/api/test") for r in hooks.router.routes)

    def test_the_reply_link_is_open_only_to_the_server_itself(self, app, svc, monkeypatch):
        fake = door.FAKES.new("/temper help", QA)
        path = f"/api/test/slack/replies/{fake.id}"
        outside = TestClient(app)
        itself = TestClient(app, client=("127.0.0.1", 40000))
        assert outside.post(path, json={"text": "hi"}).status_code == 401
        assert outside.post(path, json={"text": "hi"}, headers=KEY).status_code == 200
        monkeypatch.setenv("TEMPER_API_TOKEN", "api-token")  # with the API token on, too
        assert itself.post(path, json={"text": "again"}).status_code == 200
        assert itself.post("/api/test/slack/replies/000000000000000000000000", json={}).status_code == 404
        assert [r["payload"]["text"] for r in door.show(fake.id)["replies"]] == ["hi", "again"]


class TestSameAsTheSocket:
    def test_a_fake_goes_through_the_inbox_to_the_handler(self, client, slack):
        got = send(client, fakes.command(WHERE, "help"))
        assert got["kind"] == "/temper help"
        row = inbox_store.get(got["event_id"])
        assert (row.source, row.delivery, row.kind, row.subject) == (
            "slack", f"test:{got['fake']}", "test /temper help", QA)
        assert (row.status, row.outcome) == ("done", "handled /temper help")
        assert row.payload["test"] == {"fake": got["fake"]}
        # Temper answered on the fake's own reply link, not Slack's.
        assert slack.responses[-1]["url"] == f"{LOCAL}/api/test/slack/replies/{got['fake']}"

    def test_a_fake_acts_as_the_owner_and_keeps_no_token(self, client):
        env = fakes.command(WHERE, "help")
        env["payload"].update(user_id=OTHER, user_name="someone", token="legacy-secret")
        row = inbox_store.get(send(client, env)["event_id"])
        assert (row.payload["payload"]["user_id"], row.payload["payload"]["user_name"]) == (OWNER, "shine")
        assert fakes.token_paths(row.payload) == [] and "legacy-secret" not in json.dumps(row.payload)

    def test_it_can_be_replayed_like_any_event(self, client, slack, monkeypatch):
        monkeypatch.setattr(inbox, "submit", lambda event_id: inbox.process(event_id))
        row = inbox_store.get(send(client, fakes.command(WHERE, "help"))["event_id"])
        assert inbox.replay(row.id)[0] is True
        assert len(slack.responses) == 2 and inbox_store.get(row.id).status == "done"

    def test_a_fake_click_approves_a_real_question(self, client, slack, ops):
        msg = question(slack, ops)
        got = send(client, fakes.click(WHERE, msg, blocks.APPROVE))
        assert got["kind"] == f"click {blocks.APPROVE}"
        assert ops.approved == [("run-1", "approve_step")]
        assert ops.answers[0]["by"] == "shine (Slack)"
        assert slack.updates[-1]["ts"] == msg["ts"] and "Approved by" in str(slack.updates[-1]["blocks"])

    def test_the_answer_form_is_checked_by_slack_kept_and_answered(self, client, slack, ops):
        msg = question(slack, ops, QUESTIONS)
        clicked = send(client, fakes.click(WHERE, msg, blocks.ANSWER))
        assert slack.calls[0][0] == "views.open" and slack.calls[0][1]["trigger_id"] == f"test.{clicked['fake']}"
        kept = client.get(f"/api/test/slack/fakes/{clicked['fake']}", headers=KEY).json()
        assert [f["verdict"] for f in kept["forms"]] == ["ok"] and ops.answers == []
        view = kept["forms"][0]["view"]
        assert view["id"].startswith("VTEST") and view["callback_id"] == blocks.ANSWER_FORM

        picks, expect = e2e.picks_for(view)
        assert (picks, expect) == ({"q0": [1], "q1c": e2e.TYPED}, ["Large", e2e.TYPED])
        sent = send(client, fakes.submit(WHERE, view, picks))
        assert sent["kind"] == f"form {blocks.ANSWER_FORM}"
        assert ops.approved == [("run-1", "approve_step")]
        assert {a["id"]: (a["selected"], a["custom"]) for a in ops.answers[0]["answers"]} == {
            "size": (["Large"], ""), "name": ([], e2e.TYPED)}

    def test_a_form_slack_refuses_is_kept_with_its_problems(self, client, slack, ops):
        slack.refuse, slack.problems = "invalid_arguments", ["[ERROR] must be less than 25 characters"]
        msg = question(slack, ops, QUESTIONS)
        clicked = send(client, fakes.click(WHERE, msg, blocks.ANSWER))
        form = door.show(clicked["fake"])["forms"][0]
        assert (form["verdict"], form["problems"]) == ("refused: invalid_arguments",
                                                       ["[ERROR] must be less than 25 characters"])
        assert "would not open the form" in json.dumps(slack.responses[-1])


class TestReplies:
    def test_what_temper_says_on_the_reply_link_is_kept(self, app, svc, slack):
        slack.server = TestClient(app, client=("127.0.0.1", 40000))
        got = door.take(fakes.command(WHERE, "help"), service=svc)
        shown = door.show(got["fake"])
        assert shown["event"]["status"] == "done"
        assert [r["payload"].get("response_type") for r in shown["replies"]] == ["ephemeral"]
        assert "posted" not in shown["replies"][0]

    def test_an_answer_for_everyone_is_posted_in_the_channel(self, svc, slack):
        fake = door.FAKES.new("/temper ask", QA)
        assert door.reply(fake.id, {"response_type": "in_channel", "text": "the answer"}, service=svc)
        assert (slack.posts[-1]["channel"], slack.posts[-1]["text"]) == (QA, "the answer")
        assert door.show(fake.id)["replies"][0]["posted"] == slack.posts[-1]["ts"]

    def test_one_the_channel_refuses_says_why(self, svc, slack):
        slack.forbidden.add(QA)
        fake = door.FAKES.new("/temper ask", QA)
        assert door.reply(fake.id, {"response_type": "in_channel", "text": "x"}, service=svc)
        assert door.show(fake.id)["replies"][0]["posted"] == "error: not_in_channel"

    def test_nothing_is_kept_for_an_unknown_or_old_fake(self, svc):
        now = [1000.0]
        kept = door.Fakes(keep_s=3600, clock=lambda: now[0])
        fake = kept.new("/temper help", QA)
        assert not door.reply("f" * 24, {"text": "x"}, service=svc, fakes=kept)
        now[0] += 3601
        assert kept.get(fake.id) is None and not door.reply(fake.id, {"text": "x"}, service=svc, fakes=kept)


class TestTheRealClient:
    """SlackClient.open_view with a fake click's trigger: to Slack to check, then kept."""

    def _client(self, answer: dict[str, Any], seen: list) -> SlackClient:
        def reply(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=answer)

        return SlackClient("xoxb-test", http=httpx.Client(transport=httpx.MockTransport(reply)))

    def test_slack_checks_the_form_and_refuses_the_trigger(self):
        seen: list = []
        fake = door.FAKES.new(f"click {blocks.ANSWER}", QA)
        client = self._client({"ok": False, "error": "invalid_trigger_id"}, seen)
        view = blocks.answer_form({"id": "run-1", "workflow": "w"}, {"node_name": "n", "event_id": "e",
                                                                     "questions": QUESTIONS}, QA, "1.2")
        opened = client.open_view(f"test.{fake.id}", view)
        assert seen[0].url.path == "/api/views.open" and f"test.{fake.id}" in seen[0].content.decode()
        assert opened["view"]["id"].startswith("VTEST")
        assert [f["verdict"] for f in door.show(fake.id)["forms"]] == ["ok"]

    def test_a_form_slack_refuses_raises_as_a_real_one_would(self):
        fake = door.FAKES.new(f"click {blocks.ANSWER}", QA)
        client = self._client({"ok": False, "error": "invalid_arguments",
                               "response_metadata": {"messages": ["[ERROR] bad title"]}}, [])
        with pytest.raises(SlackError) as caught:
            client.open_view(f"test.{fake.id}", {"type": "modal"})
        assert caught.value.error == "invalid_arguments"
        assert door.show(fake.id)["forms"][0]["problems"] == ["[ERROR] bad title"]

    def test_a_real_trigger_opens_it_as_before(self):
        seen: list = []
        client = self._client({"ok": True, "view": {"id": "V1"}}, seen)
        assert client.open_view("12345.67890.abcdef", {"type": "modal"})["view"]["id"] == "V1"
        assert len(seen) == 1 and door.FAKES.get("12345") is None


class TestTemplates:
    @pytest.mark.parametrize("kind", fakes.KINDS)
    def test_no_template_carries_a_token(self, kind):
        raw = (fakes.TEMPLATES / f"{kind}.json").read_text()
        assert fakes.token_paths(fakes.template(kind)) == []
        assert not re.search(r"xox[abpe]-|xapp-", raw) and '"token"' not in raw

    def test_the_token_check_finds_one(self):
        assert fakes.token_paths({"payload": {"token": "abc", "x": ["xoxb-123"]}}) == ["payload.token", "payload.x[0]"]

    def test_each_builder_makes_what_the_handler_reads(self):
        msg = {"ts": "1790000001.000100", "text": "q",
               "blocks": blocks.gate({"id": "run-1", "workflow": "w"},
                                     {"node_name": "n", "event_id": "e", "questions": QUESTIONS})["blocks"]}
        view = blocks.answer_form({"id": "run-1", "workflow": "w"},
                                  {"node_name": "n", "event_id": "e", "questions": QUESTIONS}, QA, msg["ts"])
        made = {
            "/temper ask": fakes.command(WHERE, "ask why"),
            "app_mention": fakes.mention(WHERE, "what does it do?", "1790000002.000100"),
            f"click {blocks.REJECT}": fakes.click(WHERE, msg, blocks.REJECT),
            f"form {blocks.ANSWER_FORM}": fakes.submit(WHERE, view, {"q0": 0}),
        }
        for said, envelope in made.items():
            assert describe(envelope) == said
            assert door.channel_of(envelope) == QA
        mention = made["app_mention"]["payload"]["event"]
        assert mention["text"] == "<@UBOT> what does it do?" and mention["user"] == OWNER
        with pytest.raises(ValueError, match="no gate_answer button"):
            fakes.click(WHERE, {"ts": "1", "blocks": []}, blocks.ANSWER)


# -- temper slack e2e ------------------------------------------------------------------------

class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class Theirs:
    """A temper behind a fake test entry, and #temper-qa as Slack's API shows
    it. ``broken`` names the one thing that goes wrong."""

    def __init__(self, broken: str = "") -> None:
        self.broken = broken
        self.messages: list[dict[str, Any]] = []
        self.fakes: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.sent: list[dict[str, Any]] = []
        self._ts = itertools.count(1)
        self._ids = itertools.count(1)
        self.door_on = True

    # -- Slack's API
    def post(self, channel: str, text: str, blocks: list | None = None, thread_ts: str | None = None,
             broadcast: bool = False) -> dict[str, Any]:
        ts = f"{1790000000 + next(self._ts)}.000100"
        msg = {"ts": ts, "text": text, "blocks": copy.deepcopy(blocks or []), "user": "UBOT", "bot_id": "B1"}
        if thread_ts:
            msg["thread_ts"] = thread_ts
        self.messages.append(msg)
        return {"ok": True, "channel": channel, "ts": ts}

    def history(self, channel: str, oldest: str | None = None, latest: str | None = None,
                inclusive: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        top = [m for m in self.messages if m.get("thread_ts") in (None, m["ts"])]
        if oldest:
            top = [m for m in top if float(m["ts"]) > float(oldest)]
        if latest:
            top = [m for m in top if float(m["ts"]) < float(latest) or (inclusive and m["ts"] == latest)]
        return copy.deepcopy(list(reversed(top))[:limit])

    def replies(self, channel: str, ts: str, limit: int = 100) -> list[dict[str, Any]]:
        return copy.deepcopy([m for m in self.messages if ts in (m["ts"], m.get("thread_ts"))][:limit])

    # -- the test entry and the run API
    def info(self) -> dict[str, Any]:
        if not self.door_on:
            return {"on": False, "slack": True, "channel": "#temper-qa"}
        return {"on": True, "slack": True, "channel": "#temper-qa", "channel_id": QA, "user": OWNER,
                "bot_user": "UBOT", "team": "T1"}

    def fake(self, fake_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.fakes[fake_id])

    def run(self, execution_id: str) -> dict[str, Any]:
        if execution_id not in self.runs:
            raise e2e.E2EError(f"GET /api/workflows/{execution_id}: 404")
        return dict(self.runs[execution_id])

    def send(self, envelope: dict[str, Any]) -> dict[str, Any]:
        self.sent.append(envelope)
        fid = f"fake{len(self.sent)}"
        self.fakes[fid] = {"fake": fid, "replies": [], "forms": [],
                           "event": {"id": len(self.sent), "status": "done", "started": []}}
        kind, p = envelope["type"], envelope["payload"]
        if kind == "slash_commands":
            self._command(fid, p["text"])
        elif kind == "events_api":
            self._mention(fid, p["event"])
        elif p["type"] == "block_actions":
            self._click(fid, p)
        else:
            self._submit(p)
        return {"fake": fid, "kind": describe(envelope), "event_id": len(self.sent)}

    # -- what temper does
    def _start(self, fid: str, workflow: str, cost: float) -> str:
        eid = f"{next(self._ids):08x}-0000-4000-8000-000000000000"
        self.runs[eid] = {"status": "running", "total_cost_usd": cost, "workflow_output": None}
        self.fakes[fid]["event"]["started"].append({"workflow": workflow, "execution_id": eid})
        return eid

    def _command(self, fid: str, text: str) -> None:
        if text.startswith("ask"):
            self._start(fid, "repo_answer", 0.05)
            if self.broken == "ask-silent":
                return
            answer = self.post(QA, "It asks two questions and waits.",
                               [blocks.section("It asks two questions and waits."), blocks.context("Read the code in x")])
            posted = "error: not_in_channel" if self.broken == "ask-not-posted" else answer["ts"]
            self.fakes[fid]["replies"].append({"payload": {"response_type": "in_channel", "text": "It asks…"},
                                               "posted": posted})
            return
        eid = self._start(fid, e2e.PROBE, 0.0)
        head = self.post(QA, f"Started {e2e.PROBE} ({blocks.short(eid)}) for <@{OWNER}>")["ts"]
        gate = blocks.gate({"id": eid, "workflow": e2e.PROBE},
                           {"node_name": "decide", "event_id": f"ev-{eid}", "questions": QUESTIONS})
        self.runs[eid].update(header=head, question=self.post(QA, gate["text"], gate["blocks"], thread_ts=head)["ts"])

    def _mention(self, fid: str, event: dict[str, Any]) -> None:
        self._start(fid, "slack_pick", 0.01)
        if self.broken == "mention":
            self.post(QA, "I couldn't find a workflow that does that.", thread_ts=event["ts"])
            return
        self._start(fid, "repo_answer", 0.04)
        self.post(QA, "It stops at a gate.", [blocks.context("Read the code in y")], thread_ts=event["ts"])

    def _click(self, fid: str, p: dict[str, Any]) -> None:
        action = p["actions"][0]
        eid = json.loads(action["value"])["run"]
        if action["action_id"] == blocks.ANSWER:
            view = blocks.answer_form({"id": eid, "workflow": e2e.PROBE},
                                      {"node_name": "decide", "event_id": f"ev-{eid}", "questions": QUESTIONS},
                                      QA, self.runs[eid]["question"])
            refused = self.broken == "form-refused"
            self.fakes[fid]["forms"].append({
                "verdict": "refused: invalid_arguments" if refused else "ok",
                "problems": ["[ERROR] bad title"] if refused else [],
                "view": {**view, "id": "VTEST1", "hash": "h1", "state": {"values": {}}}})
        elif action["action_id"] == blocks.APPROVE:
            self._decide(eid, f"Approved by <@{OWNER}>")
            self._end(eid, "completed")
        elif action["action_id"] == blocks.REJECT:
            self._decide(eid, f"Rejected by <@{OWNER}>", "rejected")
            self._end(eid, "cancelled", "" if self.broken == "reject" else f"Rejected in Slack by <@{OWNER}>")
        elif action["action_id"] == blocks.STOP:
            self.post(QA, f"Stop requested by <@{OWNER}>.", thread_ts=self.runs[eid]["header"])
            self._end(eid, "cancelled", f"Stopped in Slack by <@{OWNER}>")

    def _submit(self, p: dict[str, Any]) -> None:
        meta = json.loads(p["view"]["private_metadata"])
        answers, _ = blocks.form_answers(QUESTIONS, p["view"]["state"]["values"])
        self.runs[meta["run"]]["workflow_output"] = "{}" if self.broken == "form-lost" else json.dumps(answers)
        self._decide(meta["run"], f"Approved by <@{OWNER}>")
        self._end(meta["run"], "completed")

    def _decide(self, eid: str, line: str, verdict: str = "approved") -> None:
        msg = next(m for m in self.messages if m["ts"] == self.runs[eid]["question"])
        msg["blocks"] = blocks.decided(msg["blocks"], line, verdict)

    def _end(self, eid: str, status: str, by: str = "") -> None:
        self.runs[eid]["status"] = status
        notice = blocks.ended({"workflow": e2e.PROBE, "execution_id": eid, "status": status,
                               "duration_seconds": 4, **({"stopped_by": by} if by else {})})
        self.post(QA, notice["text"], notice["blocks"], thread_ts=self.runs[eid]["header"])


def make_tester(theirs: Theirs, said: list[str] | None = None, say: Any = None) -> e2e.Tester:
    clock = Clock()
    return e2e.Tester(theirs, theirs, say=say or (said if said is not None else []).append, sleep=clock.sleep,
                      clock=clock, now=lambda: 1790000000.0)


class TestE2E:
    def test_a_temper_that_works_passes_all_six(self):
        said: list[str] = []
        results = make_tester(Theirs(), said).run()
        assert [(r.name, r.ok) for r in results] == [(name, True) for name in e2e.CHECKS], said
        assert [round(r.cost_usd, 3) for r in results] == [0.05, 0.05, 0.0, 0.0, 0.0, 0.0]
        assert e2e.summary(results) == "6/6 passed in 0 s, $0.100"
        assert said[0] == "… ask" and said[1].startswith("PASS  ask")

    @pytest.mark.parametrize(("broken", "check", "why"), [
        ("ask-silent", "ask", "no answer for everyone after 480 s"),
        ("ask-not-posted", "ask", "could not be posted in the channel: error: not_in_channel"),
        ("mention", "mention", "the thread got something else"),
        ("form-refused", "form", "Slack refused the form: refused: invalid_arguments [ERROR] bad title"),
        ("form-lost", "form", "without the form's answers: Large, " + e2e.TYPED),
        ("reject", "reject", "does not say who rejected it"),
    ])
    def test_what_goes_wrong_fails_its_own_check_only(self, broken, check, why):
        results = make_tester(Theirs(broken)).run()
        failed = [r for r in results if not r.ok]
        assert [r.name for r in failed] == [check] and why in failed[0].detail
        assert len(results) == len(e2e.CHECKS)

    def test_a_check_that_crashes_is_a_failure_not_the_end(self, monkeypatch):
        t = make_tester(Theirs())
        monkeypatch.setattr(t, "check_ask", lambda: {}["boom"])
        results = t.run(["ask", "mention"])
        assert [(r.name, r.ok) for r in results] == [("ask", False), ("mention", True)]
        assert results[0].detail == "KeyError: 'boom'"

    def test_only_the_named_checks_and_no_unknown_ones(self):
        assert [r.name for r in make_tester(Theirs()).run(["reject", "ask"])] == ["ask", "reject"]
        with pytest.raises(e2e.E2EError, match="no check nope"):
            make_tester(Theirs()).run(["nope"])

    def test_it_will_not_start_while_the_entry_is_off(self):
        theirs = Theirs()
        theirs.door_on = False
        with pytest.raises(e2e.E2EError, match="entry is off"):
            make_tester(theirs)


class TestCommands:
    def _args(self, **kw: Any) -> SimpleNamespace:
        return SimpleNamespace(server="http://temper.test", **kw)

    def test_e2e_exit_code(self, monkeypatch, capsys):
        monkeypatch.setattr(cli_slack, "_tester", lambda server: make_tester(Theirs()))
        assert cli_slack.cmd_slack(self._args(action="e2e", only="ask,approve")) == 0
        assert "2/2 passed" in capsys.readouterr().out
        monkeypatch.setattr(cli_slack, "_tester", lambda server: make_tester(Theirs("reject")))
        assert cli_slack.cmd_slack(self._args(action="e2e", only="reject")) == 1
        assert cli_slack.cmd_slack(self._args(action="e2e", only="nope")) == 1
        assert "no check nope" in capsys.readouterr().err

    def test_fake_command_wait_prints_what_came_of_it(self, monkeypatch, capsys):
        theirs = Theirs()
        monkeypatch.setattr(cli_slack, "_tester", lambda server: make_tester(theirs, say=print))
        args = self._args(action="fake", kind="command", text=["ask", "why?"], name="/temper", wait=30.0)
        assert cli_slack.cmd_slack(args) == 0
        out = capsys.readouterr().out
        assert "fake fake1 (/temper ask) sent; inbox event 1" in out
        assert "reply, in_channel (posted in #temper-qa at 1790000001.000100)" in out
        assert "inbox event 1: done; started repo_answer 00000001-0000-4000-8000-000000000000" in out
        assert theirs.sent[0]["payload"]["text"] == "ask why?"
