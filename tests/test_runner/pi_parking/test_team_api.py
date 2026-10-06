"""The Team page's API (M3 contract, #48) through a real in-process Temper.

Every route is called on the server's own FastAPI app with the Pi switch on, every member is
a scripted Pi (tests/test_runner/pi_team/support.py), and nothing reaches a model or the
network (pi_parking/conftest.py's guard). Proven here:

- a trial starts in one call with its roster, frozen configs and its own row; the same
  request id gives the first result again, a different body under it is refused, and a
  refused start leaves nothing behind;
- team_check writes nothing and gives problems and notes by field (E20); a folder Temper
  can't see gets the note, then the node's own check refuses it before any copy (M4 item 0);
- typed answers reach the team's decision (pause continue/guide/stop, E18's cancelled stop),
  bad answers are refused before anything is recorded, and an answered wait says who
  answered it and from where (E21);
- owner messages are held while a wait is open; the full text of a message reads back;
- team_run reads the outcome from pi_team_outcomes only (A2) and lists owner actions with
  who did them and where from (E15); team_trials carries each run's status (E19);
- #45's guard: off, record and enforce, with the caller's name as ``by``.
"""

from __future__ import annotations

import json
import os
import time

import pytest
import sqlalchemy as sa

from temper_ai.pi_agent.ledger import Ledger, outcomes, requests, trials, waits
from tests.test_pi_agent import support as sup
from tests.test_pi_agent import test_team as tt
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking import test_team_runs as runs
from tests.test_runner.pi_parking.test_team_runs import GOAL, prompts, script
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts

team_on = tt.team_on
tr = runs.tr

THOST = "trial.team"
OWNER_KEY = "tk_owner-test-key-0123456789"
CI_KEY = "tk_ci-test-key-0123456789"
NOT_VISIBLE = "folder checks run when the Pi lane starts the team"


@pytest.fixture
def api(tr, monkeypatch, tmp_path):
    """The Team page's routes on the server's app (added the way the server adds them with
    the switch on), configs loaded from the test database, and the server's named keys."""
    from temper_ai.api import api_keys, caller, run_tokens
    from temper_ai.api.team_routes import include_team_routes
    from temper_ai.server import app
    from temper_ai.stage.loader import GraphLoader

    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps({"keys": {"owner-dashboard": api_keys.hash_key(OWNER_KEY),
                                         "temper-ci": api_keys.hash_key(CI_KEY)}}))
    stamp = time.time() + 3
    os.utime(keys, (stamp, stamp))
    monkeypatch.setenv(api_keys.KEYS_FILE_ENV_VAR, str(keys))
    monkeypatch.setenv("TEMPER_API_GUARD", "off")
    for mod in (api_keys, caller, run_tokens):
        mod._reset_for_tests()
    # These two are keyed by request id, not by run, and the Postgres tier truncates only
    # Temper's own tables: start each test without an earlier test's trials and requests.
    tr.led.ensure()
    with tr.led.engine.begin() as conn:
        conn.execute(sa.delete(requests))
        conn.execute(sa.delete(trials))
    routes, handlers = list(app.router.routes), dict(app.exception_handlers)
    assert include_team_routes(app) is True
    app.middleware_stack = None
    tr.state.graph_loader = GraphLoader(tr.state.config_store)
    yield tr
    app.router.routes[:] = routes
    app.exception_handlers = handlers
    app.middleware_stack = None
    app.openapi_schema = None
    for mod in (api_keys, caller, run_tokens):
        mod._reset_for_tests()


# --- helpers ---------------------------------------------------------------------------------


def body(tr, rid: str = "start-1", **over) -> dict:
    raw = {"request_id": rid, "goal": GOAL, "leader": "design", "pause_after_rounds": 3,
           "members": [{"name": "design", "role": "architecture"},
                       {"name": "frontend", "role": "frontend", "tools": ["Read", "Edit"]},
                       {"name": "qa", "role": "qa", "tools": ["Read", "Grep"]}],
           "project_path": str(tr.ws)}
    raw.update(over)
    return raw


