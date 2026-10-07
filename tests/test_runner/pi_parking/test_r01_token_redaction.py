"""R01 (SW-52): a planted login token never leaves a team run (queue #76: gaps 1, 2 and 4 of
Temper's SW-52 coverage map).

Cases a-d are team trials started through the Team API on a real in-process Temper with the
Pi switch on (test_team_api.py's ``api``), every member a scripted Pi (TeamFakeBox) behind the
real turn code. Cases e-j cover the event door, the single-step path and the stream rule.
Nothing reaches a model, the network, a credential, the host helper, a usage figure or the
account room: each is a tripwire counted here, and every count must be 0.

The tokens are made in this file from pieces (the repo is public, so no file holds a whole
one): one of an OAuth access token's shape, and the run's own login token, handed off the way
WorkerBox._handoff hands it (the turn's redactor and the token scan learn it before Pi has it).
Each case has its own tokens, so rows another test left in a shared test database never count.

- a, the done path (gap 1), the whole feature in one run: a member commits a file holding a
  token, and one holding the run's own token, into its version, and a review call holding the
  token is refused before a clean one. The team ends done, the version is withheld and no
  branch is made, and the token is in no stored row of the test database (the outcome row, the
  node's output, the workflow outputs, every event, every pi_ row), in no file of the run's
  log folder (its event log), in no answer the server gives about the run (the run page's routes, the Team API's, the version route that names
  rules and paths only), in no member's prompt and in none of Temper's answers to the members.
- b, the review tool (gap 2): a request_review note, a give_view note and a decide summary,
  each holding a token, are refused naming the rule; the turn keeps the refusal's words only,
  and nothing of the call is kept anywhere.
- c, a provider error (gap 4): an error reply whose words hold a token ends the turn; the
  turn's error, the stage's and the run's, the events, the event log, the run page and the
  Team API carry a marker in its place, never the token.

Every check of a case runs, and a case that fails lists the places by name (a table and its
columns, a route, a prompt), never the text found there: that text is a token.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import socket
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

from temper_ai.llm.pi_stream import REDACTED, PiEventMapper, Redactor, record_outcome
from temper_ai.pi_agent import token_scan
from temper_ai.pi_agent import turn as turn_mod
from temper_ai.pi_agent.event_guard import (
    STREAM_HOLD_CAP,
    TOKEN_GUARD,
    GuardedRecorder,
    ShapeStream,
    guarded,
    guarded_context,
)
from temper_ai.pi_agent.ledger import messages, outcomes, reviews
from temper_ai.pi_agent.team_runtime import Team
from temper_ai.shared.types import ExecutionContext
from tests.test_pi_agent import support as sup
from tests.test_pi_agent import test_team as tt
from tests.test_pi_agent import test_turn as turns
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking import test_team_api as team_api
from tests.test_runner.pi_parking import test_team_runs as runs
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts

team_on = tt.team_on
tr = runs.tr
api = team_api.api

THOST = team_api.THOST
SHAPE = "anthropic_oauth_access_token"
OWN = token_scan.RUN_TOKEN
ZERO = dict.fromkeys(("model_call", "usage_read", "credential_read", "host_helper",
                      "account_room_read", "socket_connect"), 0)
#: Every GET answer the server gives about one run: the run page's routes and the Team API's.
ROUTES = (
    ("the run page", "/api/workflows/{id}"),
    ("the run's agents", "/api/workflows/{id}/agents"),
    ("the run's tool calls", "/api/runs/{id}/tool-calls"),
    ("the run's waits", "/api/runs/{id}/gates"),
    ("the run's decisions", "/api/runs/{id}/decisions"),
    ("the run's checkpoints", "/api/runs/{id}/checkpoints"),
    ("the run's resume preview", "/api/runs/{id}/resume-preview"),
    ("the run list", "/api/workflows"),
    ("the Team API's run", "/api/team/runs/{id}"),
    ("the Team API's version", "/api/team/runs/{id}/version"),
    ("the Team API's trials", "/api/team/trials"),
    ("the Team API's status", "/api/team/status"),
)


@pytest.fixture(autouse=True)
def _forget_tokens():
    token_scan.forget_all()
    yield
    token_scan.forget_all()


# --- the tokens -------------------------------------------------------------------------------


def planted(mark: str) -> str:
    """A token of an OAuth access token's shape (test_team_versions.py's way), marked so that
    no other test's rows hold it."""
    return "sk-ant-" + "oat01-" + ("R01" + mark) * 8


def own_token(mark: str) -> str:
    """The run's own login token (the run_token rule): what the box hands Pi."""
    return "r01-own-login-" + ("own" + mark) * 8


def tokens(kind: str, mark: str) -> tuple[str, str, str]:
    """(the token a member plants, the run's own token, the rule naming the planted one)."""
    own = own_token(mark)
    return (own, own, OWN) if kind == "own" else (planted(mark), own, SHAPE)


def handed_off(token: str) -> dict:
    """A turn's login hand-off as WorkerBox._handoff does it: the turn's redactor and the token
    scan learn the run's own token before Pi has it."""
    def learn(box, _message: str) -> None:
        box.redactor.add(token)
        token_scan.remember(token)
    return {"call": learn}


def with_hand_off(token: str) -> None:
    """Every scripted turn of every member starts with its hand-off."""
    for member, scripts in list(ts.SCRIPTS.items()):
        ts.SCRIPTS[member] = [[handed_off(token), *turn] for turn in scripts]


def refusal(rule: str) -> str:
    """Temper's answer to a call holding one token: the rule's name, never the text."""
    return (f"refused: it holds 1 login-token match(es) ({rule} x1); nothing was sent or "
            "recorded. Never put a login token in a message or a note")


# --- what a run must never reach --------------------------------------------------------------


