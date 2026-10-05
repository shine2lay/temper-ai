"""The leader loop (#38): rounds of review, done only on a reviewed version, the pause after
N keep-goings, the stalled wait and recovery waits -- model-free, every member a scripted Pi.

The leader works in its own git copy of the project and asks for a review; Temper commits that
copy and moves each reviewer's copy to the commit, so everyone sees exactly that version. Each
reviewer gives a view; Temper collects them for the leader, who decides. Only Temper records
done. Every owner wait is a ``pi_waits`` row written before the owner is asked, under the row's
own id (the owner here stands in for ``ask_owner`` beneath the real bridge).
"""

from __future__ import annotations

import hashlib

import pytest

from temper_ai.pi_agent.ledger import acts, reviews, waits
from temper_ai.pi_agent.team_leader import TOOLS_NOTE, tools_note
from temper_ai.stage.exceptions import RunParked
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts

README = "# Tiny\n\nPrints hello. Run it with `python app.py`.\n"


def asked_after_their_rows(owner: ls.Owner) -> None:
    """Every owner wait was a pi_waits row, open, before the owner was asked, and the owner was
    asked under that row's own id."""
    for ask in owner.asked:
        row = ask["row"]
        assert row is not None, ("asked before its row was written", ask["wait_id"])
        assert row["wait_id"] == ask["wait_id"] and row["state"] == "open", row
        assert row["gate_name"].endswith(f"~ask-{ask['wait_id']}"), row["gate_name"]


def rounds(led, run_id, decisions, *, last_views="satisfied"):
    """The leader's rounds: write a version and ask for a review; both reviewers give a view
    (changes, or ``last_views`` before a done); the leader decides each in its own turn."""
    lead, builder, checker = [], [], []
    for i, d in enumerate(decisions, 1):
        verdict = last_views if d == "done" else "changes"
        lead.append([ls.write("README.md", f"# Tiny v{i}\n"), ls.request_review(f"draft {i}")])
        builder.append([ls.give_view(led, run_id, verdict, f"builder note {i}")])
        checker.append([ls.give_view(led, run_id, verdict, f"checker note {i}")])
        lead.append([ls.decide(led, run_id, d, f"summary {i}")])
    ts.SCRIPTS["lead"], ts.SCRIPTS["builder"], ts.SCRIPTS["checker"] = lead, builder, checker


def _round_one(led, run_id, *, lead_after=None, views=("satisfied", "satisfied")):
    """The leader writes the README and asks for a review; each reviewer gives a view."""
    ts.SCRIPTS["lead"] = [[ls.write("README.md", README), ls.request_review("first draft")],
                          *(lead_after or [])]
    ts.SCRIPTS["builder"] = [[ls.give_view(led, run_id, views[0], "fine")]]
    ts.SCRIPTS["checker"] = [[ls.give_view(led, run_id, views[1], "fine too")]]


def test_a_round_pins_the_version_collects_the_views_and_done_is_recorded_by_temper(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led).install(monkeypatch)
    src = ls.project(tmp_path / "proj")
    _round_one(led, run_id, lead_after=[[ls.decide(led, run_id, "done", "README written.")]])
    team = ls.open_leader(led, box, run_id=run_id, source=src)

    outcome = team.drive(ls.Context())

    assert outcome.status == "done", outcome.text
    assert owner.asked == []  # nothing needed the owner
    (rev,) = ls.table(led, reviews, run_id)
    assert rev["round"] == 1 and rev["decision"] == "done" and rev["state"] == "decided"
    # the version: the leader's copy, committed by Temper; every reviewer saw exactly it
    sha = rev["commit_sha"]
    assert ls.head(team, "lead") == sha
    for name in ("builder", "checker"):
        assert ls.head(team, name) == sha
        assert (ls.workspace(team, name) / "README.md").read_text() == README
    assert rev["files"]["README.md"] == hashlib.sha256(README.encode()).hexdigest()
    # Temper's record of done: the node's outputs
    record = outcome.record
    assert record["decision"] == "done" and record["round"] == 1 and record["rounds"] == 1
    assert record["version"]["commit"] == sha
    assert record["version"]["files"]["README.md"] == rev["files"]["README.md"]
    assert {m: v["verdict"] for m, v in record["views"].items()} == {
        "builder": "satisfied", "checker": "satisfied"}
    assert record["summary"] == "README written." and record["leader"] == "lead"
    assert set(record["cost"]) >= {"cost_usd", "total_tokens"}
    # one view message per reviewer, sent as that reviewer, delivered to the leader once
    snap = ts.rows(led, run_id)
    view_msgs = [m for m in snap["messages"] if m["kind"] == "view"]
    assert sorted(m["sender"] for m in view_msgs) == ["builder", "checker"]
    assert all(m["state"] == "consumed" and m["delivery_count"] == 1 for m in view_msgs)
    # the team ended done: nothing pending, every member ended team_done
    assert {p["ended_reason"] for p in snap["participants"]} == {"team_done"}
    ts.check_invariants(led, run_id)