def key(which: str | None) -> dict:
    return {"Authorization": f"Bearer {which}"} if which else {}


def start_trial(tr, raw: dict, *, auth: str | None = None) -> dict:
    r = tr.client.post("/api/team/trials", json=raw, headers=key(auth))
    assert r.status_code == 201, r.text
    return r.json()


def team_run(tr, eid: str) -> dict:
    r = tr.client.get(f"/api/team/runs/{eid}")
    assert r.status_code == 200, r.text
    return r.json()


def parked(tr, eid: str, n: int) -> dict:
    """Attempt ``n`` let go at the team's open wait, and the wait is asked."""
    pw.wait_parked(tr.state, eid, n_attempts=n)

    def asked():
        view = team_run(tr, eid)["open_waits"]
        return view[0] if view and view[0]["asked"] else None
    return sup.wait_for(asked, what=f"an asked wait in {eid}")


def answer(tr, eid: str, wait_id: str, word: str, text: str = "", *, rid: str,
           auth: str | None = None, headers: dict | None = None):
    return tr.client.post(f"/api/team/runs/{eid}/waits/{wait_id}/answer",
                          json={"request_id": rid, "answer": word, "text": text},
                          headers={**key(auth), **(headers or {})})


def message(tr, eid: str, to: str, text: str, *, rid: str, auth: str | None = None):
    return tr.client.post(f"/api/team/runs/{eid}/messages",
                          json={"request_id": rid, "to": to, "body": text}, headers=key(auth))


def trial_configs(tr) -> list[str]:
    from sqlmodel import select

    from temper_ai.config.models import Config
    from temper_ai.database import get_session

    with get_session() as session:
        return sorted(c.name for c in session.exec(select(Config)).all()
                      if c.name.startswith("team-trial-"))


def trial_rows(tr) -> list[dict]:
    from temper_ai.pi_agent import team_trials

    return team_trials.listed(tr.led)


# --- the switch, reads ------------------------------------------------------------------------


