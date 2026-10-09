"""SW-85: a deploy that changes a parked Pi conversation's settings asks the owner instead of
failing it (temper_ai/pi_agent/settings_wait.py).

Since C7 every owner answer reopens a Pi conversation in a new attempt, and that attempt checks
the conversation's pin (temper_ai/pi_agent/host.py ``pin_for``) against what the configs and
the box say now. Every land deploys, so a change while a conversation waits is bound to happen.
Proven here through a real in-process Temper, every Pi scripted (nothing reaches a model):

1. a single Pi step parked at an owner wait and reopened under a changed agent config or
   extension asks the owner at a ``settings`` wait first: no turn ran, the session files are
   untouched, nothing failed, and the answer that reopened it is held;
2. ``go on`` (a run-page pick or a typed answer) re-pins it to the new settings, then applies
   the held answer once, and the next turn runs with the new settings; the wait's typed fields
   carry text only for the short settings and full digests for the rest;
3. ``stop`` ends the step and the run cancelled (M3 E18), never failed, in neutral words: the
   step ran once in that attempt, no turn ran, the held answer was never applied, and a Resume
   doesn't reopen it;
4. an answer naming neither choice (or none at all) decides nothing: the owner is asked again;
5. settings that changed again while the settings wait was open: its go on re-pins nothing,
   and a new settings wait names the newer settings;
6. a team: one member's change asks at one team-level settings wait; go on carries the team on
   to done; stop ends it stopped (the engine's reason) and the run cancelled; a changed member
   set is still refused;
7. the Team page's API shows the wait's kind, state, answers and typed fields, and its timeline
   shows the settings answer, then the held answer once (never after a stop).

Runs on SQLite and on the Postgres tier; tables.md's invariants I1-I8 are checked after every
test here (pi_parking/conftest.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from temper_ai.pi_agent.host import PiHost
from tests.test_pi_agent import support as sup
from tests.test_pi_agent import test_team as tt
from tests.test_pi_agent.support import FakeBox
from tests.test_runner.pi_parking import support as pw
from tests.test_runner.pi_parking import test_team_api as team_api
from tests.test_runner.pi_parking import test_team_runs as runs
from tests.test_runner.pi_team import support as ts

team_on = tt.team_on  # the team switched on with the fixture role list; asked for after pw_run
tr = runs.tr
api = team_api.api

HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
#: The owner's answer that reopens the conversation (held until the settings are settled).
HELD = "look once more"
STEP_STOPPED = "the Pi step was stopped: its settings changed since its conversation started"
TEAM_STOPPED = "stopped when the team's settings changed since its conversations started"
QA = next(m for m in tt.members() if m["name"] == "qa")


# --- helpers ---------------------------------------------------------------------------------


def pin_digest(pin: dict) -> str:
    """A pin's digest as M3 E24 defines it, worked out here on its own: the sha256 of the
    pin's canonical JSON (keys sorted, no spaces)."""
    return hashlib.sha256(json.dumps(pin, sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()


def _prompts() -> int:
    """Model prompts sent across every worker the fake started: one per turn run."""
    return sum(s["prompts"] for s in FakeBox.STARTS)


def _statuses(eid: str) -> list[str]:
    return [a["status"] for a in pw.attempts(eid)]


def _participant(eid: str) -> dict:
    (part,) = sup.ledger().snapshot(eid)["participants"]
    return part


def _waits(eid: str) -> dict[str, dict]:
    return {w["wait_id"]: w for w in sup.ledger().snapshot(eid)["waits"]}


def _owner_messages(eid: str, body: str) -> int:
    """How many times the owner's words reached the conversation."""
    return sum(1 for m in sup.ledger().snapshot(eid)["messages"]
               if m["sender_kind"] == "owner" and m["body"] == body)


def _files(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def _said(eid: str, text: str) -> bool:
    """Whether any of the run's events says ``text``."""
    return any(text in str(e["data"]) for e in sup.events(eid))


def _change_thinking(monkeypatch, thinking: str) -> None:
    """A deploy changed the Pi step's agent config: it now thinks at ``thinking``."""
    monkeypatch.setitem(sup.WORKFLOWS, "pi_talk", lambda: [
        sup.step("brief"), sup.pi_node(thinking=thinking), sup.step("audit", ["talk"])])


def _change_extension(marker: str) -> None:
    """A deploy changed the identity extension (its digest is in every Pi's pin)."""
    raw = json.loads(Path(os.environ["TEMPER_PI_BOX_CONFIG"]).read_text())
    (Path(raw["identity_extension"]) / "index.ts").write_text(
        f"export default function () {{}} // {marker}\n")


def _watch_runs(monkeypatch) -> list[str]:
    """How every PiHost.run call ended: ``returned``, or the name of what it raised."""
    ended: list[str] = []
    real_run = PiHost.run

    def watched(self, input_data, context):
        try:
            result = real_run(self, input_data, context)
        except BaseException as exc:
            ended.append(type(exc).__name__)
            raise
        ended.append("returned")
        return result

    monkeypatch.setattr(PiHost, "run", watched)
    return ended


def _parked_at_owner(pw_run) -> tuple[str, dict]:
    eid = sup.start(pw_run.client, "pi_talk", pw_run.ws)
    pw.wait_parked(pw_run.state, eid, 1)
    return eid, sup.open_wait(eid, "owner")


def _answer_owner(pw_run, eid: str, owner: dict) -> None:
    r = pw.approve(pw_run.client, eid, owner["gate_name"], event_id=owner["ask_event_id"],
                   response=HELD)
    assert r.status_code == 200, r.text
    assert r.json()["carries_on"] is True


def _go_on(pw_run, eid: str, wait: dict, how: str = "typed") -> None:
    if how == "pick":  # the run page's GateModal: a picked option, sent as ``answers``
        r = pw.pick(pw_run.client, eid, wait["gate_name"], "go on",
                    event_id=wait["ask_event_id"], question=wait["subject"]["question"])
    else:
        r = pw.approve(pw_run.client, eid, wait["gate_name"], event_id=wait["ask_event_id"],
                       response="go on")
    assert r.status_code == 200, r.text


def _reopened_at_settings(pw_run, monkeypatch) -> tuple[str, dict, dict, dict]:
    """A Pi step parked at its owner wait; a deploy changes its agent config (thinking medium
    -> high); the owner's answer reopens it at a settings wait. Returns (run, owner wait,
    settings wait, the pin stored before)."""
    eid, owner = _parked_at_owner(pw_run)
    before = _participant(eid)["pin"]
    _change_thinking(monkeypatch, "high")
    _answer_owner(pw_run, eid, owner)
    pw.wait_parked(pw_run.state, eid, 2)
    return eid, owner, sup.open_wait(eid, "settings"), before


# --- 1. asked first ----------------------------------------------------------------------------


@pytest.mark.parametrize("change", ["agent_config", "extension"])
def test_1_a_changed_setting_asks_the_owner_first_and_nothing_runs_fails_or_is_applied(
        pw_run, monkeypatch, change):
    state = pw_run.state
    eid, owner = _parked_at_owner(pw_run)
    part = _participant(eid)
    folder = Path(part["session_dir"]).parent
    files = _files(folder)
    assert any(name.endswith(".jsonl") for name in files), "the conversation's session file"
    starts = len(FakeBox.STARTS)
    if change == "agent_config":
        _change_thinking(monkeypatch, "high")
    else:
        _change_extension("SECRET-EXT-1")

    _answer_owner(pw_run, eid, owner)
    pw.wait_parked(state, eid, 2)
    wait = sup.open_wait(eid, "settings")
    assert pw.parked(pw.attempts(eid)[-1])["wait_id"] == wait["wait_id"]
    assert wait["gate_name"] == f"talk~ask-{wait['wait_id']}"
    # nothing failed, no turn ran, no worker started, the session files are as they were
    assert _statuses(eid) == ["parked", "waiting"]  # the latest attempt waits, parked
    assert "failed" not in sup.node_status(eid, "talk")
    assert _prompts() == 1 and len(FakeBox.STARTS) == starts
    assert _files(folder) == files
    # the answer that reopened it is held: its wait still open, its words not delivered
    assert {w: row["state"] for w, row in _waits(eid).items()} == {
        owner["wait_id"]: "open", wait["wait_id"]: "open"}
    assert _owner_messages(eid, HELD) == 0
    assert _participant(eid)["pin"] == part["pin"], "not re-pinned before the owner says so"

    subject = wait["subject"]
    assert (subject["header"], subject["options"]) == ("settings", ["go on", "stop"])
    assert subject["reply_hint"] == "Reply 'go on' or 'stop'."
    keys = [ch["key"] for ch in subject["settings_changes"]]
    if change == "agent_config":
        assert keys == ["agent_config_sha256", "thinking"]
        assert "thinking medium -> high" in subject["question"]
    else:
        assert keys == ["extensions.identity"]
        assert "extension identity" in subject["question"]
    assert "SECRET-EXT" not in json.dumps(subject)


# --- 2. go on ----------------------------------------------------------------------------------


@pytest.mark.parametrize("how", ["pick", "typed"])
def test_2_go_on_repins_then_applies_the_held_answer_once_and_the_next_turn_uses_the_new_settings(
        pw_run, monkeypatch, how):
    c, state = pw_run.client, pw_run.state
    eid, owner = _parked_at_owner(pw_run)
    part = _participant(eid)
    old = part["pin"]
    _change_thinking(monkeypatch, "high")
    _change_extension("SECRET-EXT-2")
    _answer_owner(pw_run, eid, owner)
    pw.wait_parked(state, eid, 2)
    wait = sup.open_wait(eid, "settings")
    subject = wait["subject"]

    # the typed fields: one entry per changed setting, text only for the short settings and a
    # full sha256 for every other; never a file's contents or the agent's message
    changes = subject["settings_changes"]
    assert [(ch["scope"], ch["member"], ch["key"], ch["value_kind"]) for ch in changes] == [
        ("member", sup.ROLE, "agent_config_sha256", "sha256"),
        ("member", sup.ROLE, "extensions.identity", "sha256"),
        ("member", sup.ROLE, "thinking", "text")]
    by_key = {ch["key"]: ch for ch in changes}
    assert (by_key["thinking"]["old"], by_key["thinking"]["new"]) == ("medium", "high")
    for key in ("agent_config_sha256", "extensions.identity"):
        assert HEX64.match(by_key[key]["old"]) and HEX64.match(by_key[key]["new"])
        assert by_key[key]["old"] != by_key[key]["new"]
    assert by_key["agent_config_sha256"]["old"] == old["agent_config_sha256"]
    assert by_key["extensions.identity"]["old"] == old["extensions"]["identity"]
    assert subject["pin_old"] == pin_digest(old) and HEX64.match(subject["pin_new"])
    assert (f"Settings fingerprint {subject['pin_old'][:12]} -> {subject['pin_new'][:12]}."
            in subject["question"])
    assert (f"agent config {by_key['agent_config_sha256']['old'][:12]} -> "
            f"{by_key['agent_config_sha256']['new'][:12]}") in subject["question"]
    assert subject["pins"] == [{"member": sup.ROLE, "participant_id": part["participant_id"],
                                "pin_old": subject["pin_old"], "pin_new": subject["pin_new"]}]
    shown = json.dumps(subject)
    assert "SECRET-EXT" not in shown and "note.txt" not in shown

    _go_on(pw_run, eid, wait, how)
    pw.wait_parked(state, eid, 3)
    sup.open_wait(eid, "owner", other_than=owner["wait_id"])
    now = _participant(eid)["pin"]
    assert now["thinking"] == "high" and pin_digest(now) == subject["pin_new"]
    rows = _waits(eid)
    decision = rows[wait["wait_id"]]["decision"]
    assert (decision["answer"], decision["applied"], decision["pin_old"],
            decision["pin_new"]) == ("go on", True, subject["pin_old"], subject["pin_new"])
    assert decision["changed"] == [{"scope": "member", "member": sup.ROLE, "key": k}
                                   for k in ("agent_config_sha256", "extensions.identity",
                                             "thinking")]
    # then the held answer, once, and the next turn on the new settings
    assert rows[owner["wait_id"]]["state"] == "decided"
    assert rows[wait["wait_id"]]["decided_at"] <= rows[owner["wait_id"]]["decided_at"]
    assert _owner_messages(eid, HELD) == 1
    assert _prompts() == 2
    assert [s["thinking"] for s in FakeBox.STARTS] == ["medium", "high"]

    n = pw.finish_pi(c, eid)
    assert [a["status"] for a in pw.wait_ended(eid, n)] == [
        "parked", "parked", "parked", "completed"]
    assert _owner_messages(eid, HELD) == 1, "never applied again"
    assert sup.node_status(eid, "audit")[-1] == "completed"


# --- 3. stop -----------------------------------------------------------------------------------


def test_3_stop_ends_the_step_and_run_cancelled_in_neutral_words_and_a_resume_never_reopens(
        pw_run, monkeypatch):
    ended = _watch_runs(monkeypatch)
    c = pw_run.client
    eid, owner, wait, before = _reopened_at_settings(pw_run, monkeypatch)
    starts = len(FakeBox.STARTS)

    r = pw.approve(c, eid, wait["gate_name"], event_id=wait["ask_event_id"], response="stop")
    assert r.status_code == 200, r.text
    attempts = pw.wait_ended(eid, 3)
    assert [a["status"] for a in attempts] == ["parked", "parked", "cancelled"]
    # the stop is returned, never raised: the step ran once in that attempt, never retried
    assert ended == ["RunParked", "RunParked", "returned"]
    assert sup.node_status(eid, "talk")[-1] == "cancelled"
    # (What runs after a step that ended cancelled is E18's path, the same for every owner
    # stop; not decided here.)
    assert _said(eid, f"{STEP_STOPPED} (agent_config_sha256, thinking)"), "neutral (M3 E16)"
    assert "Workflow cancelled by user" not in str(attempts[-1]), "never the run's cancel"
    # no turn ran, no new wait opened, and the held answer was never applied
    assert _prompts() == 1 and len(FakeBox.STARTS) == starts
    rows = _waits(eid)
    assert {w: (row["state"], (row["decision"] or {}).get("answer")) for w, row in rows.items()} \
        == {owner["wait_id"]: ("cancelled", None), wait["wait_id"]: ("decided", "stop")}
    assert _owner_messages(eid, HELD) == 0
    part = _participant(eid)
    assert (part["state"], part["ended_reason"]) == ("ended", "team_stopped")
    assert part["pin"] == before

    # a later Resume doesn't reopen it: the step ends cancelled again, nothing runs or opens
    assert c.post(f"/api/runs/{eid}/resume", json={}).status_code == 200
    attempts = pw.wait_ended(eid, 4)
    assert attempts[-1]["status"] == "cancelled"
    assert ended[3:] == ["returned"]
    assert _prompts() == 1 and len(FakeBox.STARTS) == starts
    assert _waits(eid).keys() == rows.keys()
    assert _owner_messages(eid, HELD) == 0
    assert sup.node_status(eid, "talk")[-1] == "cancelled"


# --- 4. an unknown answer -----------------------------------------------------------------------


def test_4_an_answer_naming_neither_choice_or_none_at_all_decides_nothing_and_is_asked_again(
        pw_run, monkeypatch):
    c, state = pw_run.client, pw_run.state
    eid, owner, first, before = _reopened_at_settings(pw_run, monkeypatch)

    r = pw.pick(c, eid, first["gate_name"], event_id=first["ask_event_id"],
                question=first["subject"]["question"], custom="not sure yet")
    assert r.status_code == 200, r.text
    pw.wait_parked(state, eid, 3)
    second = sup.open_wait(eid, "settings", other_than=first["wait_id"])
    asked = second["subject"]
    assert asked["question"].startswith("That answer was not one of: go on, stop. Nothing was "
                                        "decided. The Pi step's settings changed")
    assert asked["settings_changes"] == first["subject"]["settings_changes"]
    assert (asked["pin_old"], asked["pin_new"]) == (first["subject"]["pin_old"],
                                                    first["subject"]["pin_new"])
    # nothing at all (a plain approval): asked again too
    r = pw.pick(c, eid, second["gate_name"], event_id=second["ask_event_id"],
                question=asked["question"])
    assert r.status_code == 200, r.text
    pw.wait_parked(state, eid, 4)
    third = sup.open_wait(eid, "settings", other_than=second["wait_id"])
    rows = _waits(eid)
    assert [(rows[w["wait_id"]]["decision"] or {}).get("answer") for w in (first, second)] == [
        "invalid", "invalid"]
    assert _participant(eid)["pin"] == before, "never a go on by default"
    assert _participant(eid)["state"] != "ended", "never a stop by default"
    assert _prompts() == 1 and _owner_messages(eid, HELD) == 0
    assert _statuses(eid) == ["parked"] * 3 + ["waiting"]

    _go_on(pw_run, eid, third)
    pw.wait_parked(state, eid, 5)
    sup.open_wait(eid, "owner", other_than=owner["wait_id"])
    assert _owner_messages(eid, HELD) == 1 and _prompts() == 2


# --- 5. changed again --------------------------------------------------------------------------


def test_5_settings_changed_again_while_asked_go_on_repins_nothing_and_a_new_wait_names_the_newer(
        pw_run, monkeypatch):
    state = pw_run.state
    eid, owner, first, before = _reopened_at_settings(pw_run, monkeypatch)
    _change_thinking(monkeypatch, "low")  # another deploy while the settings wait is open

    _go_on(pw_run, eid, first)
    pw.wait_parked(state, eid, 3)
    second = sup.open_wait(eid, "settings", other_than=first["wait_id"])
    decision = _waits(eid)[first["wait_id"]]["decision"]
    assert (decision["answer"], decision["applied"], decision["why"]) == (
        "go on", False, "the settings changed again before this answer was applied")
    assert _participant(eid)["pin"] == before, "nothing was re-pinned"
    newer = second["subject"]
    assert newer["pin_old"] == first["subject"]["pin_old"] == pin_digest(before)
    assert newer["pin_new"] != first["subject"]["pin_new"]
    thinking = {ch["key"]: ch for ch in newer["settings_changes"]}["thinking"]
    assert (thinking["old"], thinking["new"]) == ("medium", "low")
    assert _prompts() == 1 and _owner_messages(eid, HELD) == 0

    _go_on(pw_run, eid, second)
    pw.wait_parked(state, eid, 4)
    sup.open_wait(eid, "owner", other_than=owner["wait_id"])
    assert pin_digest(_participant(eid)["pin"]) == newer["pin_new"]
    assert _owner_messages(eid, HELD) == 1
    assert [s["thinking"] for s in FakeBox.STARTS] == ["medium", "low"]


# --- 6. a team ---------------------------------------------------------------------------------


def _team_wait(tr, eid: str, kind: str) -> dict:
    """The team's open wait of ``kind``, once it is asked."""
    def find():
        rows = [w for w in runs.team_waits(tr, eid) if w["state"] == "open"
                and w["kind"] == kind and w["gate_name"] == f"{runs.HOST}~ask-{w['wait_id']}"]
        return rows[0] if rows else None
    return sup.wait_for(find, what=f"an open {kind} wait in {eid}")


def _install(tr, **stage) -> None:
    agents = stage.pop("agents_cfg", None)
    runs.install(tr, tt.team_stage(strategy_config=runs.PAUSE_1, **stage),
                 outputs=runs.OUTPUTS, agents=agents)


def _team_pins(tr, eid: str) -> dict[str, dict]:
    return {p["member"]: p for p in ts.rows(tr.led, eid, runs.HOST)["participants"]}


def _team_reopened_at_settings(tr) -> tuple[str, dict, dict, dict, dict]:
    """A team paused after round 1; a deploy changes qa's agent config (thinking high); the
    owner's continue reopens it at the team's settings wait. Returns (run, the pause wait,
    the settings wait, its event as the gates list has it, the members' rows before)."""
    _install(tr)
    runs.script(tr.led, ["keep_going", "done"])
    eid = runs.start(tr, {"goal": runs.GOAL})
    pause, gate = runs.parked_at(tr, eid, 1, "settings_pause")
    members = _team_pins(tr, eid)
    _install(tr, agents_cfg={"agent:qa": {**QA, "thinking": "high"}})
    assert runs.answer(tr, eid, pause, gate, "continue")["carries_on"] is True
    attempt = pw.wait_parked(tr.state, eid, 2)
    wait = _team_wait(tr, eid, "settings")
    assert pw.parked(attempt)["wait_id"] == wait["wait_id"]
    return eid, pause, wait, pw.open_gate(tr.client, eid, wait["gate_name"]), members


def test_6_a_member_changed_while_paused_asks_one_team_settings_wait_and_go_on_finishes(tr):
    eid, pause, wait, gate, members = _team_reopened_at_settings(tr)
    subject = wait["subject"]
    changes = subject["settings_changes"]
    assert [(ch["scope"], ch["member"], ch["key"], ch["value_kind"]) for ch in changes] == [
        ("member", "qa", "agent_config_sha256", "sha256"), ("member", "qa", "thinking", "text")]
    thinking = changes[1]
    assert thinking["new"] == "high" and thinking["old"] == members["qa"]["pin"]["thinking"]
    assert subject["pins"] == [{"member": "qa",
                                "participant_id": members["qa"]["participant_id"],
                                "pin_old": pin_digest(members["qa"]["pin"]),
                                "pin_new": subject["pins"][0]["pin_new"]}]
    assert "qa: agent config" in subject["question"]
    qa_pins = subject["pins"][0]
    assert (f"Settings fingerprints: qa {qa_pins['pin_old'][:12]} -> {qa_pins['pin_new'][:12]}."
            in subject["question"])
    # asked first: nothing ran and the pause's answer is held
    assert runs.prompts() == {"design": 2, "frontend": 1, "qa": 1}
    assert {w["kind"]: w["state"] for w in runs.team_waits(tr, eid)} == {
        "pause": "open", "settings": "open"}

    runs.pick(tr, eid, wait, gate, "go on")
    attempts = pw.wait_ended(eid, 3)
    assert [a["status"] for a in attempts] == ["parked", "parked", "completed"], \
        runs.stage_error(eid, "build")
    out = attempts[-1]["data"]["workflow_output"]
    assert out["decision"] == "done" and out["cost"]["cost_usd"] == 100.0
    now = _team_pins(tr, eid)
    assert now["qa"]["pin"]["thinking"] == "high"
    assert pin_digest(now["qa"]["pin"]) == subject["pins"][0]["pin_new"]
    assert now["design"]["pin"] == members["design"]["pin"]
    rows = {w["kind"]: w for w in runs.team_waits(tr, eid)}
    assert (rows["settings"]["decision"]["answer"], rows["settings"]["decision"]["applied"]) == (
        "go on", True)
    assert rows["pause"]["decision"]["answer"] == "continue"
    assert rows["settings"]["decided_at"] <= rows["pause"]["decided_at"]
    assert runs.prompts() == {"design": 4, "frontend": 2, "qa": 2}


def test_6_a_stop_at_the_team_settings_wait_ends_it_stopped_and_the_run_cancelled(tr):
    eid, pause, wait, gate, members = _team_reopened_at_settings(tr)
    r = pw.approve(tr.client, eid, wait["gate_name"], event_id=gate["event_id"],
                   response="stop")
    assert r.status_code == 200, r.text
    attempts = pw.wait_ended(eid, 3)
    assert [a["status"] for a in attempts] == ["parked", "parked", "cancelled"]
    assert runs.stage_row(eid)[-1] == "cancelled" and runs.team_row(eid)[-1] == "cancelled"
    assert f"{TEAM_STOPPED} (qa: agent_config_sha256, thinking)" in runs.stage_error(
        eid, "build")
    assert "Workflow cancelled by user" not in str(attempts[-1])
    assert attempts[-1]["data"]["workflow_output"]["decision"] == "stopped"
    snap = ts.rows(tr.led, eid, runs.HOST)
    assert {p["ended_reason"] for p in snap["participants"]} == {"team_stopped"}
    assert {w["kind"]: w["state"] for w in snap["waits"]} == {
        "pause": "cancelled", "settings": "decided"}, "the held continue was never applied"
    assert runs.prompts() == {"design": 2, "frontend": 1, "qa": 1}
    assert _team_pins(tr, eid)["qa"]["pin"] == members["qa"]["pin"]


def test_6_a_changed_member_set_is_still_refused(tr):
    _install(tr)
    runs.script(tr.led, ["keep_going", "done"])
    eid = runs.start(tr, {"goal": runs.GOAL})
    pause, gate = runs.parked_at(tr, eid, 1, "member_set_pause")
    _install(tr, agents=["design", "frontend"])  # qa left the team
    assert runs.answer(tr, eid, pause, gate, "continue")["carries_on"] is True
    attempts = pw.wait_ended(eid, 2)
    assert attempts[-1]["status"] == "failed"
    assert ("team settings changed since the team started (members); refusing to reopen its "
            "conversations") in runs.stage_error(eid, "build")
    assert [w["kind"] for w in runs.team_waits(tr, eid)] == ["pause"], "no settings wait"


# --- 7. the Team page's API ----------------------------------------------------------------------


def _trial_reopened_at_settings(api) -> tuple[str, dict, dict]:
    """A trial paused after round 1; a deploy changes the identity extension (every member's
    pin); the owner's continue reopens it at the team's settings wait."""
    runs.script(api.led, ["keep_going", "done"])
    eid = team_api.start_trial(api, team_api.body(api))["execution_id"]
    pause = team_api.parked(api, eid, 1)
    assert pause["kind"] == "pause"
    _change_extension("SECRET-EXT-7")
    r = team_api.answer(api, eid, pause["wait_id"], "continue", rid="p-1")
    assert r.status_code == 200, r.text
    return eid, pause, team_api.parked(api, eid, 2)


def _owner_answers(run: dict) -> list[tuple[str, str]]:
    return [(e["wait_kind"], e["data"]["answer"]) for e in run["timeline"]["entries"]
            if e["entry"] == "owner_answer"]


def test_7_the_api_shows_the_settings_wait_then_the_settings_answer_and_the_held_one_once(api):
    eid, pause, wait = _trial_reopened_at_settings(api)
    run = team_api.team_run(api, eid)
    assert run["state"] == "settings_changed"
    assert (wait["kind"], wait["asked"], wait["asked_again"]) == ("settings", True, 0)
    assert [(a["answer"], a["needs_text"]) for a in wait["answers"]] == [
        ("go on", "none"), ("stop", "optional")]
    assert wait["reply_hint"] == "Reply 'go on' or 'stop'." and "Reply" not in wait["question"]
    changes = wait["settings_changes"]
    assert [(ch["scope"], ch["member"], ch["key"], ch["value_kind"]) for ch in changes] == [
        ("member", m, "extensions.identity", "sha256") for m in ("design", "frontend", "qa")]
    assert all(HEX64.match(ch["old"]) and HEX64.match(ch["new"]) and ch["old"] != ch["new"]
               for ch in changes)
    assert [p["member"] for p in wait["pins"]] == ["design", "frontend", "qa"]
    assert all(set(p) == {"member", "pin_old", "pin_new"} and HEX64.match(p["pin_old"])
               and HEX64.match(p["pin_new"]) for p in wait["pins"])
    assert "SECRET-EXT" not in json.dumps(run)
    assert [(w["kind"], w["asked"]) for w in run["open_waits"]] == [
        ("settings", True), ("pause", False)]
    others = [w for w in run["open_waits"] if w["kind"] != "settings"]
    assert all(w["settings_changes"] is None and w["pins"] is None for w in others)
    assert _owner_answers(run) == [], "the pause's continue is held, not applied"
    (item,) = api.client.get("/api/team/trials").json()["trials"]
    assert item["state"] == "settings_changed"
    # the held pause can't be answered past the settings wait
    r = team_api.answer(api, eid, pause["wait_id"], "continue", rid="p-2")
    assert r.status_code == 409, r.text

    r = team_api.answer(api, eid, wait["wait_id"], "go on", rid="s-1")
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 3)[-1]["status"] == "completed"
    run = team_api.team_run(api, eid)
    assert _owner_answers(run) == [("settings", "go on"), ("pause", "continue")]
    assert run["outcome"]["decision"] == "done"


def test_7_after_a_settings_stop_the_api_never_shows_the_held_answer_applied(api):
    eid, pause, wait = _trial_reopened_at_settings(api)
    r = team_api.answer(api, eid, wait["wait_id"], "stop", "not on these settings", rid="s-2")
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 3)[-1]["status"] == "cancelled"
    run = team_api.team_run(api, eid)
    assert (run["run_status"], run["state"]) == ("cancelled", "stopped")
    out = run["outcome"]
    assert (out["decision"], out["owner_words"]) == ("stopped", "not on these settings")
    assert out["reason"] == (f"{TEAM_STOPPED} (design: extensions.identity; frontend: "
                             "extensions.identity; qa: extensions.identity)")
    assert _owner_answers(run) == [("settings", "stop")]
    assert run["open_waits"] == []