class Wires:
    """Counted and refused: a model call, a usage figure, a credential, the host helper, the
    account room, and any socket connection but the test's own Unix sockets under its folder
    (the test database's connections never pass through Python's sockets)."""

    def __init__(self, monkeypatch, own: Path):
        from temper_ai.llm import week_usage
        from temper_ai.llm.providers.base import BaseLLM
        from temper_ai.llm.service import LLMService
        from temper_ai.pi_agent import accounts, host_helper
        from temper_ai.pi_agent.box import WorkerBox

        self.trips = {"model_call": sup.Tripwire("a model call"),
                      "usage_read": sup.Tripwire("a usage figure read"),
                      "credential_read": sup.Tripwire("a credential read"),
                      "host_helper": sup.Tripwire("a host helper call"),
                      "account_room_read": sup.Tripwire("an account room read")}
        for owner, name, trip in (
                (LLMService, "run", "model_call"), (BaseLLM, "complete", "model_call"),
                (BaseLLM, "stream", "model_call"), (WorkerBox, "_connect_upstream", "model_call"),
                (week_usage, "highest", "usage_read"), (week_usage, "over_line", "usage_read"),
                (week_usage, "accounts", "usage_read"),
                (WorkerBox, "_host_pi_token", "credential_read"),
                (host_helper, "token", "host_helper"), (host_helper, "ask", "host_helper"),
                (accounts, "read_room", "account_room_read")):
            monkeypatch.setattr(owner, name, self.trips[trip])
        self.own, self.allowed, self.refused = str(own), 0, 0
        for name in ("connect", "connect_ex"):
            monkeypatch.setattr(socket.socket, name, self._guard(getattr(socket.socket, name)))

    def _guard(self, through):
        def connect(sock, address):
            if (sock.family == socket.AF_UNIX and isinstance(address, (str, bytes))
                    and os.fsdecode(address).startswith(self.own)):
                self.allowed += 1
                return through(sock, address)
            self.refused += 1
            raise OSError("R01 test: no socket connection but the test's own Unix sockets")
        return connect

    def counts(self) -> dict[str, int]:
        return {**{k: t.calls for k, t in self.trips.items()}, "socket_connect": self.refused}


@pytest.fixture
def wires(monkeypatch, tmp_path):
    return Wires(monkeypatch, tmp_path)


# --- where a token could be --------------------------------------------------------------------


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("latin-1")
    return json.dumps(value, default=str)


class Findings:
    """Every check runs to the end. Failures name places or conditions, never captured values."""

    def __init__(self, *secrets: str):
        self.needles = sorted({*secrets, *(s[-20:] for s in secrets)}, key=len, reverse=True)
        self.failed: list[str] = []

    def holds(self, value: Any) -> bool:
        text = _text(value)
        return any(n in text for n in self.needles)

    def clean(self, place: str, value: Any) -> None:
        if self.holds(value):
            self.failed.append(f"a token is in {place}")

    def check(self, ok: bool, what: str, got: Any = None) -> None:
        if not ok:
            self.failed.append(what)

    def stored(self, engine, eid: str) -> int:
        """Every row of every table in the test database; returns how many name the run."""
        of_run = 0
        names = sorted(sa.inspect(engine).get_table_names())
        with engine.connect() as conn:
            for name in names:
                columns, kinds, held = set(), set(), 0
                for row in conn.execute(sa.text(f'SELECT * FROM "{name}"')).mappings():
                    text = {c: _text(v) for c, v in row.items() if v is not None}
                    of_run += any(eid in t for t in text.values())
                    hit = [c for c, t in text.items() if self.holds(t)]
                    if hit:
                        held += 1
                        columns.update(hit)
                        if name == "events" and row.get("type") is not None:
                            kinds.add(str(row["type"]))
                if held:
                    types = f"; event types {', '.join(sorted(kinds))}" if kinds else ""
                    self.failed.append(f"a token is in table {name}: {held} row(s), column(s) "
                                       f"{', '.join(sorted(columns))}{types}")
        return of_run

    def logged(self, eid: str) -> int:
        """Every file of the run's own log folder (its event log, TEMPER_LOG_DIR/<run>/); returns
        how many there are."""
        folder = Path(os.environ["TEMPER_LOG_DIR"]) / eid
        files = sorted(p for p in folder.rglob("*") if p.is_file())
        for path in files:
            self.clean(f"the run's log file {path.relative_to(folder)}",
                       path.read_bytes().decode("utf-8", "replace"))
        return len(files)

    def served(self, client, eid: str, message_ids: list[str]) -> dict[str, Any]:
        """Every GET answer the server gives about the run, each message's full text too."""
        got = {}
        routes = [*ROUTES, *((f"the Team API's message {m}", f"/api/team/runs/{{id}}/messages/{m}")
                             for m in message_ids)]
        for place, route in routes:
            r = client.get(route.format(id=eid))
            self.clean(f"{place} (GET {route})", r.text)
            got[route] = r
        return got

    def everywhere(self, api, eid: str) -> dict[str, Any]:
        """The test database, the run's log files, the server's answers, every member's prompts
        and Temper's answers to the members' calls."""
        of_run = self.stored(api.led.engine, eid)
        self.check(of_run > 0, "the database scan saw rows of the run")
        self.check(self.logged(eid) > 0, "the run's log folder has files")
        mids = [m["message_id"] for m in ls.table(api.led, messages, eid, THOST)]
        answers = self.served(api.client, eid, mids)
        for member, given in ts.PROMPTS.items():
            self.clean(f"{member}'s prompts", given)
        self.clean("Temper's answers to the members' calls", [s["reply"] for s in ts.SENDS])
        return answers

    def json(self, answers: dict[str, Any], route: str) -> dict:
        r = answers[route]
        self.check(r.status_code == 200, f"GET {route} answers 200", r.text)
        return r.json() if r.status_code == 200 else {}


def snapshot(api, eid: str) -> tuple[dict, dict]:
    """The team's rows, and its turns by (member, turn number)."""
    snap = ts.rows(api.led, eid, THOST)
    who = {p["participant_id"]: p["member"] for p in snap["participants"]}
    return snap, {(who[t["participant_id"]], t["turn_no"]): t for t in snap["turns"]}