def test_the_routes_come_only_with_the_switch(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from temper_ai.api.team_routes import include_team_routes

    monkeypatch.delenv("TEMPER_PI_AGENT", raising=False)
    app = FastAPI()
    assert include_team_routes(app) is False
    assert TestClient(app).get("/api/team/status").status_code == 404


def test_status_gives_the_forms_defaults_limits_folders_and_the_guards_mode(api):
    from temper_ai.pi_agent.route.model import RESERVED_IDS

    got = api.client.get("/api/team/status").json()
    assert got["api_version"] == "1" and got["roles_configured"] is True
    assert got["limits"] == {"goal_max_chars": 20000, "message_max_chars": 20000,
                             "guide_max_chars": 20000, "reply_max_chars": 20000,
                             "nudge_max_chars": 4000, "stop_reason_max_chars": 2000,
                             "name_pattern": "^[a-z][a-z0-9_-]{0,39}$",
                             "reserved_names": sorted(RESERVED_IDS)}
    assert got["tools"]["available"] == ["Read", "Grep", "Glob", "Edit", "Write", "Bash"]
    assert got["tools"]["default"] == ["Read", "Grep", "Glob", "Edit", "Write"]
    # Bash stays off until #45 enforces (E11)
    assert got["tools"]["bash_allowed"] is False
    assert got["tools"]["bash_why"] == "Bash is off until owner-only writes are enforced (#45)"
    assert got["project_roots"] == [str(api.ws)] and got["guard_mode"] == "off"
    assert got["communication"] == {"available": ["all"], "later": ["edges"]}


def test_roles_give_only_the_card_and_leak_nothing_of_a_roles_folder(api):
    r = api.client.get("/api/team/roles")
    got = r.json()
    assert got["configured"] is True and got["problem"] is None
    assert [c["id"] for c in got["roles"]] == sorted(tt.ROLES)
    for card in got["roles"]:
        assert set(card) == {"id", "title", "about", "has_home_chat", "problems"}
        assert card["has_home_chat"] is True
    assert "homeChat" not in r.text and ".jsonl" not in r.text and str(api.tmp) not in r.text
    assert "notebook" not in r.text


# --- check and start --------------------------------------------------------------------------


def test_check_gives_problems_by_field_and_member_and_writes_nothing(api):
    bad = body(api, goal="x" * 20001, leader="nobody",
               members=[{"name": "Design", "role": "architecture"},
                        {"name": "qa", "role": "qa", "tools": ["Read", "Bash"]},
                        {"role": ""}],
               project_path="/elsewhere/app")
    r = api.client.post("/api/team/check", json=bad)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["ok"] is False
    by_text = {p["text"]: p for p in got["problems"]}
    assert by_text["goal: the goal is too long (20001 characters; at most 20000)"]["field"] == "goal"
    assert by_text["members: member 3 needs a role"]["field"] == "members"
    outside = next(p for p in got["problems"] if "/elsewhere/app" in p["text"])
    assert outside == {"field": "project_path",
                       "text": f"project: /elsewhere/app is outside the allowed project folders "
                               f"({api.ws})"}
    bash = next(p for p in got["problems"] if "Bash is off" in p["text"])
    assert bash["member"] == "qa" and bash["text"].endswith(
        "Bash is off until owner-only writes are enforced (#45)")
    named = next(p for p in got["problems"] if "'Design'" in p["text"])
    assert named["member"] == "Design"
    assert any(p["field"] == "leader" for p in got["problems"]), got["problems"]
    assert trial_configs(api) == [] and trial_rows(api) == []


def test_a_good_trial_checks_clean(api):
    got = api.client.post("/api/team/check", json=body(api)).json()
    assert got == {"ok": True, "problems": [], "notes": []}
    assert trial_configs(api) == [] and trial_rows(api) == []


def test_a_trial_starts_in_one_call_with_frozen_configs_and_runs_to_done(api):
    script(api.led, ["done"])
    got = start_trial(api, body(api))
    tid, eid = got["trial_id"], got["execution_id"]
    assert len(tid) == 12 and int(tid, 16) >= 0
    assert got == {"trial_id": tid, "execution_id": eid, "status": "running",
                   "workflow": f"team-trial-{tid}", "repeated": False, "notes": []}
    assert trial_configs(api) == sorted([f"team-trial-{tid}", f"team-trial-{tid}-design",
                                         f"team-trial-{tid}-frontend", f"team-trial-{tid}-qa"])
    assert pw.wait_ended(eid, 1)[-1]["status"] == "completed"

    run = team_run(api, eid)
    assert run["state"] == "done" and run["run_status"] == "completed"
    assert run["trial"]["goal"] == GOAL and run["trial"]["leader"] == "design"
    assert [m["name"] for m in run["trial"]["members"]] == ["design", "frontend", "qa"]
    assert run["trial"]["project"]["source"] == str(api.ws)
    assert run["trial"]["started_by"] == "unknown caller" and run["trial"]["request_id"] == "start-1"
    assert run["outcome"]["decision"] == "done" and run["outcome"]["by"] is None
    assert run["outcome"]["done"]["commit"] and run["outcome"]["done"]["objections"] == []
    assert run["open_waits"] == []
    entries = {e["entry"] for e in run["timeline"]["entries"]}
    assert {"member_turn", "review_round", "decision"} <= entries, entries
    (started,) = run["owner_actions"]
    assert (started["kind"], started["by"], started["source"]) == (
        "start", "unknown caller", "team_page")
    members = {m["name"]: m for m in run["members"]}
    assert members["design"]["leader"] is True and members["design"]["turns"] >= 2
    assert members["qa"]["effective"] == {"model": "unknown", "thinking": "unknown"} or \
        members["qa"]["effective"]["model"]

    # the same request id gives the first result again; nothing new starts
    again = start_trial(api, body(api))
    assert again == {**got, "repeated": True}
    assert len(trial_rows(api)) == 1
    # the same id with a different body is refused
    r = api.client.post("/api/team/trials", json=body(api, goal="something else"))
    assert r.status_code == 409
    assert r.json() == {"reason": "request_id_reused", "message": (
        "this request id was already used for a different request; nothing was done")}

    # E19: the trial list carries the run's status beside the team's decision
    listed = api.client.get("/api/team/trials").json()
    assert listed["total"] == 1
    (item,) = listed["trials"]
    assert (item["trial_id"], item["execution_id"], item["run_status"], item["decision"],
            item["state"]) == (tid, eid, "completed", "done", "done")
    assert item["goal_first_line"] == GOAL and item["started_by"] == "unknown caller"
    assert api.client.get("/api/team/trials?state=paused").json() == {"total": 0, "trials": []}


def test_a2_team_run_reads_the_outcome_from_its_own_row_only(api):
    script(api.led, ["done"])
    eid = start_trial(api, body(api))["execution_id"]
    attempts = pw.wait_ended(eid, 1)
    assert attempts[-1]["data"]["workflow_output"]["decision"] == "done"
    with api.led.engine.begin() as conn:
        conn.execute(outcomes.update().where(outcomes.c.run_id == eid).values(
            reason="read from the outcome row"))
    assert team_run(api, eid)["outcome"]["reason"] == "read from the outcome row"


def test_a_start_without_a_request_id_is_refused(api):
    r = api.client.post("/api/team/trials", json=body(api, request_id=None))
    assert r.status_code == 400
    assert r.json() == {"problem": "the request needs a request_id (any unique text, the same "
                                   "on a retry)"}
    assert trial_rows(api) == []


def test_a_refused_start_leaves_nothing_behind(api):
    r = api.client.post("/api/team/trials", json=body(api, leader="nobody"))
    assert r.status_code == 400
    got = r.json()
    assert got["problems"] and got["notes"] == []
    # {field, member?, text}: member only on a member row's problem
    assert all(set(p) in ({"field", "text"}, {"field", "member", "text"})
               for p in got["problems"]), got["problems"]
    assert trial_configs(api) == [] and trial_rows(api) == []


@pytest.mark.parametrize("how", ["refused", "raised"])
def test_a_start_the_run_start_refuses_or_that_raises_removes_what_it_saved(api, monkeypatch, how):
    from fastapi import HTTPException

    import temper_ai.api.routes as routes

    def refuse(_request, *, execution_id=None):
        if how == "refused":
            raise HTTPException(status_code=400, detail="the run start said no")
        raise RuntimeError("the run start broke")

    monkeypatch.setattr(routes, "_start_run", refuse)
    if how == "refused":
        r = api.client.post("/api/team/trials", json=body(api))
        assert r.status_code == 400
        assert r.json() == {"problems": [{"field": None, "text": "the run start said no"}],
                            "notes": []}
    else:
        with pytest.raises(RuntimeError):
            api.client.post("/api/team/trials", json=body(api))
    assert trial_configs(api) == [] and trial_rows(api) == []


def test_m4_item0_a_folder_temper_cant_see_is_a_note_then_the_node_refuses_it(api, monkeypatch,
                                                                             tmp_path):
    """In the server a folder under a root it can't see gets the lexical check and a note; the
    team node's own check (where the team runs) refuses it before any copy or model call."""
    ls.allow_projects(monkeypatch, tmp_path / "more-settings", str(api.ws), "/srv/unseen/*")
    raw = body(api, project_path="/srv/unseen/app")
    note = {"field": "project_path", "text": NOT_VISIBLE}
    assert api.client.post("/api/team/check", json=raw).json() == {
        "ok": True, "problems": [], "notes": [note]}
    got = start_trial(api, raw)
    assert got["notes"] == [note]
    eid = got["execution_id"]
    assert pw.wait_ended(eid, 1)[-1]["status"] == "failed"
    run = team_run(api, eid)
    problem = "project: /srv/unseen/app isn't reachable inside Temper"
    assert run["outcome"]["decision"] == "didnt_start" and run["state"] == "didnt_start"
    assert run["outcome"]["reason"] == f"the team can't start: {problem}"
    assert run["outcome"]["problems"] == [problem]
    assert prompts() == {"design": 0, "frontend": 0, "qa": 0}
    # the team never opened: a message has nowhere to go
    r = message(api, eid, "design", "hello", rid="m-unseen")
    assert r.status_code == 409 and r.json()["reason"] == "team_ended"


# --- answers and messages ---------------------------------------------------------------------


def test_typed_answers_at_the_pause_messages_and_who_answered(api):
    script(api.led, ["keep_going", "done"])
    eid = start_trial(api, body(api, pause_after_rounds=1))["execution_id"]
    wait = parked(api, eid, 1)
    run = team_run(api, eid)
    assert run["state"] == "paused" and run["round"]["current"] == 1
    assert (wait["kind"], wait["asked"], wait["round"]) == ("pause", True, 1)
    assert wait["event_id"] and wait["question"] and "Reply" not in wait["question"]
    assert wait["reply_hint"] == "Reply 'continue', 'guide: <what to tell design>', or 'stop'."
    assert [a["answer"] for a in wait["answers"]] == ["continue", "guide", "stop"]
    wid = wait["wait_id"]

    # refused before anything is recorded
    refusals = [("maybe", "", "'maybe' is not an answer to this question "
                              "(answers: continue, guide, stop)"),
                ("guide", " ", "'guide' needs the words to pass to design"),
                ("continue", "now", "'continue' takes no words"),
                ("guide", "g" * 20001, "the guidance is too long (20001 characters; at most "
                                       "20000)"),
                ("stop", "s" * 2001, "the reason for stopping is too long (2001 characters; "
                                     "at most 2000)")]
    for i, (word, text, problem) in enumerate(refusals):
        r = answer(api, eid, wid, word, text, rid=f"bad-{i}")
        assert (r.status_code, r.json()) == (400, {"problem": problem})
    assert answer(api, eid, "no-such-wait", "continue", rid="bad-x").json() == {
        "detail": "That question is no longer open"}
    assert [w["state"] for w in ls.table(api.led, waits, eid, THOST)] == ["open"]

    # a message while the wait is open is held, and reads back in full
    r = message(api, eid, "frontend", "please keep the page short", rid="m-1")
    assert r.status_code == 201, r.text
    sent = r.json()
    assert (sent["to"], sent["state"], sent["delivers"], sent["repeated"]) == (
        "frontend", "held", "after_open_wait", False)
    full = api.client.get(f"/api/team/runs/{eid}/messages/{sent['message_id']}").json()
    assert (full["from"], full["to"], full["body"], full["kind"]) == (
        "owner", "frontend", "please keep the page short", "owner_reply")
    assert api.client.get(f"/api/team/runs/{eid}/messages/nope").json() == {
        "detail": "no such message in this run"}
    for rid, to, text, problem in [
            ("m-2", "zed", "hi", "'zed' is not a member of this team (members: design, frontend, qa)"),
            ("m-3", "qa", "   ", "the message is empty"),
            ("m-4", "qa", "x" * 20001, "the message is too long (20001 characters; at most 20000)")]:
        r = message(api, eid, to, text, rid=rid)
        assert (r.status_code, r.json()) == (400, {"problem": problem})
    assert message(api, eid, "frontend", "please keep the page short", rid="m-1").json() == {
        **sent, "repeated": True}
    assert message(api, eid, "qa", "different", rid="m-1").status_code == 409

    # guide: the words reach the leader, and the team carries on
    r = answer(api, eid, wid, "guide", "focus on the tests", rid="a-1", auth=OWNER_KEY)
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["status"], got["wait_id"], got["answer"], got["text"], got["carries_on"],
            got["by"], got["repeated"]) == ("approved", wid, "guide", "focus on the tests", True,
                                            "owner", False)
    assert answer(api, eid, wid, "guide", "focus on the tests", rid="a-1").json() == {
        **got, "repeated": True}
    assert pw.wait_ended(eid, 2)[-1]["status"] == "completed"

    # answered: a second answer says who answered it and from where (E21)
    r = answer(api, eid, wid, "continue", rid="a-2")
    assert r.status_code == 409
    late = r.json()
    assert late["reason"] == "already_answered" and late["answered_by"] == "owner"
    assert late["answered_source"] == "team_page"
    run = team_run(api, eid)
    (answered,) = [e for e in run["timeline"]["entries"] if e["entry"] == "owner_answer"]
    assert (answered["answered_by"], answered["answered_source"], answered["wait_kind"]) == (
        "owner", "team_page", "pause")
    kinds = [(a["kind"], a["by"], a["source"]) for a in run["owner_actions"]]
    assert kinds == [("start", "unknown caller", "team_page"),
                     ("message", "unknown caller", "team_page"),
                     ("answer", "owner", "team_page")]
    guidance = [m for m in ts.rows(api.led, eid, THOST)["messages"] if m["sender_kind"] == "owner"]
    assert {m["to_member"] for m in guidance} == {"frontend", "design"}
    # the team has ended: nothing more is sent
    r = message(api, eid, "qa", "one more thing", rid="m-5")
    assert (r.status_code, r.json()) == (409, {"reason": "team_ended",
                                               "message": "the team has ended; nothing was sent"})


