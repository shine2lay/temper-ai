"""Existing leader tests kept for flow: tools, waits, recovery, cancel and pinned settings.

Round-only review/view/keep-going cases were removed with that execution mode. Scripted Pi
members exercise the same runtime without a model, network or second Temper.
"""

from __future__ import annotations

import pytest

from temper_ai.pi_agent.ledger import acts
from temper_ai.pi_agent.team_flow import FlowTeam
from temper_ai.pi_agent.team_leader import TOOLS_NOTE, tools_note
from temper_ai.stage.exceptions import RunParked
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts


def asked_after_their_rows(owner: ls.Owner) -> None:
    for ask in owner.asked:
        row = ask["row"]
        assert row is not None
        assert row["wait_id"] == ask["wait_id"] and row["state"] == "open"
        assert row["gate_name"].endswith(f"~ask-{ask['wait_id']}")


def work_scripts() -> None:
    def lead_turn():
        heard = {h["from"] for p in ts.PROMPTS["lead"] for h in ts.headers(p)}
        if {f'member "{m}"' for m in ("builder", "checker")} <= heard:
            return [ls.op("done", summary="Both parts finished")]
        return [ls.op("idle", note="waiting for both parts")]

    ts.SCRIPTS["lead"] = ls.Turns(lead_turn)
    ts.SCRIPTS["lead"].append([ts.send("builder", "build", "work_request"),
                               ts.send("checker", "check", "work_request"), ls.op("idle")])
    ts.SCRIPTS["builder"] = [[ts.reply_to_first("built", sender="lead"), ls.op("idle")]]
    ts.SCRIPTS["checker"] = [[ts.reply_to_first("checked", sender="lead"), ls.op("idle")]]


def open_flow(led, box, run_id, tmp_path, **kw):
    return ls.open_flow(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"),
                        settings={**ls.FLOW_SETTINGS, "max_parallel": 1}, **kw)