def refused_calls(findings: Findings, snap: dict, by_turn: dict, rule: str,
                  expected: list[tuple[str, int, str]]) -> None:
    """Each refused call (member, turn, op) was answered naming the rule; its turn keeps only
    the refusal's words; no act and no message comes from it."""
    refused = [s for s in ts.SENDS if s["reply"].get("ok") is not True]
    findings.check([(s["member"], s["payload"].get("op")) for s in refused]
                   == [(m, op) for m, _n, op in expected], "the calls refused", refused)
    for s in refused:
        findings.check(s["reply"].get("ok") is False and s["reply"].get("detail") == refusal(rule),
                       f"{s['member']}'s refused {s['payload'].get('op')} names the rule",
                       s["reply"])
    kept = {key: t["refusals"] or [] for key, t in by_turn.items()}
    want = {}
    for (member, n, _op), s in zip(expected, refused, strict=False):
        want.setdefault((member, n), []).append(s["reply"].get("detail"))
    for key, items in kept.items():
        findings.check([sorted(i) for i in items] == [["at", "code", "token_refused"]]
                       * len(want.get(key, [])), f"{key}'s refusals keep only token_refused",
                       items)
        findings.check([i.get("token_refused") for i in items] == want.get(key, []),
                       f"{key}'s refusals are the refusal's words", items)
    ids = {s["payload"].get("client_msg_id") for s in refused}
    findings.check(not [a for a in snap["acts"] if a["client_msg_id"] in ids],
                   "no act comes from a refused call")
    findings.check(not [m for m in snap["messages"] if m["client_msg_id"] in ids],
                   "no message comes from a refused call")


def one_row(findings: Findings, api, table: sa.Table, eid: str) -> dict:
    rows = ls.table(api.led, table, eid, THOST)
    findings.check(len(rows) == 1, f"one {table.name} row", len(rows))
    row = dict(rows[0]) if rows else {}
    if isinstance(row.get("record"), str):
        row["record"] = json.loads(row["record"])
    return row


def no_wires(findings: Findings, wires: Wires, record_property) -> None:
    counts = wires.counts()
    record_property("tripwire_calls", counts)
    findings.check(counts == ZERO, "every tripwire stays at 0", counts)
    record_property("r01_failed_conditions", findings.failed)


# --- a, the done path (gap 1): the whole feature in one run --------------------------------------


def test_a_planted_token_never_leaves_a_team_run_that_ends_done(api, wires, record_property):
    """A member commits a file holding a token, and one holding the run's own token, into its
    version, and asks for a review with the token in its note (refused) before a clean ask.
    The team ends done on that version: withheld, no branch, and no token anywhere."""
    token, own, _rule = tokens("shape", "a")
    runs.script(api.led, ["done"])
    write_readme, ask = ts.SCRIPTS["design"][0]
    ts.SCRIPTS["design"][0] = [ls.write("config.env", f"ANTHROPIC_TOKEN={token}\n"),
                               ls.write("notes.txt", f"login: {own}\n"), write_readme,
                               ls.request_review(f"draft 1, signed {token}"), ask]
    with_hand_off(own)
    started = team_api.start_trial(api, team_api.body(api))
    tid, eid = started["trial_id"], started["execution_id"]
    ended = pw.wait_ended(eid, 1)

    f = Findings(token, own)
    f.check(ended[-1]["status"] == "completed", "the run completed", runs.stage_error(eid, "trial"))
    answers = f.everywhere(api, eid)
    out = ended[-1]["data"].get("workflow_output") or {}
    f.clean("the workflow outputs", out)

    # the refused review call: named, audited by its words only, nothing of it kept
    snap, by_turn = snapshot(api, eid)
    refused_calls(f, snap, by_turn, SHAPE, [("design", 1, "request_review")])
    f.check([a["op"] for a in snap["acts"]]
            == ["request_review", "give_view", "give_view", "decide"], "the acts kept",
            [a["op"] for a in snap["acts"]])
    review = one_row(f, api, reviews, eid)
    f.check((review.get("decision"), review.get("summary")) == ("done", "summary 1"),
            "the review's decision", review)
    f.check(not review.get("files"), "the withheld version's review row keeps no files",
            review.get("files"))
    asked = [m for m in snap["messages"] if m["kind"] == "review_request"]
    f.check(sorted(m["to_member"] for m in asked) == ["frontend", "qa"],
            "one review request to each member", asked)

    # the done record: the outcome row, the node's output, the workflow outputs
    row = one_row(f, api, outcomes, eid)
    record = row.get("record") or {}
    held = {SHAPE: 2, OWN: 2}
    why = "the version holds 4 login-token match(es) (anthropic_oauth_access_token x2, run_token x2) in "
    for place, rec in (("the outcome row's record", record), ("the workflow outputs", out)):
        version, branch = rec.get("version") or {}, rec.get("branch") or {}
        f.check(rec.get("decision") == "done" and rec.get("summary") == "summary 1",
                f"{place}: done", rec)
        f.check(version.get("files") == {} and version.get("withheld") == held,
                f"{place}: the version's files withheld", version)
        f.check(version.get("commit") == review.get("commit_sha"),
                f"{place}: the reviewed commit", version)
        f.check(branch.get("name") == f"team/{tid}" and branch.get("made") is False,
                f"{place}: no branch made", branch)
        f.check(str(branch.get("why") or "").startswith(why)
                and str(branch.get("why")).endswith(", so no branch was made from it"),
                f"{place}: why no branch", branch)
    f.check(row.get("decision") == "done", "the outcome row's decision", row.get("decision"))
    refs = ls.git(api.ws, "for-each-ref", "--format=%(refname)").split()
    f.check(not [r for r in refs if r.startswith("refs/heads/team/")],
            "no team branch in the project", refs)

    # the Team API: the run done, the version naming rules and paths only
    run = f.json(answers, "/api/team/runs/{id}")
    f.check(run.get("state") == "done" and (run.get("outcome") or {}).get("decision") == "done",
            "the Team API's run is done", {k: run.get(k) for k in ("state", "outcome")})
    v = f.json(answers, "/api/team/runs/{id}/version")
    withheld = v.get("withheld") or {}
    f.check(v.get("kind") == "done" and v.get("files") == [], "the version route keeps no files",
            v)
    f.check(withheld.get("rules") == held, "the version route names the rules", withheld)
    f.check(sorted(withheld.get("paths") or []) == ["file config.env", "file notes.txt",
                                                     "the diff"],
            "the version route names the paths", withheld)
    f.check(str(v.get("note") or "").startswith("withheld: "), "the version route's note", v)

    no_wires(f, wires, record_property)
    assert f.failed == [], "\n".join(f.failed)