def test_e18_a_stop_answer_with_words_ends_the_trial_cancelled(api):
    script(api.led, ["keep_going", "done"])
    eid = start_trial(api, body(api, pause_after_rounds=1), auth=None)["execution_id"]
    wait = parked(api, eid, 1)
    r = answer(api, eid, wait["wait_id"], "stop", "we have what we need", rid="s-1", auth=CI_KEY)
    assert r.status_code == 200, r.text
    assert r.json()["by"] == "temper-ci"
    assert pw.wait_ended(eid, 2)[-1]["status"] == "cancelled"
    run = team_run(api, eid)
    assert run["run_status"] == "cancelled" and run["state"] == "stopped"
    out = run["outcome"]
    assert (out["decision"], out["reason"], out["owner_words"], out["by"]) == (
        "stopped", "stopped at the pause after round 1", "we have what we need", "temper-ci")
    (item,) = api.client.get("/api/team/trials").json()["trials"]
    assert (item["run_status"], item["decision"], item["state"]) == (
        "cancelled", "stopped", "stopped")


def test_e15_a_cancel_from_the_run_page_is_the_owners_stop_with_its_words(api):
    script(api.led, ["keep_going", "done"])
    eid = start_trial(api, body(api, pause_after_rounds=1))["execution_id"]
    parked(api, eid, 1)
    r = api.client.post(f"/api/runs/{eid}/cancel", json={"reason": "enough for today"},
                        headers={**key(OWNER_KEY), "Origin": "http://testserver"})
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 1)[-1]["status"] == "cancelled"

    def words():
        out = team_run(api, eid)["outcome"]
        return out if out and out.get("owner_words") else None
    out = sup.wait_for(words, what="the cancel's words on the outcome")
    assert (out["decision"], out["reason"], out["owner_words"], out["by"]) == (
        "cancelled", "the run was cancelled", "enough for today", "owner")
    stop = [a for a in team_run(api, eid)["owner_actions"] if a["kind"] == "stop"]
    assert [(a["by"], a["source"]) for a in stop] == [("owner", "run_page")]


