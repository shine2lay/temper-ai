"""Team alerts (notify kind ``team_wait``, docs/notify.md#team-alerts).

A free-flowing team asks its owner on the Team page. Each asked wait is also a waiting gate,
which the ordinary ``question`` notice would send with the member's own words and Approve /
Reject buttons. For a free-flowing team the owner gets one fixed sentence and the Team-page
link instead, once per wait, closed when the wait is. Only waits the page asks get one.

Real code: the Pi ledger's waits (``Ledger.open_wait``), FLOW's ask (``ask_owner_for_wait``
with ``hold=False``, as the team's driver asks), the event recorder, ``TemperOps``' gate reads
on the test database, the notifier and the Slack sender. Fakes: the Slack client and the run
list. A fixed clock; no model, run or worker.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

from temper_ai.cli.pi import TEAM_ALERTS_FAILED, team_alerts_command
from temper_ai.database import get_database
from temper_ai.integrations.notify import store, team_waits
from temper_ai.integrations.notify.config import (
    ConfigWatcher,
    NotifyConfig,
    load_config,
)
from temper_ai.integrations.notify.loop import Notifier
from temper_ai.integrations.notify.models import NotifyCopy
from temper_ai.integrations.slack.blocks import APPROVE, REJECT
from temper_ai.integrations.slack.ops import TemperOps
from temper_ai.integrations.slack.sender import SlackSender
from temper_ai.observability.event_recorder import EventRecorder
from temper_ai.observability.event_types import EventType
from temper_ai.pi_agent.accounts import (
    limit_after_check,
    limit_details,
    limit_restart_ready,
    limit_resume,
)
from temper_ai.pi_agent.ledger import Ledger, _now, trials, waits
from temper_ai.pi_agent.owner_waits import ask_owner_for_wait
from temper_ai.pi_agent.settings_wait import SETTINGS, team_subject
from temper_ai.shared.types import ExecutionContext
from tests.test_integrations.conftest import NOTIFY_YAML, OWNER, FakeSlack

T0 = datetime(2026, 9, 28, 17, 0, tzinfo=UTC)          # 10:00 in Los Angeles
NIGHT = datetime(2026, 9, 29, 6, 0, tzinfo=UTC)        # 23:00 there: inside 22:00-07:00
MORNING = datetime(2026, 9, 29, 14, 0, tzinfo=UTC)     # 07:00 there: the quiet window's end
HOST = "trial.team"
DM = f"D{OWNER}"
TEAM_PAGE = "https://temper.test/app/team/runs/"
#: Stands for everything a member writes: questions, details, headers, names, the goal.
WORDS = "SENTINEL-member-words-7c1e"
READY_WEEKLY = {"kind": "weekly", "resume_verified": True, "resumes_at": "2026-01-01T00:00:00+00:00"}
WEEK_AHEAD = {"kind": "weekly", "resume_verified": True, "resumes_at": "2999-01-01T00:00:00+00:00"}
FIVE_HOUR = {"kind": "five_hour", "resume_verified": True, "resumes_at": "2026-01-01T00:00:00+00:00"}
ALERT = "The team is waiting for you: {}. Answer on the Team page."
ROUTED = NOTIFY_YAML.replace("  defaults:\n", "  defaults:\n    team_wait: slack\n")


class Ops(TemperOps):
    """``TemperOps``' gate reads on the test database; the run list is the test's."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}

    def add(self, workflow: str, status: str = "running") -> str:
        eid = str(uuid.uuid4())
        self.runs[eid] = {"id": eid, "workflow_name": workflow, "status": status}
        return eid

    def recent(self, status: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
        return list(self.runs.values())

    def summary(self, execution_id: str) -> dict[str, Any]:
        run = self.runs.get(execution_id) or {}
        return {"execution_id": execution_id, "workflow": run.get("workflow_name", ""),
                "status": run.get("status"), "nodes": []}


class Team:
    """A team run on the test database, asking its owner the way FLOW asks."""

    def __init__(self, ops: Ops, *, rounds: bool = False) -> None:
        self.ops = ops
        self.ledger = Ledger(get_database().engine)
        tid = uuid.uuid4().hex[:12]
        self.eid = ops.add(f"team-trial-{tid}")
        record = {"kind": "flow", "goal": WORDS, "leader": "lead", "members": [{"name": WORDS}],
                  "pause_every_usd": 100}
        if rounds:
            record = {**record, "pause_after_rounds": 2}
        with self.ledger.engine.begin() as conn:
            conn.execute(trials.insert().values(
                trial_id=tid, request_id=f"req-{tid}", body_sha256="0" * 64,
                workflow=f"team-trial-{tid}", member_configs=[], goal=WORDS, project=None,
                trial=record, execution_id=self.eid, created_at=_now(), created_by="test",
                created_source="test", started_at=_now(), start_status="running"))

    def wait(self, kind: str, subject: dict[str, Any] | None = None, *, ask: bool = True) -> str:
        row = self.ledger.open_wait(self.eid, HOST, kind,
                                    {"member": WORDS, "question": WORDS, "header": WORDS, **(subject or {})},
                                    attempt_id="attempt-1")
        if ask:
            self.ask(str(row["wait_id"]))
        return str(row["wait_id"])

    def ask(self, wait_id: str) -> None:
        """Ask the owner an open wait, as the team's driver does (its gate event appears)."""
        context = ExecutionContext(run_id=self.eid, workflow_name=self.ops.runs[self.eid]["workflow_name"],
                                   node_path=HOST, agent_name="", event_recorder=EventRecorder(self.eid),
                                   tool_executor=MagicMock(), gate_registry={}, step_path=HOST)
        assert ask_owner_for_wait(context, self.ledger, wait_id, question=WORDS, header=WORDS,
                                  detail=WORDS, hold=False) is None

    def answer(self, wait_id: str) -> None:
        assert self.ledger.decide_wait(wait_id, {"answer": WORDS}, "attempt-1")

    def end(self, status: str = "completed") -> None:
        self.ops.runs[self.eid]["status"] = status


def recheck(team: Team, wait_id: str, used_7d: int) -> None:
    """A fresh usage check of the held limit wait, as the team's driver records it (same wait)."""
    (row,) = [w for w in team.ledger.open_waits(team.eid, HOST) if w["wait_id"] == wait_id]
    reading = {"status": "ok", "windows": [{"key": "5h", "used_percent": 10},
                                         {"key": "7d", "used_percent": used_7d}]}
    assert team.ledger.update_limit_wait(wait_id, row["subject"],
                                         limit_after_check(row["subject"], reading, now=T0))


def plain_gate(ops: Ops) -> str:
    """An ordinary gate of a run that isn't a team: it must go out exactly as before."""
    eid = ops.add("plain-review")
    EventRecorder(eid).record(EventType.STAGE_STARTED, data={
        "name": "review", "gate": True, "gate_status": "waiting", "gate_path": "review",
        "gate_round": 1, "gate_context": {"upstream": [], "questions": [{"question": "Ship the plain run?"}]},
    }, execution_id=eid, status="waiting")
    return eid


@pytest.fixture
def db(tmp_path, request):
    """The test's database by URL, as ``temper pi team-alerts`` reaches it: a file when SQLite."""
    from temper_ai.database import init_database, reset_database
    from tests.conftest import TEST_DATABASE_URL

    url = request.node.stash.get(TEST_DATABASE_URL, "")
    if url.startswith("sqlite"):
        url = f"sqlite:///{tmp_path / 'alerts.db'}"
        reset_database()
        request.node.stash[TEST_DATABASE_URL] = url
        init_database(url)
    engine = get_database().engine
    Ledger(engine).ensure()
    yield url
    # The Postgres tier keeps the pi_ tables between tests: leave none of this test's rows.
    with engine.begin() as conn:
        conn.execute(sa.delete(waits))
        conn.execute(sa.delete(trials))
    if url.startswith("sqlite"):
        reset_database()


@pytest.fixture
def world(db, notify_config, monkeypatch):
    """Pi on, team alerts routed to the owner's DM, a notifier on a fixed clock."""
    monkeypatch.setenv("TEMPER_PI_AGENT", "1")
    notify_config(ROUTED)
    clock = {"now": T0}
    ops = Ops()
    slack = FakeSlack()

    def notifier(fake: FakeSlack | None = None) -> Notifier:
        n = Notifier(ConfigWatcher(), ops, clock=lambda: clock["now"])
        n.register(SlackSender(fake or slack))
        return n

    n = notifier()
    assert n.tick() == []           # switched on: nothing yet
    return {"db": db, "clock": clock, "ops": ops, "slack": slack, "n": n, "notifier": notifier,
            "write": notify_config}


def at(world: dict, minutes: int, base: datetime = T0) -> datetime:
    world["clock"]["now"] = base + timedelta(minutes=minutes)
    return world["clock"]["now"]


def team_copies(eid: str | None = None) -> list[Any]:
    return store.copies(kind=team_waits.KIND, execution_id=eid, statuses=None)


def copy_rows(eid: str | None = None) -> list[dict[str, Any]]:
    """The ``team_wait`` rows whole, every column (``detail`` too)."""
    table = NotifyCopy.__table__  # type: ignore[attr-defined]
    query = sa.select(table).where(table.c.kind == team_waits.KIND)
    if eid is not None:
        query = query.where(table.c.execution_id == eid)
    with get_database().engine.connect() as conn:
        return [dict(r) for r in conn.execute(query).mappings().all()]


def posts_to(slack: FakeSlack, text: str) -> list[dict[str, Any]]:
    return [p for p in slack.posts if p["text"] == text]


def export(world: dict, eid: str) -> dict[str, Any]:
    out = io.StringIO()
    assert team_alerts_command(eid, out=out, url=world["db"]) == 0
    answer = json.loads(out.getvalue())
    assert answer["ok"] is True and answer["execution_id"] == eid
    return answer


# --- The whole feature, in one go ---------------------------------------------------------


def test_each_asked_wait_reaches_the_owner_once_as_a_fixed_alert_and_closes_with_it(world):
    ops, slack, n = world["ops"], world["slack"], world["n"]
    team = Team(ops)
    scout = team.wait("owner")                                  # a member's question
    builder = team.wait("owner")                                # another, open at the same time
    check_in = team.wait("pause", {"at_usd": 100})              # the $100 check-in
    weekly = team.wait("limit", READY_WEEKLY)                   # restart after a weekly limit
    plain = plain_gate(ops)

    sent_at = at(world, 1)
    out = n.tick()

    # Read -> classify -> claim -> format -> send: four alerts, one per asked wait, to the DM.
    alerts = [o for o in out if o["kind"] == team_waits.KIND]
    assert len(alerts) == 4 and {o["execution_id"] for o in alerts} == {team.eid}
    reasons = {"a member's question": 2, "a spending check-in": 1, "a usage-limit restart decision": 1}
    for reason, count in reasons.items():
        got = posts_to(slack, ALERT.format(reason))
        assert len(got) == count and {p["channel"] for p in got} == {DM}
        for post in got:
            assert slack.buttons(post) == ["open_run"]          # a link, no answer buttons
            (link,) = [e["url"] for b in post["blocks"] if b["type"] == "actions" for e in b["elements"]]
            assert link == TEAM_PAGE + team.eid
    # The team's waits never go out as ordinary questions; the plain run's gate still does.
    assert store.copies(kind="question", execution_id=team.eid, statuses=None) == []
    (question,) = [p for p in slack.posts if "Ship the plain run?" in json.dumps(p)]
    assert {APPROVE, REJECT} <= set(slack.buttons(question))
    assert [o["execution_id"] for o in out if o["kind"] == "question"] == [plain]

    # Acknowledged: Slack gave each message back; the copy keeps that time, ids and the reason.
    copies = {team_waits.wait_of(c.key, c.state): c for c in team_copies(team.eid)}
    assert set(copies) == {scout, builder, check_in, weekly}
    for wait_id, c in copies.items():
        assert c.status == "sent" and c.ref.startswith(f"{DM}:1790000000.")
        assert c.state == {"wait_id": wait_id, "reason": c.state["reason"], "url": TEAM_PAGE + team.eid,
                           "acked_at": sent_at.isoformat()}

    # A second tick and a restarted notifier send nothing again.
    at(world, 2)
    assert [o for o in n.tick() if o["kind"] == team_waits.KIND] == []
    assert world["notifier"]().tick() == []
    assert len(slack.posts) == 5

    # The owner answers one question: that alert is edited to its closing line, only that one.
    team.answer(scout)
    at(world, 3)
    assert n.tick() == [{"kind": "team_wait_closed", "execution_id": team.eid, "via": "slack"}]
    (edit,) = slack.updates
    assert edit["text"] == "No longer waiting for you: a member's question."
    assert edit["ts"] == copies[scout].ref.partition(":")[2] and slack.buttons(edit) == ["open_run"]
    assert {c.status for c in team_copies(team.eid)} == {"sent", "closed"}

    # The team ends: every alert still open closes; nothing new is sent.
    team.end()
    at(world, 4)
    assert len([o for o in n.tick() if o["kind"] == "team_wait_closed"]) == 3
    assert {c.status for c in team_copies(team.eid)} == {"closed"} and len(slack.posts) == 5
    assert world["notifier"]().tick() == [] and len(slack.updates) == 4

    # The receipts FLOW's measure reads: one per wait, at its acknowledged time.
    assert export(world, team.eid) == {
        "ok": True, "execution_id": team.eid,
        "notices": sorted(({"wait_id": w, "at": sent_at.isoformat(), "channel": "slack"}
                           for w in (scout, builder, check_in, weekly)), key=lambda x: x["wait_id"])}

    # Nothing a member wrote went anywhere: not to Slack, not into a copy row.
    assert WORDS not in json.dumps(slack.posts + slack.updates)
    assert WORDS not in json.dumps(copy_rows(), default=str)


def test_the_leaders_refused_git_alerts_and_closes_with_its_own_reason_and_the_rest_keep_theirs(world):
    # #119 (Architecture's S3 on #115): Temper asks the owner about the leader's refused git
    # through an owner wait, but no member asked it. Its header picks its own fixed reason.
    ops, slack, n = world["ops"], world["slack"], world["n"]
    team = Team(ops)
    refused = team.wait("owner", {"label": "git-refused", "header": "git-refused",
                                  "reply_hint": WORDS, "refusals": WORDS})
    question = team.wait("owner")                               # a member's question
    check_in = team.wait("pause", {"at_usd": 100})

    at(world, 1)
    n.tick()

    git_refused = "the leader's work can't be shared"
    reasons = {refused: git_refused, question: "a member's question", check_in: "a spending check-in"}
    assert {team_waits.wait_of(c.key, c.state): c.state["reason"] for c in team_copies(team.eid)} == reasons
    assert sorted(p["text"] for p in slack.posts) == sorted(ALERT.format(r) for r in reasons.values())
    assert posts_to(slack, "The team is waiting for you: the leader's work can't be shared. Answer on the Team page.")

    team.answer(refused)
    at(world, 2)
    assert n.tick() == [{"kind": "team_wait_closed", "execution_id": team.eid, "via": "slack"}]
    assert [u["text"] for u in slack.updates] == ["No longer waiting for you: the leader's work can't be shared."]

    assert WORDS not in json.dumps(slack.posts + slack.updates)
    assert WORDS not in json.dumps(copy_rows(), default=str)


# --- Which waits get one: the Team page's own rule ----------------------------------------


def test_only_waits_the_page_asks_get_an_alert_and_none_goes_out_as_a_question(world):
    ops, slack, n = world["ops"], world["slack"], world["n"]
    team = Team(ops)
    team.wait("limit", FIVE_HOUR)                    # resumes by itself (asked or not)
    team.wait("limit", WEEK_AHEAD)                   # weekly, not reset yet: nothing to answer
    team.wait("pause", {"at_usd": 100}, ask=False)   # a check-in while running work finishes
    other = team.wait("recovery", {"turn_no": 3})    # another decision the page asks
    rounds = Team(ops, rounds=True)                  # a team in review rounds: unchanged
    rounds.wait("owner")

    at(world, 1)
    out = n.tick()
    assert [(o["kind"], o["execution_id"]) for o in out] == [("question", rounds.eid),
                                                              (team_waits.KIND, team.eid)]
    (alert,) = [p for p in slack.posts if p["text"].startswith("The team is waiting")]
    assert alert["text"] == ALERT.format("an owner decision")
    assert [team_waits.wait_of(c.key, c.state) for c in team_copies()] == [other]
    assert store.copies(kind="question", execution_id=team.eid, statuses=None) == []
    # The rounds team's question is the ordinary one, words and buttons as before.
    assert len(store.copies(kind="question", execution_id=rounds.eid)) == 1
    (question,) = [p for p in slack.posts if p is not alert]
    assert {APPROVE, REJECT} <= set(slack.buttons(question)) and WORDS in json.dumps(question)

    # Once the running work has finished, the team asks the check-in: now it gets its alert.
    check_in = next(w["wait_id"] for w in team.ledger.open_waits(team.eid, HOST) if w["kind"] == "pause")
    team.ask(check_in)
    at(world, 2)
    assert [o["kind"] for o in n.tick()] == [team_waits.KIND]
    assert posts_to(slack, ALERT.format("a spending check-in"))
    assert WORDS not in json.dumps([p for p in slack.posts if p["text"].startswith("The team")])


def test_a_wait_closed_or_a_team_ended_before_the_alert_went_out_sends_nothing(world):
    ops, slack, n = world["ops"], world["slack"], world["n"]
    closed = Team(ops)
    closed.answer(closed.wait("owner"))
    ended = Team(ops)
    ended.wait("owner")
    ended.end("cancelled")

    at(world, 1)
    assert n.tick() == []
    assert slack.posts == [] and team_copies() == []
    assert store.copies(kind="question", statuses=None) == []


def test_settings_limits_without_a_reset_closing_checks_and_cancel_time_waits_get_what_the_page_asks(world):
    """H-NOTICE-1 for the wait kinds no other test covers: one alert for each wait the Team
    page asks, none for a wait it never asks, and nothing new when a cancel opens and closes
    waits (S-G5: 92f0123a's stop opened 4 recovery waits, cancelled 0.04-0.26 s later)."""
    ops, slack, n = world["ops"], world["slack"], world["n"]

    def kinds(out: list[dict[str, Any]], team: Team) -> list[str]:
        return [o["kind"] for o in out if o["execution_id"] == team.eid]

    def alerted(team: Team) -> dict[str, str]:
        return {team_waits.wait_of(c.key, c.state): c.status for c in team_copies(team.eid)}

    # 1. Settings changed mid-conversation: the settings wait is asked first and gets one
    #    alert. The member's question alerted before it keeps its one alert, never a second,
    #    while the settings wait holds it back and after the settings wait is answered.
    s = Team(ops)
    question = s.wait("owner")
    at(world, 1)
    assert kinds(n.tick(), s) == [team_waits.KIND]
    subject = team_subject([("scout", "p-scout", {"team": "a", "model": "m1"}, {"team": "a", "model": "m2"})])
    assert subject["header"] == SETTINGS and subject["pins"]
    settings = s.wait(SETTINGS, subject)
    later = s.wait("owner")                     # a running turn's question, asked meanwhile
    at(world, 2)
    assert kinds(n.tick(), s) == [team_waits.KIND]
    assert alerted(s) == {question: "sent", settings: "sent"}
    assert len(posts_to(slack, ALERT.format("an owner decision"))) == 1
    s.answer(settings)
    at(world, 3)
    assert kinds(n.tick(), s) == [team_waits.KIND, "team_wait_closed"]
    assert alerted(s) == {question: "sent", settings: "closed", later: "sent"}
    assert slack.updates[-1]["text"] == "No longer waiting for you: an owner decision."

    # 2. A usage limit whose words give no reset time: weekly, a re-check in 15 minutes, not
    #    verified. Nothing to answer (no alert, even with its gate waiting) until a fresh check
    #    shows room; then exactly one, kept through later checks that take room away and back.
    details = limit_details("acct-1", "Claude usage limit reached.")
    resume = limit_resume(details, now=T0)
    assert details["resets"] is None and resume["how"] == "recheck" and resume["kind"] == "weekly"
    lim = Team(ops)
    limit = lim.wait("limit", {**details, **resume, "label": "usage-limit"})
    assert not limit_restart_ready(lim.ledger.open_waits(lim.eid, HOST)[0]["subject"])
    recheck(lim, limit, 100)                     # still no room, and still no reset time
    at(world, 4)
    assert kinds(n.tick(), lim) == [] and alerted(lim) == {}
    recheck(lim, limit, 20)                      # room: now the owner decides the restart
    lim.ask(limit)
    at(world, 5)
    assert kinds(n.tick(), lim) == [team_waits.KIND] and alerted(lim) == {limit: "sent"}
    recheck(lim, limit, 100)
    at(world, 6)
    assert kinds(n.tick(), lim) == []
    recheck(lim, limit, 20)
    lim.ask(limit)
    at(world, 7)
    assert kinds(n.tick(), lim) == [] and alerted(lim) == {limit: "sent"}
    assert len(posts_to(slack, ALERT.format("a usage-limit restart decision"))) == 1

    # 3. Temper's own closing check: the owner never answers it, so no alert and no ordinary
    #    question, even with a gate waiting for it; Temper settling it closes nothing.
    c = Team(ops)
    closing = c.wait("closing", {"label": "closing", "stage": "finishing"})
    at(world, 8)
    assert kinds(n.tick(), c) == []
    c.answer(closing)
    at(world, 9)
    assert kinds(n.tick(), c) == [] and alerted(c) == {}

    # 4. The owner stops the team: the stop opens 4 recovery waits for the cut turns and
    #    cancels them with every other open wait within a second. A tick inside that second
    #    sends nothing for them; the end closes the one earlier alert and sends nothing new.
    x = Team(ops)
    asked = x.wait("owner")
    at(world, 10)
    assert kinds(n.tick(), x) == [team_waits.KIND]
    cut = [x.wait("recovery", {"turn_no": i, "why": "cancelled", "options": ["accept", "retry"]}, ask=False)
           for i in range(1, 5)]
    at(world, 11)
    assert kinds(n.tick(), x) == []
    ended = x.ledger.end_team(x.eid, HOST, "run_cancelled", "attempt-1")
    assert {w["wait_id"] for w in ended["cancelled_waits"]} == {asked, *cut}
    x.end("cancelled")
    at(world, 12)
    assert kinds(n.tick(), x) == ["team_wait_closed"] and alerted(x) == {asked: "closed"}

    # In all: one alert per asked wait (3 + 1 + 0 + 1), each with the Team-page link; no other.
    alerts = [p for p in slack.posts if p["text"].startswith("The team is waiting")]
    assert len(alerts) == len(slack.posts) == 5
    for post in alerts:
        (link,) = [e["url"] for b in post["blocks"] if b["type"] == "actions" for e in b["elements"]]
        assert link.startswith(TEAM_PAGE) and slack.buttons(post) == ["open_run"]
    assert store.copies(kind="question", statuses=None) == []
    assert WORDS not in json.dumps(slack.posts + slack.updates)


# --- Quiet hours ----------------------------------------------------------------------------


def test_quiet_hours_let_team_alerts_through_unless_told_not_to(world):
    ops, slack, n, write = world["ops"], world["slack"], world["n"], world["write"]
    quiet = '  quiet_hours: {from: "22:00", to: "07:00", zone: America/Los_Angeles}\n  agents: [telegram]'
    write(ROUTED.replace("  agents: [telegram]", quiet))
    team = Team(ops)
    team.wait("owner")
    at(world, 0, NIGHT)
    assert [o["kind"] for o in n.tick()] == [team_waits.KIND]       # it asks you: it goes now
    assert len(posts_to(slack, ALERT.format("a member's question"))) == 1

    # Told to hold them: held till morning, and sent then only if the team still asks.
    write(ROUTED.replace("  agents: [telegram]", quiet.replace("}", ", still_ping: [question]}", 1)))
    stays, goes = Team(ops), Team(ops)
    stays_wait = stays.wait("pause", {"at_usd": 100})
    goes_wait = goes.wait("owner")
    at(world, 5, NIGHT)
    held = n.tick()
    assert {o["execution_id"] for o in held} == {stays.eid, goes.eid}
    assert {datetime.fromisoformat(o["held_until"]) for o in held} == {MORNING}
    assert len(slack.posts) == 1
    goes.answer(goes_wait)
    at(world, 0, MORNING)
    out = n.tick()
    assert [(o["kind"], o["execution_id"]) for o in out if "ref" in o] == [(team_waits.KIND, stays.eid)]
    by_wait = {team_waits.wait_of(c.key, c.state): c for c in team_copies()}
    assert by_wait[stays_wait].status == "sent" and by_wait[stays_wait].state["acked_at"] == MORNING.isoformat()
    assert by_wait[goes_wait].status == "closed" and "acked_at" not in by_wait[goes_wait].state
    assert len(posts_to(slack, ALERT.format("a spending check-in"))) == 1 and len(slack.posts) == 2


# --- Sends that fail or aren't confirmed --------------------------------------------------


class Unconfirmed(FakeSlack):
    """Slack that times out, or answers without the posted message."""

    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode

    def post(self, channel: str, text: str, blocks: list[dict] | None = None, thread_ts: str | None = None,
             broadcast: bool = False) -> dict[str, Any]:
        if self.mode == "timeout":
            raise TimeoutError("Slack did not answer in time")
        self.posts.append({"channel": channel, "text": text, "blocks": blocks})
        return {"ok": True}


@pytest.mark.parametrize("mode", ["rejected", "timeout", "no message back"])
def test_a_send_slack_did_not_confirm_is_failed_never_a_receipt_and_never_repeated(world, mode):
    ops = world["ops"]
    fake = FakeSlack() if mode == "rejected" else Unconfirmed(mode)
    if mode == "rejected":
        fake.forbidden.add(DM)
    n = world["notifier"](fake)
    team = Team(ops)
    wait_id = team.wait("owner")
    at(world, 1)
    (out,) = n.tick()
    assert out["kind"] == team_waits.KIND and "error" in out and "ref" not in out
    (c,) = team_copies(team.eid)
    assert c.status == "failed" and "acked_at" not in (c.state or {})
    at(world, 2)
    assert n.tick() == [] and len(team_copies(team.eid)) == 1
    assert export(world, team.eid)["notices"] == []
    team.answer(wait_id)
    at(world, 3)
    assert n.tick() == [] and fake.updates == []


def test_a_send_cut_off_midway_is_never_repeated_and_closes_as_unconfirmed(world):
    ops, slack, n = world["ops"], world["slack"], world["n"]
    team = Team(ops)
    wait_id = team.wait("owner")
    alert = team_waits.TeamAlert(team.eid, wait_id, "", "a member's question", TEAM_PAGE + team.eid)
    # The server stopped between claiming the copy and hearing back from Slack.
    assert store.claim(alert.key, team_waits.KIND, team.eid, "slack", DM, state=alert.state)
    at(world, 1)
    assert n.tick() == [] and slack.posts == []
    team.answer(wait_id)
    at(world, 2)
    assert n.tick() == [{"kind": "team_wait_closed", "execution_id": team.eid, "via": "slack"}]
    (row,) = copy_rows(team.eid)
    assert row["status"] == "closed" and row["detail"] == "send not confirmed" and slack.updates == []
    assert export(world, team.eid)["notices"] == []


# --- Reading the teams fails, or the Pi step is off ----------------------------------------


def test_when_the_team_waits_cannot_be_read_nothing_with_a_members_words_goes_out(world, monkeypatch):
    ops, slack, n = world["ops"], world["slack"], world["n"]
    team = Team(ops)
    first = team.wait("owner")
    at(world, 1)
    n.tick()
    assert len(slack.posts) == 1
    team.answer(first)
    team.wait("owner")
    plain = plain_gate(ops)

    def broken(*_args: Any) -> None:
        raise RuntimeError("the ledger is not readable")

    monkeypatch.setattr(team_waits, "_scan", broken)
    at(world, 2)
    out = n.tick()
    # No alert, no close, no step's wait as a question; the plain gate goes out as before.
    assert [(o["kind"], o["execution_id"]) for o in out] == [("question", plain)]
    assert [c.status for c in team_copies(team.eid)] == ["sent"] and slack.updates == []
    assert WORDS not in json.dumps(slack.posts)


def test_with_the_pi_step_off_nothing_pi_is_read_and_gates_go_out_as_before(db, notify_config, monkeypatch):
    monkeypatch.delenv("TEMPER_PI_AGENT", raising=False)
    notify_config(ROUTED)

    def looked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the Pi ledger was read with the Pi step off")

    monkeypatch.setattr(team_waits, "_scan", looked)
    monkeypatch.setattr(Ledger, "open_waits", looked)
    ops, slack = Ops(), FakeSlack()
    n = Notifier(ConfigWatcher(), ops, clock=lambda: T0)
    n.register(SlackSender(slack))
    assert n.tick() == []
    plain = plain_gate(ops)
    out = n.tick()
    assert [(o["kind"], o["execution_id"]) for o in out] == [("question", plain)]
    assert {APPROVE, REJECT} <= set(slack.buttons(slack.posts[0]))
    assert n.last_error is None


# --- Routing and receipts on their own ----------------------------------------------------


def test_team_alerts_go_only_where_a_block_names_them_and_still_ping_through_quiet_hours(notify_config):
    plain = NotifyConfig()
    assert plain.route("team_wait", None) == () and plain.route("question", None) == ("origin",)
    notify_config(ROUTED.replace("  agents: [telegram]",
                                 '  quiet_hours: {from: "22:00", to: "07:00"}\n  agents: [telegram]'))
    cfg = load_config()
    assert cfg.route("team_wait", "any-workflow") == ("slack",)
    quiet = cfg.quiet_hours("any-workflow")
    assert quiet is not None and quiet.still_ping == ("question", "team_wait")


def test_receipts_keep_each_waits_first_acknowledged_copy_only():
    rows = [
        {"kind": "team_wait", "key": "tw:w1", "via": "slack", "state": {"wait_id": "w1", "acked_at": "2026-09-28T17:05:00+00:00"}},
        {"kind": "team_wait", "key": "tw:w1", "via": "slack", "state": {"wait_id": "w1", "acked_at": "2026-09-28T17:01:00+00:00"}},
        {"kind": "team_wait", "key": "tw:w2", "via": "slack", "state": {"wait_id": "w2"}},   # never confirmed
        {"kind": "question", "key": "q:e1", "via": "slack", "state": {"acked_at": "2026-09-28T17:00:00+00:00"}},
    ]
    assert team_waits.receipts(rows) == {"notices": [
        {"wait_id": "w1", "at": "2026-09-28T17:01:00+00:00", "channel": "slack"}]}


def test_team_alerts_export_fails_loudly_on_a_database_without_the_notify_table(tmp_path):
    out = io.StringIO()
    empty = f"sqlite:///{tmp_path / 'empty.db'}"
    sa.create_engine(empty).dispose()
    assert team_alerts_command("any-run", out=out, url=empty) == TEAM_ALERTS_FAILED
    answer = json.loads(out.getvalue())
    assert answer["ok"] is False and "notify_copies" in answer["error"]