# --- b, the review tool (gap 2) ----------------------------------------------------------------


@pytest.mark.parametrize(("kind", "mark"), [("shape", "b"), ("own", "c")],
                         ids=["a-token-s-shape", "the-run-s-own-token"])
def test_a_review_call_holding_a_token_is_refused_and_nothing_of_it_is_kept(
        api, wires, record_property, kind, mark):
    """A request_review note, a give_view note and a decide summary holding a token, each sent
    through the review tool before a clean call: refused naming the rule, the turn keeps the
    refusal's words only, and nothing of the call is kept anywhere."""
    token, own, rule = tokens(kind, mark)
    runs.script(api.led, ["done"])
    design, frontend = ts.SCRIPTS["design"], ts.SCRIPTS["frontend"]
    design[0].insert(1, ls.request_review(f"draft 1, signed {token}"))
    frontend[0].insert(0, ls.give_view(api.led, None, "satisfied", f"fine; key {token}"))
    design[1].insert(0, ls.decide(api.led, None, "done", f"done, with {token}"))
    with_hand_off(own)
    eid = team_api.start_trial(api, team_api.body(api))["execution_id"]
    ended = pw.wait_ended(eid, 1)

    f = Findings(token, own)
    f.check(ended[-1]["status"] == "completed", "the run completed", runs.stage_error(eid, "trial"))
    answers = f.everywhere(api, eid)
    snap, by_turn = snapshot(api, eid)
    refused_calls(f, snap, by_turn, rule, [("design", 1, "request_review"),
                                           ("frontend", 1, "give_view"), ("design", 2, "decide")])
    f.check(not [s for s in ts.SENDS if s["reply"].get("ok") is True and f.holds(s["payload"])],
            "only clean calls were taken")
    f.check([a["op"] for a in snap["acts"]]
            == ["request_review", "give_view", "give_view", "decide"], "the acts kept",
            [a["op"] for a in snap["acts"]])
    review = one_row(f, api, reviews, eid)
    f.check((review.get("decision"), review.get("summary")) == ("done", "summary 1"),
            "the decision is the clean call's", review)
    asked = [m for m in snap["messages"] if m["kind"] == "review_request"]
    f.check(len(asked) == 2, "one review request to each member", asked)
    row = one_row(f, api, outcomes, eid)
    record = row.get("record") or {}
    f.check(row.get("decision") == "done" and record.get("summary") == "summary 1",
            "the outcome is the clean decision's", row)
    views = {m: (v or {}).get("note") for m, v in (record.get("views") or {}).items()}
    f.check(views == {"frontend": "frontend note 1", "qa": "qa note 1"},
            "the views are the clean calls'", views)
    run = f.json(answers, "/api/team/runs/{id}")
    f.check(run.get("state") == "done", "the Team API's run is done", run.get("state"))

    no_wires(f, wires, record_property)
    assert f.failed == [], "\n".join(f.failed)


# --- c, a provider error (gap 4) ---------------------------------------------------------------


@pytest.mark.parametrize(("kind", "mark"), [("shape", "d"), ("own", "e")],
                         ids=["a-token-s-shape", "the-run-s-own-token"])
def test_a_provider_error_holding_a_token_never_shows_it(api, wires, record_property, kind,
                                                         mark):
    """The provider's error reply holds a token and ends design's first turn: the turn's error,
    the stage's and the run's, the events, the run page and the Team API show a marker in its
    place (the token scan's for a token's shape, the redactor's for the run's own token)."""
    token, own, _rule = tokens(kind, mark)
    runs.script(api.led, ["done"])
    ts.SCRIPTS["design"].insert(0, [{"error": "400 invalid_request_error: the request was "
                                              f"refused (it named {token})"}])
    with_hand_off(own)
    eid = team_api.start_trial(api, team_api.body(api))["execution_id"]
    ended = pw.wait_ended(eid, 1)

    f = Findings(token, own)
    f.check(ended[-1]["status"] == "failed", "the run failed", ended[-1]["status"])
    answers = f.everywhere(api, eid)
    marker = REDACTED if kind == "own" else token_scan.WITHHELD
    _snap, by_turn = snapshot(api, eid)
    turn = by_turn.get(("design", 1)) or {}
    error = str(turn.get("error") or "")
    f.check(turn.get("state") == "failed", "design's turn failed", turn.get("state"))
    f.check(error.startswith("design (architecture) turn 1 failed: ")
            and "400 invalid_request_error" in error and marker in error,
            "the turn's error keeps the provider's words with a marker for the token", error)
    stage = runs.stage_error(eid, "trial")
    f.check("design (architecture) turn 1 failed" in stage and marker in stage,
            "the stage's error carries the marker", stage)
    row = one_row(f, api, outcomes, eid)
    f.check(row.get("decision") == "failed" and marker in str(row.get("reason") or ""),
            "the outcome row names the failed turn with the marker", row)
    run = f.json(answers, "/api/team/runs/{id}")
    f.check((run.get("outcome") or {}).get("decision") == "failed",
            "the Team API's run shows the failure", run.get("outcome"))

    no_wires(f, wires, record_property)
    assert f.failed == [], "\n".join(f.failed)