def test_each_members_framing_carries_the_tools_note_with_exactly_its_tools(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    work_scripts()
    team = open_flow(led, box, run_id, tmp_path)
    assert team.drive(ls.Context()).status == "done"
    expected = {"lead": ["ask_owner", "done", "idle", "read", "send_message", "share"],
                "builder": ["ask_owner", "idle", "read", "send_message", "share"],
                "checker": ["ask_owner", "idle", "read", "send_message", "share"]}
    for name, tools in expected.items():
        assert sorted(team.tools_for(team.members[name])) == tools
        note = tools_note(tools)
        assert note == TOOLS_NOTE.format(tools=", ".join(tools))
        assert ts.PROMPTS[name]
        assert all(note in p for p in ts.PROMPTS[name])
        others = set().union(*expected.values()) - set(tools)
        assert others.isdisjoint(set(note.split(": ", 1)[1].split(". ")[0].split(", ")))


def test_a_repeated_call_gets_its_first_answer_and_a_changed_one_is_refused(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    ts.SCRIPTS["lead"] = [[ls.op("share", note="draft", client_msg_id="call_1"),
                           ls.op("share", note="draft", client_msg_id="call_1"),
                           ls.op("share", note="other", client_msg_id="call_1"), ls.op("idle")]]
    team = open_flow(led, box, run_id, tmp_path)
    with pytest.raises(RunParked):
        team.drive(ls.Context())
    first, again, changed, _idle = ls.replies("lead")
    assert first["ok"] and not first["duplicate"]
    assert again["ok"] and again["duplicate"] and again["act_id"] == first["act_id"]
    assert changed == {"ok": False, "code": "idempotency_conflict",
                       "detail": "that call id was already used for a different call"}
    assert len([a for a in ls.table(led, acts, run_id) if a["op"] == "share"]) == 1


def test_a_stalled_team_asks_the_owner_and_a_nudge_reaches_the_leader(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led, "nudge: share your work").install(monkeypatch)
    ts.SCRIPTS["lead"] = [[{"say": "thinking it over"}], [ls.op("done", summary="ok")]]
    team = open_flow(led, box, run_id, tmp_path)
    out = team.drive(ls.Context())
    assert out.status == "done"
    (ask,) = owner.asked
    asked_after_their_rows(owner)
    assert ask["row"]["kind"] == "stalled" and ask["options"] == ("nudge", "stop")
    assert ask["question"] == (
        "The team is stalled: nothing is running, nothing is waiting to be delivered and lead "
        "has not said done. Reply 'nudge' (optionally with a message for lead) or 'stop'.")
    assert "Reply" not in ask["row"]["subject"]["question"]
    assert sum("share your work" in p for p in ts.PROMPTS["lead"]) == 1


def test_stop_when_stalled_ends_the_team_stopped(led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led, "stop").install(monkeypatch)
    ts.SCRIPTS["lead"] = [[{"say": "nothing to do"}]]
    team = open_flow(led, box, run_id, tmp_path)
    out = team.drive(ls.Context())
    assert (out.status, out.text) == ("stopped", "stopped when the team had nothing left to do")


@pytest.mark.parametrize("kind", ["pause", "stalled"])
def test_e18_a_stop_keeps_the_words_given_with_it_and_the_text_stays_neutral(
        led, box, run_id, tmp_path, monkeypatch, kind):
    from temper_ai.pi_agent.team_runtime import stop_ends_cancelled

    words = "we have what we need " + "x" * 2100
    ls.Owner(led, f"stop: {words}").install(monkeypatch)
    if kind == "pause":
        monkeypatch.setattr(FlowTeam, "usage", lambda self: {
            "cost_usd": 100.0, "total_tokens": 0, "llm_calls": 0})
        expected = "stopped at the check-in at $100"
    else:
        ts.SCRIPTS["lead"] = [[{"say": "nothing to do"}]]
        expected = "stopped when the team had nothing left to do"
    team = open_flow(led, box, run_id, tmp_path)
    out = team.drive(ls.Context())
    assert (out.status, out.text) == ("stopped", expected)
    stop = team.stop_wait()
    assert stop["kind"] == kind and stop_ends_cancelled(stop)
    assert stop["decision"]["words"] == words.strip()[:2000]
    assert "owner" not in out.text and "by " not in out.text


def test_e18_a_stop_with_no_words_keeps_none(led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led, "stop").install(monkeypatch)
    ts.SCRIPTS["lead"] = [[{"say": "nothing to do"}]]
    team = open_flow(led, box, run_id, tmp_path)
    team.drive(ls.Context())
    assert team.stop_wait()["decision"]["words"] is None


def test_b11_a_cut_off_turn_pauses_the_team_and_retry_resends_the_same_messages(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led, "retry").install(monkeypatch)
    work_scripts()
    ts.SCRIPTS["builder"][:0] = [[{"die": 1}], [{"die": 1}]]
    team = open_flow(led, box, run_id, tmp_path)
    out = team.drive(ls.Context())
    assert out.status == "done", out.text
    (ask,) = owner.asked
    asked_after_their_rows(owner)
    assert ask["row"]["kind"] == "recovery"
    subject = ask["row"]["subject"]
    assert subject["reply_hint"] == ("Reply 'accept' to keep what it did without running it "
                                     "again, or 'retry' to send its messages again.")
    assert "Reply" not in subject["question"]
    assert subject["question"].startswith("builder's turn 2 did not finish (")
    assert ask["question"] == f"{subject['question']} {subject['reply_hint']}"
    first, second, retried = ts.PROMPTS["builder"]
    assert ts.ids_in(first) == ts.ids_in(second) == ts.ids_in(retried) and ts.ids_in(first)
    # The checker carried on while the builder was held; the leader waited for its reply.
    assert len(ts.PROMPTS["lead"]) == 3
    ts.check_invariants(led, run_id)


def test_b11_stop_at_a_recovery_wait_ends_the_team_red_never_done(
        led, box, run_id, tmp_path, monkeypatch):
    from temper_ai.pi_agent.team_runtime import stop_ends_cancelled

    ls.Owner(led, "stop").install(monkeypatch)
    work_scripts()
    ts.SCRIPTS["builder"][:0] = [[{"die": 1}], [{"die": 1}]]
    team = open_flow(led, box, run_id, tmp_path)
    out = team.drive(ls.Context())
    assert out.status == "stopped"
    assert out.text == "builder turn 2 did not finish and the team was stopped"
    assert not out.record
    assert team.stop_wait()["kind"] == "recovery"
    assert not stop_ends_cancelled(team.stop_wait())
    ts.check_invariants(led, run_id)


def test_b12_a_cancelled_run_ends_the_team_and_queued_messages_go_undelivered(
        led, box, run_id, tmp_path, monkeypatch):
    import threading

    ls.Owner(led).install(monkeypatch)
    work_scripts()
    cancel = threading.Event()
    ts.SCRIPTS["lead"][0].append({"call": lambda _b, _m: cancel.set()})
    team = open_flow(led, box, run_id, tmp_path, cancel_event=cancel)
    out = team.drive(ls.Context(cancel_event=cancel))
    assert out.status == "cancelled"
    snap = ts.rows(led, run_id)
    assert {p["ended_reason"] for p in snap["participants"]} == {"run_cancelled"}
    assert not [m for m in snap["messages"] if m["state"] in ("held", "pending")]
    ts.check_invariants(led, run_id)


def test_b13_a_reviewer_whose_turn_fails_turns_the_team_red_never_done(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led).install(monkeypatch)
    work_scripts()
    ts.SCRIPTS["checker"] = [[{
        "error": "403 permission_error: OAuth authentication is currently not allowed for this organization"}]]
    team = open_flow(led, box, run_id, tmp_path)
    out = team.drive(ls.Context())
    assert out.status == "failed" and "refused the call" in out.text, out.text
    assert not out.record and owner.asked == []
    ts.check_invariants(led, run_id)


def test_b15_each_members_record_names_the_worker_image_and_the_pi_version(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    work_scripts()
    team = open_flow(led, box, run_id, tmp_path)
    assert team.drive(ls.Context()).status == "done"
    parts = ts.rows(led, run_id)["participants"]
    assert sorted(p["member"] for p in parts) == ["builder", "checker", "lead"]
    for p in parts:
        assert p["pin"]["image"] == box.image and p["pin"]["pi_version"] == box.pi_version
        assert p["pin"]["team"]


@pytest.mark.parametrize("lie", ["model", "tools", "identity"])
def test_b16_a_member_whose_pi_reads_back_other_settings_never_reaches_the_model(
        lie, led, box, run_id, tmp_path, monkeypatch):
    from tests.test_pi_agent.support import FakeBox

    ls.Owner(led, "stop").install(monkeypatch)
    work_scripts()
    monkeypatch.setattr(FakeBox, "lie", lie)
    team = open_flow(led, box, run_id, tmp_path)
    out = team.drive(ls.Context())
    assert out.status == "stopped" and "lead" in out.text, out.text
    assert ts.PROMPTS["lead"] == []  # refused before its prompt: no model call
    assert not out.record
    ts.check_invariants(led, run_id)