def test_e12_a_second_open_wait_is_listed_after_the_asked_one_and_cant_be_answered_yet(api):
    script(api.led, ["keep_going", "done"])
    eid = start_trial(api, body(api, pause_after_rounds=1))["execution_id"]
    first = parked(api, eid, 1)
    second = api.led.open_wait(eid, THOST, "owner",
                               {"member": "frontend", "question": "Which colour?"}, "attempt-x")
    listed = team_run(api, eid)["open_waits"]
    assert [(w["wait_id"], w["asked"], w["kind"]) for w in listed] == [
        (first["wait_id"], True, "pause"), (second["wait_id"], False, "question")]
    assert listed[1]["event_id"] is None
    assert [a["answer"] for a in listed[1]["answers"]] == ["reply"]
    r = answer(api, eid, second["wait_id"], "reply", "blue", rid="q-1")
    assert (r.status_code, r.json()) == (409, {
        "reason": "not_asked_yet",
        "message": "Temper hasn't asked this question yet; answer the one before it first"})
    # let the run end cleanly: no second wait left open behind it
    with api.led.engine.begin() as conn:
        conn.execute(waits.delete().where(waits.c.wait_id == second["wait_id"]))
    assert answer(api, eid, first["wait_id"], "continue", rid="q-2").status_code == 200
    assert pw.wait_ended(eid, 2)[-1]["status"] == "completed"