# --- the event door (Architecture's decision-76-event-guard, M1-M4) -----------------------------


def update(kind: str, **fields: Any) -> dict:
    return {"type": "message_update", "assistantMessageEvent": {"type": kind, **fields}}


def fragments(findings: Findings, place: str, value: Any, *secrets: str) -> None:
    """Check every eight-character piece, without retaining or showing a matched piece."""
    text = _text(value)
    for secret in secrets:
        run = secret.removeprefix(token_scan.SHAPE_PREFIX)
        if any(run[i:i + 8] in text for i in range(len(run) - 7)):
            findings.failed.append(f"a token's eight-character piece is in {place}")
            return


class DoorTrace:
    """Spy at the real recorder: every write whose caller is in the Pi lane must have gone
    through event_guard first. Keep method names for bypasses, never values in diagnostics.
    Live chunks are captured only in memory and checked both individually and joined."""

    def __init__(self, monkeypatch):
        from temper_ai.observability.event_recorder import EventRecorder

        self.door = 0
        self.skipped: list[str] = []
        self.chunks: list[dict] = []
        for name in ("record", "update_event", "decide", "broadcast_stream_chunk"):
            through = getattr(EventRecorder, name)
            signature = inspect.signature(through)

            def traced(rec, *args, _name=name, _through=through, _sig=signature, **kwargs):
                frame = sys._getframe(1)
                try:
                    while frame is not None:
                        module = frame.f_globals.get("__name__", "")
                        if module == "temper_ai.pi_agent.event_guard":
                            self.door += 1
                            break
                        if (module.startswith("temper_ai.pi_agent.")
                                or module == "temper_ai.llm.pi_stream"):
                            self.skipped.append(f"{module}:{frame.f_code.co_name}:{_name}")
                            break
                        frame = frame.f_back
                finally:
                    del frame
                if _name == "broadcast_stream_chunk":
                    bound = _sig.bind(rec, *args, **kwargs)
                    bound.apply_defaults()
                    self.chunks.append({k: v for k, v in bound.arguments.items() if k != "self"})
                return _through(rec, *args, **kwargs)

            monkeypatch.setattr(EventRecorder, name, traced)

    def check(self, findings: Findings, *secrets: str) -> None:
        findings.check(self.door > 0, "the recorder spy saw guarded writes")
        findings.check(not self.skipped, "no Pi write bypasses the door", self.skipped)
        joined = defaultdict(str)
        for chunk in self.chunks:
            key = (chunk["agent_id"], chunk.get("call_id"), chunk["chunk_type"])
            findings.clean("a live chunk", chunk)
            fragments(findings, "a live chunk", chunk["content"], *secrets)
            if chunk["chunk_type"] != "tool_progress":
                joined[key] += chunk["content"]
        for key, text in joined.items():
            findings.clean(f"joined {key[-1]} chunks", text)
            fragments(findings, f"joined {key[-1]} chunks", text, *secrets)


def door_events(token: str, own: str) -> list[dict]:
    """Scripted raw Pi events: text, thinking, an argument key, a raw tool name, progress and
    a file read. The final member answer is clean; these are earlier calls in that turn."""
    text = f"said {token} with {own} end"
    thought = f"thought {token} end"
    raw_name = f"read {token}"
    args = {token: "argument-key", "path": "note.txt"}
    msg = sup.assistant(text, stop="toolUse")
    msg["content"] += [{"type": "thinking", "thinking": thought},
                       {"type": "toolCall", "id": "door_read", "name": raw_name,
                        "arguments": args}]
    events = [sup.said(msg)[0], update("text_start")]
    events += [update("text_delta", delta=piece) for piece in (text[:17], text[17:])]
    events += [update("text_end"), update("thinking_start")]
    events += [update("thinking_delta", delta=piece) for piece in (thought[:19], thought[19:])]
    events += [update("thinking_end"), update("toolcall_start", toolName=raw_name),
               update("toolcall_end", toolCall={"id": "door_read", "arguments": args}),
               {"type": "message_end", "message": msg},
               {"type": "tool_execution_start", "toolCallId": "door_read",
                "toolName": raw_name, "args": args}]
    for snapshot_text in ("progress " + token[:22], f"progress {token} done",
                          "padding " + "x" * 50 + " " + token + "Q" * 5000):
        events.append({"type": "tool_execution_update", "toolCallId": "door_read",
                       "partialResult": {"content": [{"type": "text", "text": snapshot_text}]}})
    events.append({"type": "tool_execution_end", "toolCallId": "door_read",
                   "toolName": raw_name, "result": {"content": [
                       {"type": "text", "text": f"read {token} and {own} end"}]},
                   "isError": False})
    return events


class DoorBox(ts.TeamFakeBox):
    def _model_turn(self, rid, message, ok):
        team = self.spec.team
        member = team.binding.member if team is not None else None
        actions = ts.SCRIPTS[member][0] if member is not None and ts.SCRIPTS[member] else []
        events = [e for action in actions for e in action.get("pi", [])]
        out = super()._model_turn(rid, message, ok)
        return [out[0], *events, *out[1:]]


# --- d, the real team path and every event door -----------------------------------------------


