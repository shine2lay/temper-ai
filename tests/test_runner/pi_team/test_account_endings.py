"""How a member's model call can end, on the run's one account (M4 ADR-M4-09, ADR-M4-16):
model-free, every member a scripted Pi on a team whose account is slot ``acct-b``.

- A call the account refuses (disabled, or not allowed for the organization) makes a red turn
  naming the slot and the refusal and stops the team with a plain problem: never a recovery
  wait, never the other slot, never a retry on the same slot.
- The refusal is read on the error path only: the provider's error (a 403 permission_error /
  oauth_not_allowed_for_organization), or a call with no model output at all whose whole
  result is the refusal. A member's normal answer quoting the sentence completes normally.
- A turn whose last model reply ended in an error is a failed turn whatever text came with
  it, and that text is never the member's answer.
- A usage limit is a recovery wait naming the slot, the limit and the reset; a retry keeps the
  same account, model and thinking.
- A model's own refusal (a safety classifier) is a red turn naming it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from temper_ai.pi_agent import team_view
from temper_ai.pi_agent.accounts import refusal_problem
from temper_ai.pi_agent.ledger import ACCOUNT_REFUSED, reviews, waits
from temper_ai.stage.exceptions import RunParked
from tests.test_runner.pi_team import leader_support as ls
from tests.test_runner.pi_team import support as ts
from tests.test_runner.pi_team.test_leader_loop import rounds

SLOT = "acct-b"
ACCOUNT = {"slot": SLOT, "picked_at": "2026-10-06T12:00:00+00:00", "by": "room",
           "room": {"five_hour": 20.0, "seven_day": 30.0,
                    "five_hour_resets_at": "2026-10-06T17:00:00+00:00"}}
#: The refusal's sentences, as the provider and the CLI give them.
OAUTH_403 = ("403 permission_error: OAuth authentication is currently not allowed for this "
             "organization. (oauth_not_allowed_for_organization)")
DISABLED = "Your organization has disabled Claude subscription access for Claude Code"


def open_team(led, box, run_id, tmp_path, **kw):
    return ls.open_leader(led, box, run_id=run_id, source=ls.project(tmp_path / "proj"),
                          account=ACCOUNT, **kw)


def _member_of(led, run_id, turn):
    parts = {p["participant_id"]: p["member"] for p in ts.rows(led, run_id)["participants"]}
    return parts.get(turn["participant_id"])


def red_turn(led, run_id, member) -> dict:
    (failed,) = [t for t in ts.rows(led, run_id)["turns"]
                 if _member_of(led, run_id, t) == member and t["state"] == "failed"]
    return failed


def said_by(led, run_id, member) -> list[str]:
    return [str(m.get("body") or m.get("text") or m) for m in ts.rows(led, run_id)["messages"]
            if m.get("sender") == member]


def slots_used() -> set[str]:
    return {slot for _m, slot, _model, _thinking in ts.SLOTS_USED}


# --- the account refused the call -------------------------------------------------------------


REFUSALS = {
    # the provider's structured error: the normal shape for a Pi member
    "403-error": [{"error": OAUTH_403}],
    # the same error reply, with text the model streamed before it
    "403-error-with-text": [{"error": OAUTH_403, "text": "Let me look at the README first."}],
    # a call with no model output at all whose whole result is the refusal (the CLI's shape)
    "no-output-whole-result": [{"alone": DISABLED}],
}


@pytest.mark.parametrize("script", list(REFUSALS.values()), ids=list(REFUSALS))
def test_a_refused_call_is_a_red_turn_and_stops_the_team_never_a_wait_a_switch_or_a_retry(
        led, box, run_id, tmp_path, monkeypatch, script):
    owner = ls.Owner(led, "retry", "retry").install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["builder"].insert(0, script)
    recorder = ts.Recorder()
    team = open_team(led, box, run_id, tmp_path, recorder=recorder)
    out = team.drive(ls.Context())

    # the team stops with a plain problem, never done
    assert out.status == "failed"
    assert out.text == refusal_problem(SLOT)
    assert out.text == (f"account {SLOT} refused the call (not allowed for this organization); "
                        "the team was stopped")
    assert team.done_review() is None and not out.record
    snap = ts.rows(led, run_id)
    assert {p["ended_reason"] for p in snap["participants"]} == {ACCOUNT_REFUSED}
    # a red turn naming the slot and the refusal
    turn = red_turn(led, run_id, "builder")
    head = f"account {SLOT} refused the call (not allowed for this organization): "
    assert turn["error"].startswith("builder (") and head in turn["error"]
    refusal = turn["error"].split(head, 1)[1]
    assert ("not allowed for this organization" in refusal
            or "disabled claude subscription access" in refusal.lower())
    assert turn["account_slot"] == SLOT
    # no wait: nobody was asked and no wait was opened
    assert owner.asked == []
    assert ls.table(led, waits, run_id) == []
    # no switch and no retry: one call for the builder, every call on the run's slot
    assert len(ts.PROMPTS["builder"]) == 1
    assert slots_used() == {SLOT}
    # the error's words are never the member's answer
    assert not turn["output"]
    assert not [s for s in said_by(led, run_id, "builder")
                if "not allowed" in s or "disabled" in s.lower() or "README first" in s]
    ts.check_invariants(led, run_id)


def test_a_resume_after_a_refusal_stays_stopped_without_another_call(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led, "retry").install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["lead"].insert(0, [{"error": OAUTH_403}])
    out = open_team(led, box, run_id, tmp_path).drive(ls.Context())
    assert out.status == "failed" and out.text == refusal_problem(SLOT)
    calls = len(ts.SLOTS_USED)

    again = ls.make_leader(led, box, run_id=run_id, attempt="attempt-2",
                           source=tmp_path / "proj", account=ACCOUNT)
    again.open({"goal": again.goal})
    out = again.drive(ls.Context())
    assert out.status == "failed" and out.text == refusal_problem(SLOT)
    assert len(ts.SLOTS_USED) == calls  # no reset fixes it: nothing was called again
    assert owner.asked == [] and ls.table(led, waits, run_id) == []
    ts.check_invariants(led, run_id)


# --- a normal answer that quotes the sentence ---------------------------------------------------


@pytest.mark.parametrize("words", [
    f"From my notes: the CLI said \"{DISABLED}\" last week; the README is fine now.",
    DISABLED,  # the whole answer, written by the model (it produced output): still an answer
    OAUTH_403,
], ids=["quoted", "whole-answer", "quoted-403"])
def test_a_normal_answer_quoting_the_refusal_completes_with_nothing_stopped(
        led, box, run_id, tmp_path, monkeypatch, words):
    owner = ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["builder"][0].append({"say": words})
    out = open_team(led, box, run_id, tmp_path).drive(ls.Context())
    assert out.status == "done", out.text
    assert owner.asked == []
    snap = ts.rows(led, run_id)
    assert not [t for t in snap["turns"] if t["state"] == "failed"]
    assert {p["ended_reason"] for p in snap["participants"]} == {"team_done"}
    (builder_turn,) = [t for t in snap["turns"] if _member_of(led, run_id, t) == "builder"]
    assert builder_turn["state"] == "completed" and builder_turn["output"] == words
    assert slots_used() == {SLOT}
    ts.check_invariants(led, run_id)


# --- an error reply, whatever text came with it --------------------------------------------------


def test_an_error_reply_with_text_is_a_failed_turn_and_the_text_is_never_the_answer(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["checker"] = [[{"error": "500 api_error: Internal server error",
                               "text": "The version looks right to me, satisfied."}]]
    out = open_team(led, box, run_id, tmp_path).drive(ls.Context())
    assert out.status == "failed" and "checker" in out.text, out.text
    assert out.text != refusal_problem(SLOT)
    turn = red_turn(led, run_id, "checker")
    assert "500 api_error" in turn["error"] and not turn["output"]
    assert not [s for s in said_by(led, run_id, "checker") if "satisfied" in s]
    assert "done" not in [r["decision"] for r in ls.table(led, reviews, run_id)]
    assert owner.asked == []  # red at once: not a question, not a wait
    ts.check_invariants(led, run_id)


def test_a_safety_classifier_refusal_is_a_red_turn_naming_it(led, box, run_id, tmp_path,
                                                             monkeypatch):
    owner = ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["checker"] = [[{"error": "The model refused the request: stop_reason refusal "
                                        "(cyber classifier)"}]]
    out = open_team(led, box, run_id, tmp_path).drive(ls.Context())
    assert out.status == "failed" and "checker" in out.text, out.text
    turn = red_turn(led, run_id, "checker")
    assert "the model refused the request (safety classifier): " in turn["error"]
    assert "cyber classifier" in turn["error"]
    assert out.text != refusal_problem(SLOT) and owner.asked == []
    ts.check_invariants(led, run_id)


# --- a usage limit on the pinned slot -----------------------------------------------------------


LIMIT = "429 rate_limit_error: You've hit your session limit \u00b7 resets 3pm (America/Los_Angeles)"


def test_a_limit_is_a_recovery_wait_naming_the_slot_the_limit_and_the_reset(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led, "retry").install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["builder"].insert(0, [{"error": LIMIT}])
    out = open_team(led, box, run_id, tmp_path).drive(ls.Context())
    assert out.status == "done", out.text

    (ask,) = owner.asked
    row = ask["row"]
    assert row["kind"] == "recovery"
    subject = row["subject"]
    assert subject["account_slot"] == SLOT
    assert "session limit" in subject["limit"]
    assert subject["resets"] == "3pm (America/Los_Angeles)"
    assert f"account {SLOT} hit a usage limit" in subject["question"]
    assert "Retrying keeps the same account, model and thinking" in subject["question"]
    assert "retry" in subject["options"]
    # the retry ran on the same account, model and thinking; nothing switched
    builder = [(slot, model, thinking) for m, slot, model, thinking in ts.SLOTS_USED
               if m == "builder"]
    assert len(builder) == 2 and len(set(builder)) == 1 and builder[0][0] == SLOT
    assert slots_used() == {SLOT}
    ts.check_invariants(led, run_id)


def test_a_limit_without_its_reset_names_the_reset_from_the_room_at_the_start(
        led, box, run_id, tmp_path, monkeypatch):
    owner = ls.Owner(led, "stop").install(monkeypatch)
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["builder"].insert(0, [{"error": "429 rate_limit_error: rate limited"}])
    out = open_team(led, box, run_id, tmp_path).drive(ls.Context())
    assert out.status == "stopped"
    (ask,) = owner.asked
    assert ask["row"]["subject"]["resets"] == ("2026-10-06T17:00:00+00:00 (room figures at "
                                               "the run's start)")
    ts.check_invariants(led, run_id)


def test_the_run_view_shows_the_slot_on_each_turn_and_the_limit_wait_s_slot_limit_and_reset(
        led, box, run_id, tmp_path, monkeypatch):
    """SW-20: the run view shows the turns, the account slot and the limit waits."""
    ls.Owner(led).install(monkeypatch)  # no answer: the run parks on the recovery wait
    rounds(led, run_id, ["done"])
    ts.SCRIPTS["builder"].insert(0, [{"error": LIMIT}])
    with pytest.raises(RunParked):
        open_team(led, box, run_id, tmp_path).drive(ls.Context())

    reader = team_view.TeamReader(led, run_id, ts.HOST, "lead")
    (wait,) = team_view.open_waits_view(reader, {})
    assert wait["kind"] == "recovery" and wait["member"] == "builder"
    assert (wait["account_slot"], wait["resets"]) == (SLOT, "3pm (America/Los_Angeles)")
    assert "session limit" in wait["limit"]
    names = {p["participant_id"]: p["member"] for p in ts.rows(led, run_id)["participants"]}
    entries = team_view.turn_entries(reader, names)
    assert entries and {e["data"]["account_slot"] for e in entries} == {SLOT}
    members = team_view.members_view(reader, [{"name": n} for n in ts.NAMES], [wait])
    builder = next(m for m in members if m["name"] == "builder")
    assert builder["activity"] == "waiting_on_owner"
    assert builder["last_turn"]["account_slot"] == SLOT
    ts.check_invariants(led, run_id)


# --- the slot on every turn and in the run's events ---------------------------------------------


def test_every_turn_and_its_event_record_the_slot_and_the_box_keeps_the_canonical_provider(
        led, box, run_id, tmp_path, monkeypatch):
    ls.Owner(led).install(monkeypatch)
    rounds(led, run_id, ["done"])
    recorder = ts.Recorder()
    out = open_team(led, box, run_id, tmp_path, recorder=recorder).drive(ls.Context())
    assert out.status == "done", out.text
    turns = ts.rows(led, run_id)["turns"]
    assert turns and {t["account_slot"] for t in turns} == {SLOT}
    started = [e["data"] for e in recorder.events if e["type"] == "agent.started"]
    assert started and {d.get("account_slot") for d in started} == {SLOT}
    # inside the box the provider stays the member's own: the slot only pins the hand-off
    assert {d.get("provider") for d in started} == {"openai-codex"}
    assert {s for _m, s, _model, _t in ts.SLOTS_USED} == {SLOT}


# --- #55's drop-and-retry stays in the CLI provider's pool ----------------------------------------


_POOL = ("temper_ai.llm.fallback", "temper_ai.llm.service", "temper_ai.llm.providers",
         "local.providers", "local.agents")


def test_no_pi_lane_module_imports_the_cli_providers_pool():
    """The Pi lane reads the shared refusal signatures (temper_ai.llm.account_messages) and
    nothing of the CLI providers' token pool, whose drop-and-retry never reaches a member."""
    root = Path(__file__).resolve().parents[3] / "temper_ai"
    files = [*sorted((root / "pi_agent").glob("*.py")), root / "runner" / "pi_lane.py",
             root / "runner" / "pi_preflight.py"]
    found: list[str] = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                     else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            found += [f"{path.name}: {n}" for n in names if n.startswith(_POOL)]
    assert found == []