# --- the guard (#45) --------------------------------------------------------------------------


def test_enforce_refuses_every_team_write_without_a_key_and_reads_stay_open(api, monkeypatch):
    monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
    assert api.client.get("/api/team/status").json()["guard_mode"] == "enforce"
    # with owner-only writes enforced, Bash may be given (E11)
    assert api.client.get("/api/team/status").json()["tools"]["bash_allowed"] is True
    for r in (api.client.post("/api/team/trials", json=body(api)),
              answer(api, "run-x", "w-1", "continue", rid="g-1"),
              message(api, "run-x", "qa", "hi", rid="g-2")):
        assert r.status_code == 401, r.text
        assert r.json()["detail"].startswith("This action needs a key.")
    assert trial_rows(api) == []
    assert api.client.post("/api/team/check", json=body(api)).status_code == 200
    assert api.client.get("/api/team/trials").status_code == 200


@pytest.mark.parametrize("mode", ["record", "enforce"])
def test_a_named_key_starts_a_trial_under_its_name(api, monkeypatch, mode):
    monkeypatch.setenv("TEMPER_API_GUARD", mode)
    script(api.led, ["done"])
    eid = start_trial(api, body(api), auth=CI_KEY)["execution_id"]
    pw.wait_ended(eid, 1)
    run = team_run(api, eid)
    assert run["trial"]["started_by"] == "temper-ci"
    assert [(a["kind"], a["by"]) for a in run["owner_actions"]] == [("start", "temper-ci")]