def test_d_every_team_event_and_live_chunk_leaves_through_the_guard(
        api, wires, monkeypatch, record_property):
    token, own = planted("f"), own_token("f")
    runs.script(api.led, ["done"])
    ts.SCRIPTS["design"][0].insert(0, {"pi": door_events(token, own)})
    with_hand_off(own)
    trace, recorders = DoorTrace(monkeypatch), []

    def runner(cfg, req, ledger):
        recorders.append(req.recorder)
        return turn_mod.run_turn(cfg, req, ledger, box_factory=DoorBox)

    monkeypatch.setattr(Team, "turn_runner", runner)
    eid = team_api.start_trial(api, team_api.body(api))["execution_id"]
    ended = pw.wait_ended(eid, 1)
    f = Findings(token, own)
    f.check(ended[-1]["status"] == "completed", "the door scenario completed")
    f.everywhere(api, eid)
    f.check(bool(recorders) and all(isinstance(r, GuardedRecorder) for r in recorders),
            "run_team_node and Team hand run_turn a guarded recorder")
    trace.check(f, token, own)
    calls = [e["data"] for e in sup.events(eid, event_type="llm.call.completed")]
    f.check(any(token_scan.WITHHELD in (c.get("response_content") or "")
                and REDACTED in (c.get("response_content") or "")
                and token_scan.WITHHELD in (c.get("reasoning") or "") for c in calls),
            "the completed call's text and reasoning are withheld")
    tools = [e["data"] for e in sup.events(eid, event_type="tool.call.started")]
    f.check(any(t.get("raw_tool_name") == "read " + token_scan.WITHHELD
                and (t.get("input_params") or {}).get(token_scan.WITHHELD) == "argument-key"
                for t in tools), "the raw tool name and argument key are withheld")
    tools = [e["data"] for e in sup.events(eid, event_type="tool.call.completed")]
    f.check(any(token_scan.WITHHELD in (t.get("output") or "")
                and REDACTED in (t.get("output") or "") for t in tools),
            "the completed file read is withheld")
    progress = [c["content"] for c in trace.chunks if c["chunk_type"] == "tool_progress"]
    f.check(progress == ["progress ", "progress " + token_scan.WITHHELD + " done",
                         "padding " + "x" * 50 + " " + token_scan.WITHHELD],
            "partial, middle and over-cap progress snapshots are safe")
    no_wires(f, wires, record_property)
    assert f.failed == [], "\n".join(f.failed)


# --- e, run_turn refuses the final answer and guards its end ---------------------------------


def test_e_run_turn_guards_the_file_read_and_refuses_the_answer(
        tmp_path, monkeypatch, wires, record_property):
    token, own = planted("g"), own_token("g")
    rec, led = turns.Recorder(), turns.Ledger()
    mappers = []

    def mapper(*args, **kwargs):
        got = PiEventMapper(*args, **kwargs)
        mappers.append(got)
        return got

    def plant(box):
        box.redactor.add(own)
        token_scan.remember(own)
        (Path(box.spec.participant_dir) / "workspace" / "note.txt").write_text(
            f"{token} is the first word.")

    monkeypatch.setattr(turn_mod, "PiEventMapper", mapper)
    monkeypatch.setattr(sup.FakeBox, "on_prompt", plant)
    report = turn_mod.run_turn(sup.box_config(tmp_path / "box"), turns._req(tmp_path, rec),
                               led, box_factory=sup.FakeBox)
    f = Findings(token, own)
    f.check(report.state == "failed" and report.output == "", "the answer is refused whole")
    f.check(report.outcome is not None and report.outcome.output == ""
            and SHAPE in (report.error or ""), "the refusal names the shape rule")
    f.clean("run_turn's report", vars(report))
    f.clean("run_turn's events and chunks", [rec.events, rec.chunks])
    fragments(f, "run_turn's joined chunks", "".join(c["content"] for c in rec.chunks), token)
    f.check(len(mappers) == 1 and isinstance(mappers[0]._rec.inner, GuardedRecorder)
            and mappers[0]._rec.inner.inner is rec, "run_turn guards ChunkSink's recorder")
    f.check(any(e["type"].endswith("tool.call.completed")
                and token_scan.WITHHELD in (e["data"].get("output") or "") for e in rec.events),
            "the file read is withheld")
    f.check(any(e["type"].endswith("llm.call.completed")
                and token_scan.WITHHELD in (e["data"].get("response_content") or "")
                for e in rec.events), "the completed model call is withheld")
    f.check(any(e["type"].endswith("agent.failed") and e["data"].get("output") == ""
                for e in rec.events), "the agent end keeps no refused output")
    no_wires(f, wires, record_property)
    assert f.failed == [], "\n".join(f.failed)


# --- f, PiHost's single-step path (including its owner wait) ----------------------------------


def test_f_the_single_step_path_hands_on_only_a_guarded_recorder(
        pw_run, monkeypatch, wires, record_property):
    from temper_ai.database import get_database
    from temper_ai.pi_agent.host import PiHost

    token, own = planted("h"), own_token("h")
    trace, recorders = DoorTrace(monkeypatch), []
    through = PiHost.turn_runner

    def runner(cfg, req, ledger):
        recorders.append(req.recorder)
        return through(cfg, req, ledger)

    def plant(box):
        box.redactor.add(own)
        token_scan.remember(own)
        (Path(box.spec.participant_dir) / "workspace" / "note.txt").write_text(
            f"first {token} end")

    monkeypatch.setattr(PiHost, "turn_runner", runner)
    monkeypatch.setattr(sup.FakeBox, "on_prompt", plant)
    eid = sup.start(pw_run.client, "pi_talk", pw_run.ws)
    pw.wait_parked(pw_run.state, eid, 1)
    sup.open_wait(eid, "owner")
    ended = pw.wait_ended(eid, pw.finish_pi(pw_run.client, eid))
    f = Findings(token, own)
    f.check(ended[-1]["status"] == "completed", "the single-step run completed")
    f.check(f.stored(get_database().engine, eid) > 0, "the database scan saw the single-step run")
    f.check(f.logged(eid) > 0, "the single-step run has an event log")
    answers = f.served(pw_run.client, eid, [])
    f.json(answers, "/api/workflows/{id}")
    f.check(bool(recorders) and all(isinstance(r, GuardedRecorder) for r in recorders),
            "PiHost hands run_turn a guarded recorder")
    trace.check(f, token, own)
    tools = [e["data"] for e in sup.events(eid, event_type="tool.call.completed")]
    f.check(any(token_scan.WITHHELD in (t.get("output") or "") for t in tools),
            "the single-step file read is withheld")
    no_wires(f, wires, record_property)
    assert f.failed == [], "\n".join(f.failed)