def test_each_members_framing_carries_the_tools_note_with_exactly_its_tools(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    _round_one(led, run_id, lead_after=[[ls.decide(led, run_id, "done", "ok")]])
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    assert team.drive(ls.Context()).status == "done"
    # Pi's tool names (Temper's Read is Pi's read), the team's send tool and the review tools
    expected = {"lead": ["decide", "read", "request_review", "send_message"],
                "builder": ["give_view", "read", "send_message"],
                "checker": ["give_view", "read", "send_message"]}
    for name, tools in expected.items():
        assert sorted(team.tools_for(team.members[name])) == tools
        note = tools_note(tools)
        assert note == TOOLS_NOTE.format(tools=", ".join(tools))
        prompts = ts.PROMPTS[name]
        assert prompts, name
        # every turn's prompt has the note, listing exactly this member's tools (never printed)
        assert all(note in p for p in prompts), name
        others = set().union(*expected.values()) - set(tools)
        assert all(f"your tools are: {', '.join(tools)}." in p for p in prompts)
        assert others.isdisjoint(set(note.split(": ", 1)[1].split(". ")[0].split(", ")))


# --- the review tools: who may call them, and once ----------------------------------------------


def test_only_the_leader_asks_and_decides_and_only_an_asked_reviewer_gives_a_view(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led, "stop").install(monkeypatch)
    ts.SCRIPTS["lead"] = [[ls.op("give_view", review_id="r-none", verdict="satisfied", note="x"),
                           ts.send("builder", "please look")]]
    ts.SCRIPTS["builder"] = [[ls.request_review("mine"),
                              ls.op("decide", review_id="r-none", decision="done", summary="x"),
                              ls.op("give_view", review_id="r-none", verdict="changes",
                                    note="no review is open"),
                              ls.op("request_review", member="lead")]]
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "stopped"  # nothing to do: stalled, the owner said stop
    lead, builder = ls.replies("lead"), ls.replies("builder")
    assert lead[0]["ok"] is False and lead[0]["code"] == "not_authorized"
    assert [r.get("code") for r in builder] == [
        "not_authorized", "not_authorized", "invalid_reference", "identity_claim_mismatch"]
    assert ls.table(led, acts, run_id) == [] and ls.table(led, reviews, run_id) == []


def test_a_repeated_call_gets_its_first_answer_and_a_changed_one_is_refused(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    ts.SCRIPTS["lead"] = [[ls.request_review("draft", client_msg_id="call_1"),
                           ls.request_review("draft", client_msg_id="call_1"),
                           ls.request_review("other", client_msg_id="call_1")]]
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    with pytest.raises(RunParked):  # the reviewers have nothing scripted: stalled, asked
        team.drive(ls.Context())
    first, again, changed = ls.replies("lead")
    assert first["ok"] and not first["duplicate"]
    assert again["ok"] and again["duplicate"] and again["act_id"] == first["act_id"]
    assert changed == {"ok": False, "code": "idempotency_conflict",
                       "detail": "that call id was already used for a different call"}
    assert len(ls.table(led, acts, run_id)) == 1 and len(ls.table(led, reviews, run_id)) == 1


# --- done (R2 B9) -------------------------------------------------------------------------------


def test_b9_done_on_a_copy_changed_since_the_review_is_refused_and_counts_as_keep_going(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done", "keep_going"])
    # the deciding turn edits the README after the review, then says done
    ts.SCRIPTS["lead"][1] = [ls.write("README.md", "# changed after the review\n"),
                             ls.decide(led, run_id, "done", "done, I think")]
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    with pytest.raises(RunParked):  # two keep-goings in a row: the pause
        team.drive(ls.Context())
    first, second = ls.table(led, reviews, run_id)
    assert first["decision"] == "done_refused" and second["decision"] == "keep_going"
    assert team.done_review() is None
    refused = [m for m in ts.rows(led, run_id)["messages"]
               if m["kind"] == "notice" and "was refused" in (m["body"] or "")]
    assert len(refused) == 1 and "counts as keep going" in refused[0]["body"]
    (pause,) = owner.asked
    assert pause["header"] == "pause-after-round-2"  # the refused done was a keep-going
    asked_after_their_rows(owner)


def test_b9_done_is_refused_when_work_reached_the_leader_after_its_deciding_turn_began(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done", "done"])
    holder = {}

    def owner_writes(_box, _msg):  # the owner's message reaches the leader mid-turn
        holder["team"].post("lead", "one more thing: add a licence line")

    ts.SCRIPTS["lead"][1] = [{"call": owner_writes}, ls.decide(led, run_id, "done", "done")]
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    holder["team"] = team
    out = team.drive(ls.Context())
    assert out.status == "done", out.text
    first, second = ls.table(led, reviews, run_id)
    assert first["decision"] == "done_refused" and second["decision"] == "done"
    assert out.record["round"] == 2 and out.record["rounds"] == 2


def test_b9_after_done_nothing_more_is_delivered_and_late_messages_are_refused(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["lead"][1] = [ts.send("builder", "thanks!"), ls.decide(led, run_id, "done", "ok")]
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    assert team.drive(ls.Context()).status == "done"
    thanks = [m for m in ts.rows(led, run_id)["messages"] if m["body"] == "thanks!"]
    assert [(m["state"], m["undelivered_reason"]) for m in thanks] == [("undelivered", "team_done")]
    late = team.post("builder", "too late")
    assert late["state"] == "undelivered" and late["undelivered_reason"] == "late"
    assert ts.PROMPTS["builder"] and not any("too late" in p for p in ts.PROMPTS["builder"])
    ts.check_invariants(led, run_id)


# --- the pause after N keep-goings (R2 B10, PARK P1/P2) ----------------------------------------


def test_b10_the_pause_is_a_wait_row_asked_under_its_own_id_and_never_moves_by_itself(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["keep_going", "keep_going"])
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    with pytest.raises(RunParked):
        team.drive(ls.Context())
    (ask,) = owner.asked
    asked_after_their_rows(owner)
    assert ask["row"]["kind"] == "pause" and ask["header"] == "pause-after-round-2"
    assert ask["options"] == ("continue", "guide", "stop")
    turns_before = len(ts.rows(led, run_id)["turns"])
    # a later go with no answer: the same wait is asked again; nothing ran, nothing expired
    again = ls.make_leader(led, box, run_id=run_id, attempt="attempt-2",
                           source=tmp_path / "proj")
    assert again.open({"goal": again.goal}) is None
    with pytest.raises(RunParked):
        again.drive(ls.Context())
    assert [a["wait_id"] for a in owner.asked] == [ask["wait_id"]] * 2
    assert len(ts.rows(led, run_id)["turns"]) == turns_before
    (row,) = ls.table(led, waits, run_id)
    assert row["state"] == "open" and row["decision"] is None


def test_two_pauses_in_one_go_each_ask_the_owner_under_their_own_ids(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led, "continue").install(monkeypatch)
    rounds(led, run_id, ["keep_going"] * 4)
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    with pytest.raises(RunParked):
        team.drive(ls.Context())
    first, second = owner.asked
    asked_after_their_rows(owner)
    assert first["wait_id"] != second["wait_id"]
    assert (first["header"], second["header"]) == ("pause-after-round-2", "pause-after-round-4")
    # continue restarted the count: round 3 alone did not pause
    assert [r["decision"] for r in ls.table(led, reviews, run_id)] == ["keep_going"] * 4
    rows = ls.table(led, waits, run_id)
    assert [(w["state"], (w["decision"] or {}).get("answer")) for w in rows] == [
        ("decided", "continue"), ("open", None)]


def test_b10_guide_reaches_the_leader_and_restarts_the_count(led, box, run_id, tmp_path,
                                                             monkeypatch):
    owner = ls.Owner(led, "guide: say how to run it").install(monkeypatch)
    rounds(led, run_id, ["keep_going", "keep_going", "done"])
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "done" and len(owner.asked) == 1
    guided = [p for p in ts.PROMPTS["lead"] if "say how to run it" in p]
    assert len(guided) == 1
    (row,) = ls.table(led, waits, run_id)
    assert (row["decision"] or {}).get("answer") == "guide"
    ts.check_invariants(led, run_id)


def test_b10_stop_at_the_pause_ends_the_team_stopped_never_done(led, box, run_id, tmp_path,
                                                             monkeypatch):
    ls.Owner(led, "maybe later", "stop").install(monkeypatch)
    rounds(led, run_id, ["keep_going", "keep_going", "done"])
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "stopped" and out.text == "stopped by the owner at the pause after round 2"
    assert team.done_review() is None
    # an answer that is none of the three is never taken as continue: asked again, new id
    first, second = ls.table(led, waits, run_id)
    assert (first["decision"] or {}).get("answer") == "invalid" and first["wait_id"] != second[
        "wait_id"]
    assert {p["ended_reason"] for p in ts.rows(led, run_id)["participants"]} == {"team_stopped"}
    ts.check_invariants(led, run_id)


# --- stalled --------------------------------------------------------------------------------


def test_a_stalled_team_asks_the_owner_and_a_nudge_reaches_the_leader(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led, "nudge: ask for a review").install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["lead"].insert(0, [{"say": "thinking it over"}])
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "done"
    (ask,) = owner.asked
    asked_after_their_rows(owner)
    assert ask["row"]["kind"] == "stalled" and ask["options"] == ("nudge", "stop")
    assert sum("ask for a review" in p for p in ts.PROMPTS["lead"]) == 1


def test_stop_when_stalled_ends_the_team_stopped(led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led, "stop").install(monkeypatch)
    ts.SCRIPTS["lead"] = [[{"say": "nothing to do"}]]
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert (out.status, out.text) == ("stopped", "stopped by the owner when the team had "
                                                 "nothing left to do")


# --- recovery waits (R2 B11) ----------------------------------------------------------------


def test_b11_a_cut_off_turn_pauses_the_team_and_retry_resends_the_same_messages(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led, "retry").install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["builder"].insert(0, [{"die": 1}])
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "done", out.text
    (ask,) = owner.asked
    asked_after_their_rows(owner)
    assert ask["row"]["kind"] == "recovery"
    cut, retried = ts.PROMPTS["builder"]
    assert ts.ids_in(cut) == ts.ids_in(retried) and ts.ids_in(cut)
    assert len(ts.PROMPTS["lead"]) == 2  # the leader's finished turns never ran again
    ts.check_invariants(led, run_id)


def test_b11_stop_at_a_recovery_wait_ends_the_team_red_never_done(led, box, run_id, tmp_path,
                                                                   monkeypatch):
    ls.Owner(led, "stop").install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["builder"].insert(0, [{"die": 1}])
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "stopped"
    assert out.text == "builder turn 1 did not finish and the owner stopped the team"
    assert team.done_review() is None
    ts.check_invariants(led, run_id)


def test_a_view_given_in_a_turn_that_was_cut_off_never_counts(led, box, run_id, tmp_path,
                                                               monkeypatch):
    ls.Owner(led, "retry").install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["builder"] = [[ls.give_view(led, run_id, "satisfied", "cut off"), {"die": 1}],
                             [{"say": "no view this time"}]]
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "done", out.text
    views = [a for a in ls.table(led, acts, run_id) if a["op"] == "give_view"]
    by = {a["member"]: a["state"] for a in views}
    assert by == {"builder": "void", "checker": "carried_out"}
    assert set(out.record["views"]) == {"checker"}
    view_msgs = [m for m in ts.rows(led, run_id)["messages"] if m["kind"] == "view"]
    assert [m["sender"] for m in view_msgs] == ["checker"]
    ts.check_invariants(led, run_id)


def test_calls_of_a_settled_turn_are_carried_out_once_by_the_next_go(
        led, box, run_id, tmp_path, monkeypatch):
    """The process stops between a turn settling and its calls being carried out: the next go
    (a resume) carries them out once, before any other turn."""
    ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    assert team.step().kind == "completed"  # the leader's turn settled; nothing carried out
    assert [a["state"] for a in ls.table(led, acts, run_id)] == ["recorded"]
    again = ls.make_leader(led, box, run_id=run_id, attempt="attempt-2",
                           source=tmp_path / "proj")
    assert again.open({"goal": again.goal}) is None
    out = again.drive(ls.Context())
    assert out.status == "done", out.text
    asks = [m for m in ts.rows(led, run_id)["messages"] if m["kind"] == "review_request"]
    assert sorted(m["to_member"] for m in asks) == ["builder", "checker"]
    assert len(ls.table(led, reviews, run_id)) == 1
    ts.check_invariants(led, run_id)


def test_b12_a_cancelled_run_ends_the_team_and_queued_messages_go_undelivered(
        led, box, run_id, tmp_path, monkeypatch):
    import threading

    ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    cancel = threading.Event()
    ts.SCRIPTS["lead"][0].append({"call": lambda _b, _m: cancel.set()})
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"),
                          cancel_event=cancel)
    out = team.drive(ls.Context(cancel_event=cancel))
    assert out.status == "cancelled"
    snap = ts.rows(led, run_id)
    assert {p["ended_reason"] for p in snap["participants"]} == {"run_cancelled"}
    assert not [m for m in snap["messages"] if m["state"] in ("held", "pending")]
    ts.check_invariants(led, run_id)


# --- failures red, and what each member ran with (R2 B13, B15, B16) ----------------------------


def test_b13_a_reviewer_whose_turn_fails_turns_the_team_red_never_done(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["checker"] = [[{"error": "400 invalid_request_error: the request was refused"}]]
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "failed" and "checker" in out.text, out.text
    assert team.done_review() is None and not out.record  # nothing recorded as done
    assert owner.asked == []  # a provider refusal is red at once, not a question
    assert "done" not in [r["decision"] for r in ls.table(led, reviews, run_id)]
    ts.check_invariants(led, run_id)


def test_b15_each_members_record_names_the_worker_image_and_the_pi_version(
        led, box, run_id, tmp_path, monkeypatch):
    """The run's own records name what each member ran on; the tested tree is the harness's
    record at run time (M1 evidence), next to these."""
    ls.Owner(led).install(monkeypatch)
    _round_one(led, run_id, lead_after=[[ls.decide(led, run_id, "done", "ok")]])
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    assert team.drive(ls.Context()).status == "done"
    parts = ts.rows(led, run_id)["participants"]
    assert sorted(p["member"] for p in parts) == ["builder", "checker", "lead"]
    for p in parts:
        assert p["pin"]["image"] == box.image and p["pin"]["pi_version"] == box.pi_version
        assert p["pin"]["team"]  # the team's settings digest (R2 C3)


@pytest.mark.parametrize("lie", ["model", "tools", "identity"])
def test_b16_a_member_whose_pi_reads_back_other_settings_never_reaches_the_model(
        lie, led, box, run_id, tmp_path, monkeypatch):
    from tests.test_pi_agent.support import FakeBox

    ls.Owner(led).install(monkeypatch)
    _round_one(led, run_id, lead_after=[[ls.decide(led, run_id, "done", "ok")]])
    monkeypatch.setattr(FakeBox, "lie", lie)
    team = ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"))
    out = team.drive(ls.Context())
    assert out.status == "failed" and "lead" in out.text, out.text
    assert ts.PROMPTS["lead"] == []  # refused before its prompt: no model call
    assert team.done_review() is None
    ts.check_invariants(led, run_id)