def test_record_lets_an_unknown_caller_start_and_names_it_so(api, monkeypatch):
    monkeypatch.setenv("TEMPER_API_GUARD", "record")
    script(api.led, ["done"])
    eid = start_trial(api, body(api))["execution_id"]
    pw.wait_ended(eid, 1)
    assert team_run(api, eid)["trial"]["started_by"] == "unknown caller"


def test_a_run_that_is_no_trial_is_not_found(api):
    r = api.client.get("/api/team/runs/not-a-run")
    assert (r.status_code, r.json()) == (404, {"detail": "not a team trial, or no such run"})


def test_ledger_rows_stay_in_the_team_tables(api):
    """The trial's row holds its normalised input; nothing of the body is lost or added."""
    script(api.led, ["done"])
    got = start_trial(api, body(api))
    pw.wait_ended(got["execution_id"], 1)
    (row,) = trial_rows(api)
    assert row["request_id"] == "start-1" and row["execution_id"] == got["execution_id"]
    assert row["member_configs"] == [f"team-trial-{got['trial_id']}-{m}"
                                     for m in ("design", "frontend", "qa")]
    with api.led.engine.connect() as conn:
        (orow,) = conn.execute(sa.select(outcomes).where(
            outcomes.c.run_id == got["execution_id"])).mappings().all()
    assert orow["trial_id"] == got["trial_id"] and orow["host_path"] == THOST
    assert isinstance(api.led, Ledger)