# --- g-h, the injected stream rule, before any chunk reaches the door -------------------------


class ChunkRecorder(turns.Recorder):
    def broadcast_stream_chunk(self, agent_id, content, chunk_type="content", done=False,
                               call_id=None, seq=None):
        self.chunks.append({"content": content, "type": chunk_type, "call_id": call_id})


def stream_mapper(rec, redactor):
    return PiEventMapper(rec, execution_id="r01-stream", agent_event_id="r01-agent",
                         agent_name="r01", session_id="r01-session", redactor=redactor)


def test_g_every_two_and_three_delta_split_keeps_the_whole_token_run_hidden(
        wires, record_property):
    token, own = planted("i"), own_token("i")
    text = f"say {token} then {own} end"
    expected = f"say {token_scan.WITHHELD} then {REDACTED} end"
    f = Findings(token, own)
    count = 0
    for n in (1, 2):
        for cuts in combinations(range(1, len(text)), n):
            bounds = (0, *cuts, len(text))
            pieces = tuple(text[a:b] for a, b in zip(bounds, bounds[1:], strict=False))
            rec = ChunkRecorder()
            mapper = stream_mapper(rec, Redactor(secrets=[own], guard=TOKEN_GUARD))
            mapper.handle_all(sup.said(sup.assistant(text), pieces))
            joined = "".join(c["content"] for c in rec.chunks if c["type"] == "content")
            if joined != expected:
                f.failed.append(f"stream split {cuts} did not withhold the whole run")
            fragments(f, f"stream split {cuts}", joined, token, own)
            direct = ShapeStream()
            want = f"say {token_scan.WITHHELD} then {own} end"
            if "".join(direct.feed(p) for p in pieces) + direct.flush() != want:
                f.failed.append(f"shape-only split {cuts} differs")
            count += 1
    stream = ShapeStream()
    f.check(stream.feed(token) == "" and stream.flush() == token_scan.WITHHELD,
            "a shape at the very end is held until flush")
    record_property("two_and_three_delta_splits", count)
    no_wires(f, wires, record_property)
    assert f.failed == [], "\n".join(f.failed)


def test_h_progress_snapshots_and_the_bounded_hold_swallow_the_rest_of_a_token(
        wires, record_property):
    token = planted("j")
    f, rec = Findings(token), ChunkRecorder()
    mapper = stream_mapper(rec, Redactor(guard=TOKEN_GUARD))
    mapper.handle({"type": "tool_execution_start", "toolCallId": "progress", "toolName": "read"})
    snapshots = ("progress " + token[:22], f"progress {token} done",
                 "x" * 50 + " " + token + "Q" * (STREAM_HOLD_CAP + 1000))
    for text in snapshots:
        mapper.handle({"type": "tool_execution_update", "toolCallId": "progress",
                       "partialResult": {"content": [{"type": "text", "text": text}]}})
    f.check([c["content"] for c in rec.chunks] == ["progress ",
            "progress " + token_scan.WITHHELD + " done", "x" * 50 + " " + token_scan.WITHHELD],
            "progress holds a partial run and withholds before its display cut")
    for chunk in rec.chunks:
        fragments(f, "a progress snapshot", chunk["content"], token)
    long = token + "Q" * (STREAM_HOLD_CAP + 1000)
    stream = ShapeStream()
    seen = "".join(stream.feed(long[i:i + 97]) for i in range(0, len(long), 97))
    f.check(seen == token_scan.WITHHELD, "the capped hold emits exactly one marker")
    f.check(stream.feed("Q" * 10000) == "", "the withheld token's rest is swallowed")
    f.check(stream.feed(" end") + stream.flush() == " end", "words after the token survive")
    # A long look-alike that cannot match any rule is not a login token. A later real prefix
    # in the same run must still be held; releasing the look-alike must not lose that prefix.
    lookalike = token_scan.SHAPE_PREFIX + "z" * (STREAM_HOLD_CAP + 1000)
    stream = ShapeStream()
    seen = "".join(stream.feed(lookalike[i:i + 97]) for i in range(0, len(lookalike), 97))
    f.check(seen + stream.flush() == lookalike, "a non-matching long look-alike stays unchanged")
    stream = ShapeStream()
    long = lookalike + token + " end"
    seen = "".join(stream.feed(long[i:i + 97]) for i in range(0, len(long), 97)) + stream.flush()
    f.check(seen == lookalike + token_scan.WITHHELD + " end",
            "a later real prefix in a long non-matching run is still withheld")
    no_wires(f, wires, record_property)
    assert f.failed == [], "\n".join(f.failed)


# --- i-j, end cuts, the team's own records, explicit forwarding and unchanged defaults ----------


def test_i_agent_output_is_withheld_before_cutting_and_team_records_use_the_door(
        tmp_path, wires, record_property):
    token = planted("k")
    f, rec = Findings(token), ChunkRecorder()
    mapper = stream_mapper(rec, Redactor(guard=TOKEN_GUARD))
    text = "y" * 4990 + " " + token
    mapper.handle_all([*sup.said(sup.assistant(text)), sup.SETTLED])
    outcome = mapper.finish()
    f.check(outcome.status == "completed" and outcome.output == text,
            "the mapper retains the answer for the caller's whole-answer refusal")
    record_outcome(guarded(rec), mapper, outcome)
    end = [e for e in rec.events if e["type"].endswith("agent.completed")]
    f.check(len(end) == 1, "exactly one agent end")
    fragments(f, "the cut agent output", end, token)
    f.clean("the cut agent output", end)
    if end:
        f.check(end[0]["data"].get("output_length") == len(text),
                "the agent end still counts the original answer's length")

    class TeamRecorder(ChunkRecorder):
        def event_status(self, eid):
            return "running"

        def update_event(self, eid, status=None, data=None):
            self.updated = {"id": eid, "status": status, "data": data}

    team_rec = TeamRecorder()
    team = Team(object(), sup.box_config(tmp_path / "box"), run_id="r01-team",
                host_path="trial", members=[], team_settings=None, recorder=team_rec,
                attempt_id="r01-attempt")
    f.check(isinstance(team.recorder, GuardedRecorder) and team.recorder.inner is team_rec,
            "the Team constructor always guards its recorder")
    team._close_turn_event({"agent_event_id": "r01-start", "member": "design"},
                           "stopped because " + token)
    f.check(len(team_rec.events) == 1 and team_rec.events[0]["data"].get("error")
            == "stopped because " + token_scan.WITHHELD, "the team's own failure is withheld")
    f.check(team_rec.updated["status"] == "failed", "the team's own start event is closed")
    f.clean("the team's own records", [team_rec.events, team_rec.updated])
    no_wires(f, wires, record_property)
    assert f.failed == [], "\n".join(f.failed)


