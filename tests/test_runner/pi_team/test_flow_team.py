"""Free-flowing teams (FLOW): one combined happy-path test of the whole feature --
model-free, every member a scripted Pi.

The leader gets the goal, splits it and sends each member its part; the members wake on that
message and work AT THE SAME TIME, each in its own copy, sharing into the team's one shared
version. A member nobody gives work stays idle. One worker asks the owner and only that
worker waits, then takes the answer on its next turn. At $100 of spend the team checks in
with the owner; nothing new starts until he answers. The leader calls done once every part is shared;
Temper counts it and records the shared version as the team's result.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from temper_ai.api import team_routes as api
from temper_ai.pi_agent import flow_view, team_leader
from temper_ai.pi_agent.box import WorkerBox
from temper_ai.pi_agent.ledger import waits
from temper_ai.pi_agent.team_flow import FlowTeam
from temper_ai.pi_agent.team_leader import LeaderTeam
from temper_ai.pi_agent.team_view import TeamReader
from temper_ai.shared.clock import utcnow
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts

NAMES = ("lead", "ana", "ben", "cal", "spare")
WORKERS = ("ana", "ben", "cal")
#: What each turn costs: the leader's first turn $5, every worker turn $25, the rest nothing.
#: 5 + 6 x 25 = $155, so the team checks in once, at $100.
COST = {("lead", 1): 5.0, **{(w, n): 25.0 for w in WORKERS for n in (1, 2)}}
# Ana's second turn asks the owner; its third turn finishes the part at no extra cost.


def lead_turn() -> list[dict]:
    prompts = ts.PROMPTS["lead"]
    if len(prompts) == 1:  # the goal: split it, one part each; spare has nothing to do
        return [*(ts.send(w, f"Write {w}.md and {w}-2.md, then share.", "work_request")
                  for w in WORKERS),
                ls.op("idle", note="waiting for the parts")]
    heard = {h["id"] for p in prompts for h in ts.headers(p)
             if h["from"] in {f'member "{w}"' for w in WORKERS}}
    if len(heard) >= 2 * len(WORKERS):  # every part done and shared (reply + note each)
        return [ls.op("done", summary="Every part is in the shared version.")]
    return [ls.op("idle", note="waiting for the rest")]


def worker_turns(name: str, barrier: threading.Barrier) -> list[list[dict]]:
    def together(_box: Any, _message: str) -> None:
        barrier.wait()  # breaks (and fails the turn) unless all three run at once
    first = [ls.write(f"{name}.md", f"# {name}\n"), {"call": together},
             ls.op("share", note=f"{name} part 1"),
             ts.reply_to_first("part 1 shared", sender="lead")]
    last = [ls.write(f"{name}-2.md", f"# {name} 2\n"), ls.op("share", note=f"{name} part 2"),
            ts.send("lead", f"{name}: part 2 shared", "info"), ls.op("idle")]
    if name == "ana":
        def owner_answer_seen(_box: Any, message: str) -> None:
            assert any(h["kind"] == "owner_reply" for h in ts.headers(message))
        return [first, [ls.op("ask_owner", question="May I finish the second part?")],
                [{"call": owner_answer_seen}, *last]]
    return [first, last]


@pytest.fixture
def costs(monkeypatch):
    starts: list[dict] = []

    def runner(box: Any, req: Any, ledger: Any) -> Any:
        # The real mount builder is pure here: no socket, container, or model is started.
        worker = WorkerBox(box, req.spec, None)
        worker.sock_dir = box.sockets / req.turn["turn_id"]
        starts.append({"member": req.agent_name, "turn_id": req.turn["turn_id"],
                       "mounts": worker.mounts()})
        cost = COST.get((req.agent_name, req.turn["turn_no"]), 0.0)
        on_usage = req.on_usage
        if on_usage is not None:
            def known_usage(usage: dict[str, int | float]) -> None:
                on_usage({**usage, "cost_usd": cost})
            req.on_usage = known_usage  # synthetic cost through the live receipt seam too
        report = LeaderTeam.turn_runner(box, req, ledger)
        usage = (report.worker or {}).setdefault("usage", {})
        usage["cost_usd"] = cost
        return report
    monkeypatch.setattr(FlowTeam, "turn_runner", staticmethod(runner))
    return starts


def test_free_flowing_team_works_at_once_shares_one_version_checks_in_and_finishes(
        led, box, run_id, tmp_path, monkeypatch, costs):
    # Both the member's question and the check-in get an answer; either may come first.
    owner = ls.Owner(led, "continue", "continue").install(monkeypatch)
    src = ls.project(tmp_path / "proj")
    barrier = threading.Barrier(len(WORKERS), timeout=30)
    ts.SCRIPTS["lead"] = ls.Turns(lead_turn)
    for w in WORKERS:
        ts.SCRIPTS[w] = worker_turns(w, barrier)
    team = ls.open_flow(led, box, run_id=run_id, source=src, names=NAMES,
                        settings={**ls.FLOW_SETTINGS, "max_parallel": 5})
    started = utcnow()
    view_run = api.TeamRun(run_id, {
        "trial_id": "fixture-main", "execution_id": run_id, "workflow": "team_test",
        "goal": ls.GOAL, "created_at": started, "created_by": "owner",
        "request_id": "fixture-main", "trial": {
            "kind": "flow", "leader": "lead", "communication": "all",
            "pause_every_usd": 100.0, "max_parallel": None,
            "members": [{"name": n, "role": ts.member(n).config["role"],
                         "leader": n == "lead"} for n in NAMES],
        }}, None, ts.HOST, "running")

    def asked(_run_id):
        return [{"id": f"fixture-gate-{i}", "data": {"name": w["gate_name"]}}
                for i, w in enumerate(led.open_waits(run_id, ts.HOST))
                if w["kind"] != "closing"]

    monkeypatch.setattr(api, "_ledger", lambda: led)
    monkeypatch.setattr(api, "_team_run", lambda _ledger, _id: view_run)
    monkeypatch.setattr(api, "_owners", lambda: ("owner",))
    monkeypatch.setattr(api, "_caller_actions", lambda _id: [])
    monkeypatch.setattr(api, "_account_view", lambda _id: None)
    monkeypatch.setattr("temper_ai.api.routes._waiting_gate_events", asked)
    at_pause: list[dict] = []
    ask_owner_for_wait = team_leader.ask_owner_for_wait

    def observe_question(*args, **kw):
        at_pause.append(api.team_run(run_id))
        return ask_owner_for_wait(*args, **kw)

    monkeypatch.setattr(team_leader, "ask_owner_for_wait", observe_question)
    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    snap = ts.rows(led, run_id)
    member_of = {p["participant_id"]: p["member"] for p in snap["participants"]}
    turns = [t for t in snap["turns"] if t["state"] == "completed"]
    by = {name: sorted((t for t in turns if member_of[t["participant_id"]] == name),
                       key=lambda t: t["turn_no"]) for name in NAMES}
    # leader first: only the leader was given the goal; the others waited for its message
    assert ls.GOAL in ts.PROMPTS["lead"][0]
    assert all(ls.GOAL not in p for w in NAMES[1:] for p in ts.PROMPTS[w])
    assert by["lead"][0]["started_at"] <= min(t["started_at"] for t in turns)
    # the three workers' first turns ran at the same time (the barrier held all three)
    firsts = [by[w][0] for w in WORKERS]
    assert max(t["started_at"] for t in firsts) < min(t["ended_at"] for t in firsts)
    assert {w: len(by[w]) for w in WORKERS} == {"ana": 3, "ben": 2, "cal": 2}
    assert by["spare"] == []  # never messaged: never takes a turn, not even an empty one
    spare = next(p for p in snap["participants"] if p["member"] == "spare")
    assert spare["idle_reason"] == "start" and spare["idle_note"] is None
    # One /w, the member's own, no shared or other member's folder, and no overlapping writer.
    for start in costs:
        mine = str(team._pdir(team._member_rows()[start["member"]]).resolve())
        assert [(s, t) for s, t, writable in start["mounts"] if writable] == [(mine, "/w")]
        others = [team._pdir(p).resolve() for n, p in team._member_rows().items()
                  if n != start["member"]]
        guarded = [*others, team.shared.path.resolve()]
        assert all(not Path(s).is_relative_to(p) and not p.is_relative_to(Path(s))
                   for s, _t, _w in start["mounts"] for p in guarded)
    sockets = [s for start in costs for s, t, _w in start["mounts"] if t == "/box-sock"]
    assert len(sockets) == len(costs) == len(set(sockets))
    assert all(not Path(a).is_relative_to(Path(b)) for a in sockets for b in sockets if a != b)
    for member_turns in by.values():
        assert all(before["ended_at"] <= after["started_at"]
                   for before, after in zip(member_turns, member_turns[1:], strict=False))
    # one shared version holds every part; done records it
    head = team.shared.head()
    files = ls.git(team.shared.path, "ls-tree", "-r", "--name-only", head.commit).split()
    for w in WORKERS:
        assert {f"{w}.md", f"{w}-2.md"} <= set(files)
    record = outcome.record
    assert record["decision"] == "done" and record["kind"] == "flow"
    assert record["version"]["commit"] == head.commit
    assert {f"{w}.md" for w in WORKERS} <= set(record["version"]["files"])
    assert {s["who"] for s in record["shares"]} >= set(WORKERS)
    assert record["summary"] == "Every part is in the shared version."
    # the check-in: once, at $100; nothing new started while it waited for the owner
    (pause,) = [w for w in ls.table(led, waits, run_id) if w["kind"] == "pause"]
    assert pause["subject"]["at_usd"] == 100.0 and pause["decision"]["answer"] == "continue"
    assert not [t for t in snap["turns"]
                if pause["opened_at"] < t["started_at"] < pause["decided_at"]]
    asked = {a["wait_id"]: a for a in owner.asked}
    assert sorted(a["header"] for a in asked.values()) == ["owner", "pause-at-$100"]
    (question,) = [w for w in ls.table(led, waits, run_id) if w["kind"] == "owner"]
    assert question["subject"]["member"] == "ana" and question["decision"]["answer"] == "given"
    assert by["ana"][1]["turn_id"] == question["subject"]["turn_id"]
    assert by["ana"][2]["started_at"] >= question["decided_at"]
    assert not [w for w in ls.table(led, waits, run_id)
                if w["kind"] == "owner" and (w["subject"] or {}).get("participant_id")
                != question["subject"]["participant_id"]]
    # every turn's spend counts, and the team's total is their sum
    assert team.usage()["cost_usd"] == pytest.approx(155.0)
    assert record["cost"]["cost_usd"] == pytest.approx(155.0)
    # what happened, as the Team page reads it
    kinds = {e["kind"] for e in led.events_after(run_id, ts.HOST, limit=1000)}
    assert kinds >= {"turn_start", "turn_end", "message", "wake", "idle", "share", "check_in",
                     "closing", "done", "ended"}
    assert {p["ended_reason"] for p in snap["participants"]} == {"team_done"}
    ts.check_invariants(led, run_id)

    # Design G1-G5: real run/event serializers, using this happy path's actual rows.
    paused = next(r for r in at_pause if r["phase"]["name"] == "check_in")
    seen_at = datetime.fromisoformat(paused["as_of"])
    member_question_open = (datetime.fromisoformat(question["opened_at"]) <= seen_at
                            < datetime.fromisoformat(question["decided_at"]))
    expected_questions = 1 + int(member_question_open)  # check-in, plus Ana if still held
    assert paused["you"]["count"] == expected_questions
    assert len(paused["open_waits"]) == expected_questions
    assert paused["open_waits"][0]["words"] == paused["you"]["first"]["words"]
    assert "\n" not in paused["you"]["first"]["words"]
    assert len(paused["you"]["first"]["words"]) <= 160
    view_run.completed_at = utcnow()
    view_run.run_status = "completed"
    done_outcome = {"decision": "done", "reason": "the team finished its work",
                    "record": record, "at": view_run.completed_at}
    view_run.outcome = done_outcome
    reader = TeamReader(led, run_id, ts.HOST, "lead")
    reply = api.team_run(run_id)
    feed = flow_view.events_view(reader, 0, 1000)
    assert reply["kind"] == "flow" and "round" not in reply and "reviews" not in reply
    assert reply["trial"]["max_parallel"] == len(NAMES)
    assert reply["events_total"] == len(feed["events"])
    assert reply["events_cursor"] == feed["cursor"] > reply["events_total"]
    assert datetime.fromisoformat(reply["as_of"]).utcoffset() == timedelta(0)
    assert datetime.fromisoformat(feed["as_of"]).utcoffset() == timedelta(0)
    assert all(m["last_turn"] is None or "error" in m["last_turn"] for m in reply["members"])
    lead = next(m for m in reply["members"] if m["name"] == "lead")
    assert lead["on"]["kind"] == "message" and lead["on"]["to"] in WORKERS
    # Ended time never grows as as_of advances, including interruption without an outcome.
    for phase in ("done", "stopped", "failed", "interrupted"):
        view_run.outcome = (None if phase == "interrupted" else
                            {**done_outcome, "decision": phase})
        view_run.run_status = "interrupted" if phase == "interrupted" else "completed"
        monkeypatch.setattr(flow_view, "utcnow", lambda: view_run.completed_at + timedelta(seconds=60))
        first = api.team_run(run_id)
        monkeypatch.setattr(flow_view, "utcnow", lambda: view_run.completed_at + timedelta(seconds=120))
        later = api.team_run(run_id)
        assert first["phase"]["name"] == later["phase"]["name"] == phase
        assert later["as_of"] > first["as_of"]
        assert later["elapsed_s"] == first["elapsed_s"]