def test_j_forwarding_is_explicit_contexts_are_copied_and_non_pi_defaults_do_not_change(
        wires, record_property):
    token, own = planted("l"), own_token("l")
    f, sent, answer = Findings(token, own), [], object()

    class Recorder:
        def record(self, *args, **kwargs):
            sent.append(("record", args, kwargs))
            return answer

        def broadcast_stream_chunk(self, *args, **kwargs):
            sent.append(("chunk", args, kwargs))
            return answer

        def update_event(self, *args, **kwargs):
            sent.append(("update", args, kwargs))
            return answer

        def decide(self, *args, **kwargs):
            sent.append(("decide", args, kwargs))
            return answer

        def event_status(self, *args, **kwargs):
            return answer

        event_data = event_status
        gate_events = event_status

    rec, data = Recorder(), {token: "first", token + "Q": "second", "nested": [(token,)]}
    door = guarded(rec)
    f.check(door.record("started", data, "parent", execution_id="run") is answer,
            "record forwards positional and keyword arguments and its result")
    f.check(door.broadcast_stream_chunk("agent", token, "content", True, call_id="call") is answer,
            "chunk forwards positional and keyword arguments and its result")
    f.check(door.update_event("event", "failed", data=data) is answer,
            "update forwards positional and keyword arguments and its result")
    f.check(door.decide("event", expect="running", status="failed", data=data) is answer,
            "decide forwards keyword arguments and its result")
    f.check([s[0] for s in sent] == ["record", "chunk", "update", "decide"],
            "every write is forwarded by name")
    expected = {token_scan.WITHHELD: "first", token_scan.WITHHELD + " (2)": "second",
                "nested": [(token_scan.WITHHELD,)]}
    f.check(sent[0][1] == ("started", expected, "parent")
            and sent[0][2] == {"execution_id": "run"}, "record withholds keys without losing values")
    f.check(sent[1][1] == ("agent", token_scan.WITHHELD, "content", True)
            and sent[1][2] == {"call_id": "call"}, "chunks are withheld before forwarding")
    f.check(sent[2][1] == ("event", "failed") and sent[2][2] == {"data": expected},
            "update withholds its data")
    f.check(sent[3][1] == ("event",) and sent[3][2]
            == {"expect": "running", "status": "failed", "data": expected},
            "decide withholds its data")
    f.clean("all forwarded writes", sent)
    f.check(door.event_status("event") is answer and door.event_data("event") is answer
            and door.gate_events(execution_id="run") is answer, "reads are passed through")
    f.check(getattr(guarded(object()), "decide", None) is None
            and getattr(guarded(object()), "event_status", None) is None,
            "missing recorder methods remain missing")
    f.check("__getattr__" not in vars(GuardedRecorder), "no blind recorder passthrough")
    f.check(guarded(door) is door and guarded(None) is None, "guarding is idempotent")
    for ctx in (SimpleNamespace(event_recorder=rec, other=answer),
                ExecutionContext("run", "workflow", "node", "agent", rec, None)):
        clone = guarded_context(ctx)
        f.check(clone is not ctx and ctx.event_recorder is rec
                and isinstance(clone.event_recorder, GuardedRecorder)
                and clone.event_recorder.inner is rec, "the caller's context stays unchanged")
        f.check(guarded_context(clone) is clone, "an already-guarded context stays unchanged")
    empty = SimpleNamespace(event_recorder=None)
    f.check(guarded_context(empty) is empty, "a context without a recorder stays unchanged")
    clean = {"a": ["words", ("more",)], "b": "plain"}
    f.check(token_scan.withhold_obj(clean) is clean, "unchanged objects keep their identity")
    default = Redactor(secrets=[own])
    f.check(default.text(token) == token and default.text(own) == REDACTED,
            "a Redactor without a guard behaves as before")
    stream = default.stream()
    f.check(stream.feed(token[:15]) + stream.feed(token[15:]) + stream.flush() == token,
            "an unguarded stream behaves as before")
    root = Path(turn_mod.__file__).resolve().parents[1]
    imports = []
    for path in sorted((root / "llm").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any("pi_agent" in name.split(".") for name in names):
                imports.append(str(path.relative_to(root)))
    f.check(not imports, "the llm layer imports no Pi lane code", imports)
    tags = {"anthropic_oauth_access_token": "oat", "anthropic_oauth_refresh_token": "ort",
            "anthropic_api_key": "api"}
    f.check(set(tags) == set(token_scan.SHAPES), "the stream's rule-shape check covers every rule")
    for name, pattern in token_scan.SHAPES.items():
        sample = token_scan.SHAPE_PREFIX + tags[name] + "01-" + "K" * 30
        f.check(pattern.pattern.startswith(token_scan.SHAPE_PREFIX)
                and pattern.fullmatch(sample) is not None
                and all(ch in token_scan.RUN_CHARS for ch in sample)
                and pattern.search(sample + "Q" * 50 + " ").group() == sample + "Q" * 50,
                f"{name} starts at the shared prefix and reaches the end of its run")
    no_wires(f, wires, record_property)
    assert f.failed == [], "\n".join(f.failed)
