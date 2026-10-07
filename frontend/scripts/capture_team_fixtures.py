#!/usr/bin/env python3
"""Capture the Team page's test fixtures from the real ``/api/team`` routes.

Run it from the repository root:

    uv run python frontend/scripts/capture_team_fixtures.py

It starts no server and calls no model. The routes run on an in-process Temper with the Pi
switch on and scripted Pi members: the harness of
``tests/test_runner/pi_parking/test_team_api.py`` (and ``test_team_outcomes.py`` for the
endings). Each scenario drives a trial to one state and saves what the routes answered, one
JSON file per state and per refusal, in ``frontend/e2e/fixtures/team/``:

    {"route": "GET /api/team/runs/{execution_id}", "status": 200, "body": {...}}

States the harness can't reach are derived from a captured file afterwards, changing only
the fields that differ; ``README.md`` in that folder lists each one and why. Every name,
goal, role and path is made up, and temporary paths are rewritten to ``/srv/example/...``
before anything is written.

One group can be captured again on its own, leaving every other file as it is:

    uv run python frontend/scripts/capture_team_fixtures.py --only journey

runs only ``test_journey`` and rewrites only ``journey-*.json`` (the Team page journey's).
"""

from __future__ import annotations

import copy
import getpass
import json
import os
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend" / "e2e" / "fixtures" / "team"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Text that must never reach a fixture (temper-ai is public): host paths, the account name
#: of whoever runs the capture (as a whole word, when it is long enough to mean something),
#: and chat details.
_USER = getpass.getuser()
FORBIDDEN = re.compile(
    "|".join(
        [r"/home/", r"/tmp/", r"pytest-of-", r"/Users/", r"homeChat", r"\.jsonl"]
        + ([rf"\b{re.escape(_USER)}\b"] if len(_USER) >= 5 else [])
    )
)


def write(name: str, data: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8")


def read(name: str) -> dict:
    return json.loads((OUT / f"{name}.json").read_text(encoding="utf-8"))


#: Design's stress board: six members, one with a 40-character name.
STRESS_MEMBERS = (("frontend", "frontend"), ("a-very-long-team-name-for-the-stress-40c", "backend"),
                  ("qa", "qa"), ("design", "design"), ("docs", "docs"),
                  ("security", "security"))
STRESS_GOAL = ('Check that goals render as text: <script>alert("boards")</script> '
               "<b>not bold</b> & <img src=x onerror=alert(1)>\n\nSecond paragraph of the goal.")
STRESS_ENTRIES = 400  # the run view's most (VIEW_LIMIT)
STRESS_NOT_SHOWN = 1234


def _renamed(value, names: dict[str, str]):
    """``value`` with every member name (as a whole string or a key) swapped."""
    if isinstance(value, dict):
        return {names.get(k, k): _renamed(v, names) for k, v in value.items()}
    if isinstance(value, list):
        return [_renamed(v, names) for v in value]
    if isinstance(value, str):
        return names.get(value, value)
    return value


def stress(running: dict, done: dict) -> dict:
    """The running run at the page's limits: six members in every activity (one with a
    failed turn, one whose turns used another model), 400 entries with more not shown, and a
    goal with text that looks like HTML. A layout check, not a state of its own."""
    from datetime import datetime, timedelta

    out = copy.deepcopy(running)
    body = out["body"]
    trial_member = body["trial"]["members"][0]
    member = body["members"][0]
    body["trial"]["goal"] = STRESS_GOAL
    body["trial"]["leader"] = STRESS_MEMBERS[0][0]
    body["trial"]["members"] = [{**trial_member, "name": name, "role": role, "leader": i == 0}
                                for i, (name, role) in enumerate(STRESS_MEMBERS)]
    numbers = (("idle", 14, 3.10), ("working", 9, 2.20), ("waiting_on_owner", 8, 1.90),
               ("failed", 5, 1.10), ("idle", 3, 0.60), ("ended", 2, 0.50))
    members = []
    for (name, role), (activity, turns, cost) in zip(STRESS_MEMBERS, numbers, strict=True):
        last = {**(member["last_turn"] or {}), "turn_no": turns, "error": None,
                "state": "running" if activity == "working" else "completed"}
        effective = {"model": member["model"], "thinking": member["thinking"]}
        if activity == "failed":
            last.update(state="failed", error="the worker box closed the session: exit code "
                                                 "137 (out of memory)")
        if name == "docs":
            effective = {"model": "claude-sonnet-5", "thinking": "high"}
        members.append({**member, "name": name, "role": role, "leader": name == "frontend",
                        "activity": activity, "turns": turns, "cost_usd": cost,
                        "effective": effective, "last_turn": last})
    body["members"] = members

    source = done["body"]["timeline"]["entries"]
    others = [name for name, _ in STRESS_MEMBERS[1:]]
    start = datetime.fromisoformat(source[0]["timestamp"])
    entries = []
    for i in range(STRESS_ENTRIES):
        cycle, entry = i // len(source), source[i % len(source)]
        names = {"lead": "frontend", "maker": others[cycle % 5],
                 "checker": others[(cycle + 2) % 5]}
        entry = _renamed(copy.deepcopy(entry), names)
        entry["timestamp"] = (start + timedelta(seconds=20 * i)).isoformat()
        data = entry.get("data") or {}
        if entry.get("entry") == "message":
            data["message_id"] = f"{data['message_id'][:28]}{i:04x}"
            words = f"Stress message {i}: " + "lorem ipsum dolor sit amet " * 8
            data["preview"] = words[:160] + "..."
        entries.append(entry)
    body["timeline"] = {"entries": entries, "not_shown": STRESS_NOT_SHOWN}
    return out


def derive() -> None:
    """Fixtures for states the in-process harness can't reach, each from a captured one;
    README.md lists them. Only the fields contract section 5 says differ are changed."""
    running = read("run-running")
    write("run-stress", {**stress(running, read("run-done")), "derived_from": "run-running"})

    # starting: the run is up but no member turn has begun yet (team_state: not began).
    starting = copy.deepcopy(running)
    body = starting["body"]
    body["state"] = "starting"
    body["round"]["current"] = 0
    body["round"]["keep_goings"] = 0
    body["reviews"] = []
    body["timeline"] = {"entries": [e for e in body["timeline"]["entries"]
                                  if e.get("event_type") == "message: goal"], "not_shown": 0}
    for member in body["members"]:
        for field, value in (("turns", 0), ("cost_usd", 0.0), ("activity", "idle"),
                             ("last_turn_at", None)):
            if field in member:
                member[field] = value
    body["owner_actions"] = [a for a in body["owner_actions"] if a["kind"] == "start"]
    write("run-starting", {**starting, "derived_from": "run-running"})

    # interrupted: the run's own status is interrupted (a restart cut it off); team_state
    # reads it before any wait.
    interrupted = copy.deepcopy(running)
    interrupted["body"]["run_status"] = "interrupted"
    interrupted["body"]["state"] = "interrupted"
    write("run-interrupted", {**interrupted, "derived_from": "run-running"})

    # member_waiting for a member's question: the captured question waits behind the pause
    # (E12); here it is the one Temper asks.
    two = read("run-paused-two-waits")
    question = copy.deepcopy(two)
    qbody = question["body"]
    first, second = qbody["open_waits"]
    second["asked"] = True
    second["event_id"] = first["event_id"]
    qbody["open_waits"] = [second]
    qbody["state"] = "member_waiting"
    write("run-member-waiting-question", {**question, "derived_from": "run-paused-two-waits"})

    # trials error: the list could not be read (any 5xx; FastAPI's own body).
    write("trials-error", {"route": "GET /api/team/trials", "status": 500,
                           "body": "Internal Server Error", "derived_from": "trials-list"})

    # refusals the harness can't reach in order (an unasked question can't be answered, so
    # its own reply checks never run there): the texts are landed-48's, word for word.
    member = second.get("member") or "maker"
    refused = read("answer-400-guide-needs-words")
    write("answer-400-reply-needs-words", {
        **refused, "body": {"problem": f"'reply' needs the words to pass to {member}"},
        "derived_from": "answer-400-guide-needs-words"})
    write("answer-400-reply-too-long", {
        **refused,
        "body": {"problem": "the reply is too long (20001 characters; at most 20000)"},
        "derived_from": "answer-400-guide-needs-words"})
    ended = read("message-409-team-ended")
    write("message-409-team-not-started", {
        **ended, "body": {"reason": "team_not_started",
                          "message": "the team has not started yet; nothing was sent"},
        "derived_from": "message-409-team-ended"})
    write("message-409-member-ended", {
        **ended, "body": {"reason": "member_ended",
                          "message": "'checker' has left the team; nothing was sent"},
        "derived_from": "message-409-team-ended"})

    derive_part_b()
    derive_part_c()

    # 403: a run's own key tried an owner action (caller.py's words for a box's powers).
    from temper_ai.api import caller

    says = caller._RUN_KEY_SAYS.get(caller.BOX_ACTIONS) or " and ".join(
        sorted(caller.BOX_ACTIONS))
    for name, action, src in (("answer-403", "approve", "answer-401"),
                              ("message-403", "approve", "message-401"),
                              ("trial-start-403", "start", "trial-start-401")):
        base = read(src)
        write(name, {**base, "status": 403,
                     "body": {"detail": f"A run's own key may only {says}, not {action}."},
                     "derived_from": src})


def derive_part_b() -> None:
    """Part B's states the harness can't reach in process: a send kept while the run isn't
    running, a gate refusal the scenarios don't hit, who stopped a run from elsewhere, the
    other ways a done run's branch ends, and the other ways a team fails. Every text is the
    engine's own (the function or the format it writes with)."""
    from temper_ai.api.routes import NEEDS_RESUME
    from temper_ai.stage.gate import REJECTED, REPLACED, refusal

    # needs_resume: the answer is kept but the run is not running (the route's own words).
    guided = read("answer-200-guide")
    write("answer-200-needs-resume", {
        **guided, "body": {**guided["body"], "carries_on": False, "needs_resume": True,
                           "message": NEEDS_RESUME},
        "derived_from": "answer-200-guide"})

    # replaced: a later wait took this one's place (the gate's own refusal for that status).
    answered = read("answer-409-already-answered")
    gate = {k: v for k, v in answered["body"].items()
            if k not in ("message", "reason", "answered_source")}
    write("answer-409-replaced", {
        **answered, "body": {**refusal({**gate, "status": REPLACED, "answered_by": None,
                                         "answered_at": None}),
                             "answered_source": "unknown"},
        "derived_from": "answer-409-already-answered"})
    # already rejected: the run was stopped at this question (Stop run from the run page).
    write("answer-409-already-rejected", {
        **answered, "body": {**refusal({**gate, "status": REJECTED}), "answered_source": "run_page"},
        "derived_from": "answer-409-already-answered"})

    # who stopped it (R12v): the CI key through the API, a caller Temper can't name, a chat.
    for src, kind in (("run-stopped", "answer"), ("run-cancelled", "stop")):
        for slug, by, source in (("by-ci", "temper-ci", "api"),
                                 ("by-unknown", "unknown caller", "unknown"),
                                 ("from-chat", "owner", "chat")):
            out = copy.deepcopy(read(src))
            body = out["body"]
            body["outcome"]["by"] = by
            stops = set()
            for action in body["owner_actions"]:
                if action["kind"] == kind:
                    action["by"], action["source"] = by, source
                    stops.add(action["request_id"])
            # The timeline's answer to the same question names the same caller and place.
            for entry in body["timeline"]["entries"]:
                if entry.get("entry") == "owner_answer" and entry.get("request_id") in stops:
                    for record in (entry, entry["data"]):
                        record["answered_by"], record["answered_source"] = by, source
            write(f"{src}-{slug}", {**out, "derived_from": src})

    # a done run's branch: not made (the name was taken), and no project at all.
    done = read("run-done")
    taken = copy.deepcopy(done)
    taken["body"]["outcome"]["done"]["branch"].update(made=False, why="exists")
    write("run-done-branch-not-made", {**taken, "derived_from": "run-done"})
    empty = copy.deepcopy(done)
    empty["body"]["trial"]["project"] = None
    empty["body"]["outcome"]["done"]["branch"] = None
    write("run-done-no-project", {**empty, "derived_from": "run-done"})

    # the other ways a team fails (R14v), in team_leader.py's words.
    problems = [p["text"] for p in read("check-project-dirty")["body"]["problems"]]
    problems += ["member 'checker': Bash is off until owner-only writes are enforced (#45)"]
    failed = read("run-failed")
    for slug, reason, listed in (
            ("cant-go-on", "the team can't go on: " + "; ".join(problems), problems),
            ("copies", "the team's project copies could not be made: git clone exited 128: "
                       "fatal: repository '/srv/example/projects/notes-app' does not exist", []),
            ("cant-open", "the team can't open: another attempt holds the team", []),
            ("recorder", "the team needs the run's event recorder and the worker box config", [])):
        out = copy.deepcopy(failed)
        out["body"]["outcome"].update(reason=reason, problems=listed)
        write(f"run-failed-{slug}", {**out, "derived_from": "run-failed"})

    # S4: a 4,000-character summary and 500 files in the approved version.
    big = copy.deepcopy(done)
    line = "The team rewrote the importer in small steps, each reviewed. "
    summary = "## What changed\n\n" + line * 30 + "\n\n## Still open\n\n"
    summary += "".join(f"- step {i}: <b>not bold</b> stays text\n" for i in range(1, 60))
    big["body"]["outcome"]["done"]["summary"] = summary[:4000]
    big["body"]["outcome"]["done"]["files"] = [
        {"path": f"src/importer/step_{i:03}.py", "sha256": f"{i:064x}"} for i in range(500)]
    write("run-done-big", {**big, "derived_from": "run-done"})

    # S7: HTML in the owner's words and in a member's question stays text.
    html = "Stop. <script>alert('boards')</script> <b>bold?</b> <img src=x onerror=alert(1)> & thanks"
    stopped = copy.deepcopy(read("run-stopped"))
    stopped["body"]["outcome"]["owner_words"] = html
    write("run-stopped-script", {**stopped, "derived_from": "run-stopped"})
    asking = copy.deepcopy(read("run-member-waiting-question"))
    for wait in asking["body"]["open_waits"]:
        wait["question"] = "Should the note say " + html + "?"
    write("run-member-waiting-question-script",
          {**asking, "derived_from": "run-member-waiting-question"})


def _example_digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(f"EXAMPLE-{text}".encode()).hexdigest()


def derive_part_c() -> None:
    """Part C's states the harness can't reach in process: a trial's re-run and fork from the
    run page (A-8), the settings wait at its limits (S8: 30 changes, a 40-character member
    name, every kind of value, one setting removed) and a long question waiting behind the
    asked one (R16). The settings question and its typed fields are the engine's own
    (``settings_wait.team_subject``)."""
    from datetime import datetime, timedelta

    from temper_ai.pi_agent import settings_wait as sw

    # A-8: a trial's re-run and fork from the run page follow its own run, newest first, each
    # with its own run, state, round, cost and caller.
    listed = copy.deepcopy(read("trials-list"))
    items = listed["body"]["trials"]
    at = next(i for i, t in enumerate(items) if t["state"] == "stopped")
    own = items[at]
    began = datetime.fromisoformat(own["started_at"])
    rerun = {**own, "execution_id": "3eacb8a3-5c1d-4e0f-9a7b-2d6c8e1f4a90", "state": "running",
             "run_status": "running", "decision": None, "round": 1, "cost_usd": 0.18,
             "started_at": (began + timedelta(hours=2)).isoformat(), "started_by": "owner",
             "ended_at": None}
    fork = {**own, "execution_id": "9b1e7c42-0d3a-4f6b-8e25-71c0a4d9b3e6", "state": "done",
            "run_status": "completed", "decision": "done", "round": 2, "cost_usd": 0.37,
            "started_at": (began + timedelta(hours=1)).isoformat(), "started_by": "owner",
            "ended_at": (began + timedelta(hours=1, minutes=12)).isoformat()}
    items[at + 1:at + 1] = [rerun, fork]
    listed["body"]["total"] = len(items)
    write("trials-with-reruns", {**listed, "derived_from": "trials-list"})

    # S8: the settings wait at its limits. The leader is renamed to the stress board's
    # 40-character name everywhere; its 24 add-ons changed (one of them removed), the
    # checker's model, four of the maker's settings, and the team's own settings.
    out = copy.deepcopy(read("run-settings-changed"))
    long_name = STRESS_MEMBERS[1][0]
    out["body"] = _renamed(out["body"], {"lead": long_name})
    team_old, team_new = _example_digest("team-old"), _example_digest("team-new")
    many_old = {"team": team_old, "model": "claude-opus-5-5",
                "add_ons": {f"addon-{i:02}": _example_digest(f"addon-{i}-old") for i in range(24)}}
    many_new = {"team": team_new, "model": "claude-opus-5-5",
                "add_ons": {f"addon-{i:02}": _example_digest(f"addon-{i}-new") for i in range(23)}}
    changed = [
        (long_name, "p-lead", many_old, many_new),
        ("checker", "p-checker", {"team": team_old, "model": "claude-sonnet-x"},
         {"team": team_new, "model": "claude-sonnet-y"}),
        ("maker", "p-maker",
         {"team": team_old, "add_ons": {"pi-tldr": _example_digest("tldr-old")},
          "agent_config_sha256": _example_digest("config-old"),
          "image": "sha256:" + _example_digest("image-old"), "pi_version": "0.87.1"},
         {"team": team_new, "add_ons": {"pi-tldr": _example_digest("tldr-new")},
          "agent_config_sha256": _example_digest("config-new"),
          "image": "sha256:" + _example_digest("image-new"), "pi_version": "0.88.0"}),
    ]
    subject = sw.team_subject(changed)
    assert len(subject["settings_changes"]) == 30, len(subject["settings_changes"])
    wait = out["body"]["open_waits"][0]
    assert wait["kind"] == "settings", wait["kind"]
    wait.update(question=subject["question"], settings_changes=subject["settings_changes"],
                pins=[{k: p[k] for k in ("member", "pin_old", "pin_new")}
                      for p in subject["pins"]])
    write("run-settings-stress", {**out, "derived_from": "run-settings-changed"})

    # R16: the question waiting behind the asked one is long; the card shows two lines of it
    # and says how to read the rest.
    two = copy.deepcopy(read("run-paused-two-waits"))
    behind = two["body"]["open_waits"][1]
    behind["question"] = (
        "Before I write the empty-state copy: should the note say where the New note button "
        "is (top right on a laptop, bottom right on a phone), or should it only say what a "
        "note is for? The design board shows both versions. The first helps someone who "
        "opens the app for the first time; the second stays true if the button moves. I "
        "lean to the first, with the phone wording checked on a narrow screen, but the "
        "leader asked for the shortest text that still tells a new user what to do first.")
    write("run-paused-long-next", {**two, "derived_from": "run-paused-two-waits"})

    # A wait of a kind this page doesn't know: it shows under the generic "Temper is waiting
    # for you" with Temper's own question and answers (the contract's fallback).
    paused = copy.deepcopy(read("run-paused"))
    needs = {a["answer"]: a["needs_text"] for a in paused["body"]["open_waits"][0]["answers"]}
    paused["body"]["open_waits"][0].update(
        kind="budget", header="budget", round=None, member=None, turn_no=None, why=None,
        question="The team has spent $5.00, its budget for this trial. Raise the budget, or "
                 "stop the team?",
        answers=[{"answer": "raise", "needs_text": needs["guide"],
                  "means": "The team carries on with the budget you give, in US dollars."},
                 {"answer": "stop", "needs_text": needs["stop"],
                  "means": "The team stops here and the run ends cancelled. Any words you give "
                           "are kept with it."}])
    write("run-unknown-wait", {**paused, "derived_from": "run-paused"})


def check_clean() -> None:
    for path in sorted(OUT.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        found = FORBIDDEN.search(text)
        assert found is None, f"{path.name}: {found.group(0)!r} must not be in a fixture"


#: Groups that ``--only`` can capture again on their own: the test that makes them.
ONLY = {"journey": "test_journey"}


def main(argv: list[str] | None = None) -> int:
    import pytest

    args = sys.argv[1:] if argv is None else argv
    only = args[1] if len(args) == 2 and args[0] == "--only" else None
    if args and only not in ONLY:
        print(f"usage: capture_team_fixtures.py [--only {'|'.join(ONLY)}]", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob(f"{only}-*.json" if only else "*.json"):
        old.unlink()
    code = pytest.main([str(Path(__file__).resolve()), "-q", "-x", "-p", "no:cacheprovider",
                        "-p", "tests.conftest", "-p", "tests.test_runner.pi_parking.conftest",
                        "-c", str(ROOT / "pyproject.toml"), "--rootdir", str(ROOT),
                        "-o", "timeout=600"] + (["-k", ONLY[only]] if only else []))
    if code != 0:
        return int(code)
    if not only:
        derive()
    check_clean()
    print(f"{len(list(OUT.glob('*.json')))} fixtures in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# --- the scenarios (collected by pytest, through main()) -----------------------------------

import pytest  # noqa: E402

from temper_ai.pi_agent.ledger import waits  # noqa: E402
from tests.test_pi_agent import support as sup  # noqa: E402
from tests.test_pi_agent import test_team as tt  # noqa: E402
from tests.test_runner.pi_parking import support as pw  # noqa: E402
from tests.test_runner.pi_parking import test_team_api as ta  # noqa: E402
from tests.test_runner.pi_parking import test_team_runs as runs  # noqa: E402
from tests.test_runner.pi_team import leader_support as ls  # noqa: E402
from tests.test_runner.pi_team import support as ts  # noqa: E402

team_on = tt.team_on
tr = runs.tr
api = ta.api

THOST = ta.THOST
OWNER_KEY = ta.OWNER_KEY
CI_KEY = ta.CI_KEY
ORIGIN = {"Origin": "http://testserver"}

RUN = "GET /api/team/runs/{execution_id}"
ANSWER = "POST /api/team/runs/{execution_id}/waits/{wait_id}/answer"
MESSAGE = "POST /api/team/runs/{execution_id}/messages"
READ = "GET /api/team/runs/{execution_id}/messages/{message_id}"
TRIALS = "GET /api/team/trials"
START = "POST /api/team/trials"
CHECK = "POST /api/team/check"
CANCEL = "POST /api/runs/{execution_id}/cancel"

GOAL = ("Write a short welcome note for the notes app's first screen.\n\n"
        "Keep it under 80 words, friendly and plain. Say that notes save on their own, and "
        "that nothing is shared until you choose to share it.")
WELCOME = "# Welcome\n\nYour notes save on their own. Nothing is shared until you share it.\n"
DRAFTS = ["# Welcome to Notes, the app where every note you write is kept safe\n",
          "# Welcome\n\nNotes save themselves.\n"]
REVIEW_NOTES = ["first draft of the welcome note", "shorter heading, one line of help",
                "final wording"]
MAKER_VIEWS = ["The heading wraps to three lines on a phone. Try four words or fewer.",
               "Better. The second line could say what happens to shared notes.",
               "Reads well and fits on a small screen."]
CHECKER_VIEWS = ["A new user won't know notes save on their own; say it in the first line.",
                 "Clear now. 'Notes save themselves' sounds odd; maybe 'Your notes save on "
                 "their own'.",
                 "Good: short, plain, and it answers the two questions people ask first."]
SUMMARIES = ["Round 1: the heading is too long and saving isn't explained. Shortening it.",
             "Round 2: close. Rewording the saving line and adding the sharing line.",
             "Done: the note is short, plain and says how saving and sharing work."]
LONG_MESSAGE = (
    "Before you review: the first screen has room for about six lines at 360 pixels wide, "
    "so anything past 80 words gets cut off behind the New note button. I measured the "
    "draft at 64 words, which fits, but the heading wraps to three lines because it is a "
    "whole sentence. If you suggest changes, please keep the two promises in this order: "
    "saving first, then sharing. That is the order people asked about in the last round of "
    "interviews, and the help page uses the same order, so the two will read alike.")
OWNER_HELD = "Please keep the note under 60 words if you can; the screen is small."
OWNER_PENDING = "When you get to it, check the note on a narrow phone too."

#: The Team page journey (frontend/e2e/team-journey.ts) types its tag first in the goal and
#: in the message, in these words; the gated journey is given this tag.
JOURNEY_TAG = "journey-2026-01-01T09:00:00.000Z"
JOURNEY_GOAL = f"{JOURNEY_TAG}\n\nA practice run of the Team page journey."
JOURNEY_MESSAGE = f"{JOURNEY_TAG} A message from the Team page journey."

ROLES = {
    "planner": ("Planner", "# Planner\n\nTurns a goal into a short plan and keeps each version "
                           "small.\n\n- Writes the first draft\n- Asks the others to review each "
                           "version\n- Decides when the work is done\n"),
    "builder": ("Builder", "# Builder\n\nMakes the change the plan asks for, with a test next "
                           "to it.\n"),
    "reviewer": ("Reviewer", "# Reviewer\n\nReads each version as a new user would and says "
                             "what is unclear.\n"),
    "scribe": ("Scribe", None),  # no about page: the role shows its problem
}


class Saver:
    """Writes what a route answered, with every temporary path made up."""

    def __init__(self, team) -> None:
        self.subs = [(str(team.ws), "/srv/example/projects/notes-app"),
                     (str(team.tmp), "/srv/example/scratch")]

    def clean(self, value):
        text = json.dumps(value, ensure_ascii=False)
        for old, new in self.subs:
            text = text.replace(old, new)
        return json.loads(text)

    def save(self, name: str, route: str, response) -> dict | str:
        try:
            body = response.json()
        except ValueError:
            body = response.text
        write(name, {"route": route, "status": response.status_code, "body": self.clean(body)})
        return body


@pytest.fixture
def team(api, monkeypatch, tmp_path):
    """The Team page's routes with made-up roles (no real role's about page)."""
    roles = tmp_path / "example-roles"
    for rid, (title, about) in ROLES.items():
        folder = roles / rid
        folder.mkdir(parents=True)
        (folder / "identity.json").write_text(json.dumps(
            {"id": rid, "title": title, "homeChat": f"/srv/example/sessions/{rid}.chat"}))
        if about is not None:
            (folder / "about.md").write_text(about)
        (folder / "notebook.md").write_text("## Rules\n")
    path = tt.team_box_json(tmp_path / "example-box", identities_dir=str(roles))
    monkeypatch.setenv("TEMPER_PI_BOX_CONFIG", str(path))
    api.saver = Saver(api)
    return api


def trial(team, rid: str, **over) -> dict:
    raw = {"request_id": rid, "goal": GOAL, "leader": "lead", "pause_after_rounds": 3,
           "members": [{"name": "lead", "role": "planner"},
                       {"name": "maker", "role": "builder", "tools": ["Read", "Edit", "Write"]},
                       {"name": "checker", "role": "reviewer", "tools": ["Read", "Grep"]}],
           "project_path": str(team.ws)}
    raw.update(over)
    return raw


def rounds(led, decisions: list[str], *, last_views: str = "satisfied") -> None:
    """lead writes a version and asks for a review; maker and checker each give a view; lead
    decides each round in its own turn. In the last round maker also sends checker a long note
    (earlier, it would wake checker for a turn its script has no place for)."""
    lead, maker, checker = [], [], []
    for i, decision in enumerate(decisions):
        verdict = last_views if decision == "done" else "changes"
        text = WELCOME if decision == "done" else DRAFTS[min(i, len(DRAFTS) - 1)]
        lead.append([ls.write("WELCOME.md", text), ls.request_review(REVIEW_NOTES[i])])
        view = [ls.give_view(led, None, verdict, MAKER_VIEWS[i])]
        if i == len(decisions) - 1:
            view.insert(0, ts.send("checker", LONG_MESSAGE))
        maker.append(view)
        checker.append([ls.give_view(led, None, verdict, CHECKER_VIEWS[i])])
        lead.append([ls.decide(led, None, decision, SUMMARIES[i])])
    ts.SCRIPTS["lead"], ts.SCRIPTS["maker"], ts.SCRIPTS["checker"] = lead, maker, checker


def start(team, raw: dict, *, auth: str | None = None) -> dict:
    return ta.start_trial(team, raw, auth=auth)


def run(team, eid: str):
    return team.client.get(f"/api/team/runs/{eid}")


def save_run(team, name: str, eid: str) -> dict:
    return team.saver.save(name, RUN, run(team, eid))


def first_message(view: dict, *, sender: str | None = None) -> dict:
    found = [e for e in view["timeline"]["entries"] if e["entry"] == "message"
             and (sender is None or e.get("from_agent") == sender)]
    assert found, view["timeline"]["entries"]
    return found[0]


class Hold:
    """A member's turn that waits mid-turn until the capture is done (the running state)."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.release = threading.Event()

    def action(self) -> dict:
        def call(_box, _message: str) -> None:
            self.reached.set()
            self.release.wait(timeout=4)
        return {"call": call}


# --- status, roles, check ----------------------------------------------------------------


def test_status_and_roles(team, monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    s = team.saver
    s.save("status-on", "GET /api/team/status", team.client.get("/api/team/status"))
    for mode in ("record", "enforce"):
        monkeypatch.setenv("TEMPER_API_GUARD", mode)
        s.save(f"status-{mode}", "GET /api/team/status", team.client.get("/api/team/status"))
    monkeypatch.setenv("TEMPER_API_GUARD", "off")
    # the switch off: the routes were never added, so every /api/team path is FastAPI's 404
    s.save("status-off", "GET /api/team/status", TestClient(FastAPI()).get("/api/team/status"))

    local = ls.allow_projects(monkeypatch, tmp_path / "bad-settings", str(team.ws))
    local.write_text(f"project_roots: ['{team.ws}']\ncolour: blue\n", encoding="utf-8")
    s.save("status-project-problems", "GET /api/team/status", team.client.get("/api/team/status"))
    ls.allow_projects(monkeypatch, tmp_path / "good-settings", str(team.ws))

    got = s.save("roles-ok", "GET /api/team/roles", team.client.get("/api/team/roles"))
    assert [r["id"] for r in got["roles"]] == sorted(ROLES), got
    monkeypatch.delenv("TEMPER_PI_BOX_CONFIG")
    s.save("roles-not-set-up", "GET /api/team/roles", team.client.get("/api/team/roles"))
    monkeypatch.setenv("TEMPER_PI_BOX_CONFIG", str(tmp_path / "example-box" / "missing.json"))
    got = s.save("roles-error", "GET /api/team/roles", team.client.get("/api/team/roles"))
    assert got["configured"] is False and got["problem"], got


def test_check(team, monkeypatch, tmp_path):
    s = team.saver
    got = s.save("check-ok", CHECK, team.client.post("/api/team/check", json=trial(team, "c")))
    assert got == {"ok": True, "problems": [], "notes": []}, got
    bad = trial(team, "c", goal="x" * 20001, leader="nobody",
                members=[{"name": "Lead", "role": "planner"},
                         {"name": "checker", "role": "reviewer", "tools": ["Read", "Bash"]},
                         {"name": "temper", "role": "builder"},
                         {"role": ""}],
                project_path="/srv/example/elsewhere/notes-app")
    got = s.save("check-problems", CHECK, team.client.post("/api/team/check", json=bad))
    assert got["ok"] is False and len(got["problems"]) >= 5, got

    # project folders, one problem each (team_folders.py)
    roots = tmp_path / "roots"
    ls.allow_projects(monkeypatch, tmp_path / "folder-settings", str(team.ws), f"{roots}/*",
                      "/srv/example/unseen/*")
    (roots / "plain").mkdir(parents=True)
    empty = roots / "empty-git"
    empty.mkdir()
    ls.git(empty, "init", "-q", "-b", "main")
    dirty = ls.project(roots / "dirty")
    (dirty / "app.py").write_text("print('changed')\n")
    repo = ls.project(roots / "repo")
    (repo / "docs").mkdir()
    outside = tmp_path / "outside"
    ls.project(outside)
    (roots / "linked").symlink_to(outside, target_is_directory=True)
    cases = {"relative": "projects/notes-app", "spaces": f"{roots}/my notes",
             "up": f"{roots}/plain/../repo", "not-git": f"{roots}/plain",
             "no-commit": str(empty), "dirty": str(dirty), "subfolder": str(repo / "docs"),
             "link": str(roots / "linked"), "not-visible": "/srv/example/unseen/notes-app"}
    for slug, folder in cases.items():
        got = s.save(f"check-project-{slug}", CHECK, team.client.post(
            "/api/team/check", json=trial(team, "c", project_path=folder)))
        if slug == "not-visible":
            assert got["ok"] is True and got["notes"], got
        else:
            assert got["ok"] is False and got["problems"], (slug, got)


# --- starting a trial ------------------------------------------------------------------------


def test_start_and_its_refusals(team, monkeypatch):
    import temper_ai.api.routes as routes

    s = team.saver
    r = team.client.post("/api/team/trials", json=trial(team, None))
    s.save("trial-start-400-no-request-id", START, r)
    r = team.client.post("/api/team/trials", json=trial(team, "s-bad", leader="nobody"))
    s.save("trial-start-400-problems", START, r)
    assert r.status_code == 400

    rounds(team.led, ["done"])
    r = team.client.post("/api/team/trials", json=trial(team, "s-1"))
    got = s.save("trial-start-201", START, r)
    assert r.status_code == 201, r.text
    s.save("trial-start-201-repeated", START,
           team.client.post("/api/team/trials", json=trial(team, "s-1")))
    r = team.client.post("/api/team/trials", json=trial(team, "s-1", goal="Something else."))
    s.save("trial-start-409-request-id-reused", START, r)
    assert r.status_code == 409
    assert pw.wait_ended(got["execution_id"], 1)[-1]["status"] == "completed"

    def refuse(_request, *, execution_id=None):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="the run start said no")

    original = routes._start_run
    monkeypatch.setattr(routes, "_start_run", refuse)
    s.save("trial-start-400-run-refused", START,
           team.client.post("/api/team/trials", json=trial(team, "s-2")))
    monkeypatch.setattr(routes, "_start_run", original)

    monkeypatch.setenv("TEMPER_API_GUARD", "enforce")
    s.save("trial-start-401", START, team.client.post("/api/team/trials",
                                                      json=trial(team, "s-3")))
    s.save("answer-401", ANSWER, ta.answer(team, "run-x", "w-1", "continue", rid="g-1"))
    s.save("message-401", MESSAGE, ta.message(team, "run-x", "maker", "hi", rid="g-2"))


# --- the run's states ------------------------------------------------------------------------


def test_running(team):
    """running: checker's turn holds mid-turn while the page reads the run; an owner message
    with no wait open is pending for the member's next turn (maker has no turn left in its
    script, so the message wakes an empty one)."""
    s = team.saver
    rounds(team.led, ["done"])
    hold = Hold()
    ts.SCRIPTS["checker"][0].insert(0, hold.action())
    eid = start(team, trial(team, "r-1"))["execution_id"]
    assert hold.reached.wait(timeout=20), "checker's turn never began"
    try:
        view = save_run(team, "run-running", eid)
        assert view["state"] == "running", view["state"]
        r = ta.message(team, eid, "maker", OWNER_PENDING, rid="m-p")
        sent = s.save("message-201-pending", MESSAGE, r)
        assert r.status_code == 201 and sent["state"] == "pending", r.text
        s.save("trials-running", TRIALS, team.client.get("/api/team/trials"))
    finally:
        hold.release.set()
    assert pw.wait_ended(eid, 1)[-1]["status"] == "completed"


def test_done(team):
    s = team.saver
    rounds(team.led, ["keep_going", "done"])
    eid = start(team, trial(team, "r-2"))["execution_id"]
    assert pw.wait_ended(eid, 1)[-1]["status"] == "completed"
    done = save_run(team, "run-done", eid)
    assert done["state"] == "done", done["state"]
    note = first_message(done, sender="maker")
    s.save("message-read", READ,
           team.client.get(f"/api/team/runs/{eid}/messages/{note['data']['message_id']}"))
    s.save("message-read-404", READ, team.client.get(f"/api/team/runs/{eid}/messages/nope"))
    s.save("run-404", RUN, team.client.get("/api/team/runs/not-a-run"))
    s.save("cancel-ended", CANCEL, team.client.post(
        f"/api/runs/{eid}/cancel", json={"reason": "too late"},
        headers={**ta.key(OWNER_KEY), **ORIGIN}))
    r = team.client.post("/api/runs/not-a-run/cancel", json={"reason": ""},
                         headers={**ta.key(OWNER_KEY), **ORIGIN})
    s.save("cancel-404", CANCEL, r)
    assert r.status_code == 404, r.text


def test_done_with_objections(team):
    rounds(team.led, ["done"], last_views="changes")
    eid = start(team, trial(team, "o-1"))["execution_id"]
    assert pw.wait_ended(eid, 1)[-1]["status"] == "completed"
    got = save_run(team, "run-done-objections", eid)
    assert got["state"] == "done", got["state"]


def test_paused_refusals_messages_and_guide(team):
    s = team.saver
    rounds(team.led, ["keep_going", "done"])
    eid = start(team, trial(team, "p-1", pause_after_rounds=1))["execution_id"]
    wait = ta.parked(team, eid, 1)
    view = save_run(team, "run-paused", eid)
    assert view["state"] == "paused", view["state"]
    wid = wait["wait_id"]

    for name, word, text in (("not-an-answer", "maybe", ""),
                             ("guide-needs-words", "guide", " "),
                             ("takes-no-words", "continue", "now"),
                             ("guidance-too-long", "guide", "g" * 20001),
                             ("stop-reason-too-long", "stop", "s" * 2001)):
        r = ta.answer(team, eid, wid, word, text, rid=f"bad-{name}")
        s.save(f"answer-400-{name}", ANSWER, r)
        assert r.status_code == 400, (name, r.text)
    s.save("answer-404-no-longer-open", ANSWER,
           ta.answer(team, eid, "no-such-wait", "continue", rid="bad-x"))

    # owner messages while the pause is open are held
    r = ta.message(team, eid, "maker", OWNER_HELD, rid="m-1")
    sent = s.save("message-201-held", MESSAGE, r)
    assert r.status_code == 201 and sent["state"] == "held", r.text
    s.save("message-201-repeated", MESSAGE, ta.message(team, eid, "maker", OWNER_HELD, rid="m-1"))
    s.save("message-409-request-id-reused", MESSAGE,
           ta.message(team, eid, "checker", "different", rid="m-1"))
    s.save("message-read-owner", READ,
           team.client.get(f"/api/team/runs/{eid}/messages/{sent['message_id']}"))
    for name, to, text in (("not-a-member", "zed", "hi"), ("empty", "checker", "   "),
                           ("too-long", "checker", "x" * 20001)):
        r = ta.message(team, eid, to, text, rid=f"m-{name}")
        s.save(f"message-400-{name}", MESSAGE, r)
        assert r.status_code == 400, (name, r.text)
    save_run(team, "run-paused-held-message", eid)

    # E12: a member's question waits behind the asked pause and can't be answered yet
    second = team.led.open_wait(eid, THOST, "owner",
                                {"member": "maker",
                                 "question": "Should the note mention the keyboard shortcut "
                                             "for a new note?"}, "attempt-x")
    save_run(team, "run-paused-two-waits", eid)
    r = ta.answer(team, eid, second["wait_id"], "reply", "Yes, at the end.", rid="q-1")
    s.save("answer-409-not-asked-yet", ANSWER, r)
    assert r.status_code == 409, r.text
    with team.led.engine.begin() as conn:
        conn.execute(waits.delete().where(waits.c.wait_id == second["wait_id"]))

    r = ta.answer(team, eid, wid, "guide", "Focus on the saving line; the rest is fine.",
                  rid="a-1", auth=OWNER_KEY)
    got = s.save("answer-200-guide", ANSWER, r)
    assert r.status_code == 200 and got["by"] == "owner", r.text
    s.save("answer-200-repeated", ANSWER,
           ta.answer(team, eid, wid, "guide", "Focus on the saving line; the rest is fine.",
                     rid="a-1", auth=OWNER_KEY))
    r = ta.answer(team, eid, wid, "continue", rid="a-1", auth=OWNER_KEY)
    s.save("answer-409-request-id-reused", ANSWER, r)
    assert pw.wait_ended(eid, 2)[-1]["status"] == "completed"
    r = ta.answer(team, eid, wid, "continue", rid="a-2")
    s.save("answer-409-already-answered", ANSWER, r)
    assert r.status_code == 409 and r.json()["reason"] == "already_answered", r.text
    save_run(team, "run-done-after-guide", eid)
    r = ta.message(team, eid, "checker", "one more thing", rid="m-5")
    s.save("message-409-team-ended", MESSAGE, r)
    assert r.status_code == 409, r.text


def test_stopped_at_the_pause(team):
    rounds(team.led, ["keep_going", "done"])
    eid = start(team, trial(team, "x-1", pause_after_rounds=1))["execution_id"]
    wait = ta.parked(team, eid, 1)
    r = ta.answer(team, eid, wait["wait_id"], "stop", "We have what we need for now.",
                  rid="x-stop", auth=OWNER_KEY)
    team.saver.save("answer-200-stop", ANSWER, r)
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 2)[-1]["status"] == "cancelled"
    got = save_run(team, "run-stopped", eid)
    assert got["state"] == "stopped" and got["run_status"] == "cancelled", got["state"]


def test_cancelled_from_the_run_page(team):
    s = team.saver
    rounds(team.led, ["keep_going", "done"])
    eid = start(team, trial(team, "k-1", pause_after_rounds=1))["execution_id"]
    wait = ta.parked(team, eid, 1)
    head = {**ta.key(OWNER_KEY), **ORIGIN}
    r = team.client.post(f"/api/runs/{eid}/cancel", json={"reason": "c" * 2001}, headers=head)
    s.save("cancel-400-too-long", CANCEL, r)
    assert r.status_code == 400, r.text
    r = team.client.post(f"/api/runs/{eid}/cancel",
                         json={"reason": "Enough for today; I'll pick this up tomorrow."},
                         headers=head)
    s.save("cancel-200", CANCEL, r)
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 1)[-1]["status"] == "cancelled"

    def words():
        out = run(team, eid).json()["outcome"]
        return out if out and out.get("owner_words") else None
    sup.wait_for(words, what="the cancel's words on the outcome")
    got = save_run(team, "run-cancelled", eid)
    assert got["state"] == "stopped" and got["outcome"]["decision"] == "cancelled", got
    # an answer that reaches Temper after Stop run closed the question
    r = ta.answer(team, eid, wait["wait_id"], "continue", rid="k-late", auth=OWNER_KEY)
    reason = r.json().get("reason", "") if r.status_code == 409 else ""
    s.save(f"answer-{r.status_code}-after-stop{'-' + reason.replace('_', '-') if reason else ''}",
           ANSWER, r)
    assert r.status_code in (404, 409), r.text


def test_quiet_then_stopped(team):
    s = team.saver
    ts.SCRIPTS["lead"] = [[{"say": "Nothing to start on yet."}]]
    eid = start(team, trial(team, "q-1"))["execution_id"]
    wait = ta.parked(team, eid, 1)
    got = save_run(team, "run-quiet", eid)
    assert got["state"] == "quiet", got["state"]
    r = ta.answer(team, eid, wait["wait_id"], "nudge", "n" * 4001, rid="q-bad")
    s.save("answer-400-nudge-too-long", ANSWER, r)
    assert r.status_code == 400, r.text
    r = ta.answer(team, eid, wait["wait_id"], "stop", "Not worth more rounds today.",
                  rid="q-stop", auth=OWNER_KEY)
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 2)[-1]["status"] == "cancelled"
    got = save_run(team, "run-stopped-quiet", eid)
    assert got["state"] == "stopped", got["state"]


def test_member_waiting_after_a_cut_off_turn(team):
    rounds(team.led, ["done"])
    ts.SCRIPTS["lead"].insert(0, [ts.send("maker", "Starting on the welcome note now."),
                                  {"die": True}])
    eid = start(team, trial(team, "w-1"))["execution_id"]
    wait = ta.parked(team, eid, 1)
    got = save_run(team, "run-member-waiting", eid)
    assert got["state"] == "member_waiting" and wait["kind"] == "recovery", got["state"]
    r = ta.answer(team, eid, wait["wait_id"], "stop", "This keeps breaking; I'll look later.",
                  rid="w-stop", auth=OWNER_KEY)
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 2)[-1]["status"] == "failed"
    got = save_run(team, "run-stopped-recovery", eid)
    assert got["state"] == "stopped" and got["run_status"] == "failed", got


def test_member_waiting_after_a_failed_turn(team):
    """member_waiting at a failed turn: the run failed, and after a Resume Temper asks retry
    or stop (N1), never an automatic re-run."""
    rounds(team.led, ["done"])
    ts.SCRIPTS["lead"].insert(0, [{"error": "400 invalid_request_error: the request was "
                                            "refused"}])
    eid = start(team, trial(team, "wf-1"))["execution_id"]
    assert pw.wait_ended(eid, 1)[-1]["status"] == "failed"
    r = team.client.post(f"/api/runs/{eid}/resume", json={},
                         headers={**ta.key(OWNER_KEY), **ORIGIN})
    assert r.status_code == 200, r.text
    wait = ta.parked(team, eid, 2)
    got = save_run(team, "run-member-waiting-failed", eid)
    assert got["state"] == "member_waiting", got["state"]
    assert [a["answer"] for a in wait["answers"]] == ["retry", "stop"], wait
    r = ta.answer(team, eid, wait["wait_id"], "stop", rid="wf-stop", auth=OWNER_KEY)
    assert r.status_code == 200, r.text
    pw.wait_ended(eid, 3)


def test_member_waiting_asked_again(team):
    """Words naming no choice at a cut-off turn's wait (the run page's GateModal) decide
    nothing: Temper asks again in a new wait, and the old one is answered."""
    s = team.saver
    rounds(team.led, ["done"])
    ts.SCRIPTS["lead"].insert(0, [ts.send("maker", "Starting on the welcome note now."),
                                  {"die": True}])
    eid = start(team, trial(team, "aa-1"))["execution_id"]
    wait = ta.parked(team, eid, 1)
    r = pw.pick(team.client, eid, wait["node_name"], event_id=wait["event_id"],
                question=wait["question"], custom="not sure yet")
    assert r.status_code == 200, r.text
    again = ta.parked(team, eid, 2)
    got = save_run(team, "run-member-waiting-asked-again", eid)
    assert again["asked_again"] == 1 and again["wait_id"] != wait["wait_id"], again
    assert got["state"] == "member_waiting", got["state"]
    r = ta.answer(team, eid, again["wait_id"], "stop", rid="aa-stop", auth=OWNER_KEY)
    assert r.status_code == 200, r.text
    pw.wait_ended(eid, 3)
    r = ta.answer(team, eid, wait["wait_id"], "retry", rid="aa-old")
    s.save("answer-409-asked-again-old", ANSWER, r)
    assert r.status_code == 409, r.text


def test_member_waiting_at_a_usage_limit(team):
    """A usage limit holds the turn for the owner, naming the limit (member.usage_limit)."""
    rounds(team.led, ["done"])
    ts.SCRIPTS["lead"].insert(0, [{"error": sup.USAGE_LIMIT_ERROR}])
    eid = start(team, trial(team, "ul-1"))["execution_id"]
    wait = ta.parked(team, eid, 1)
    got = save_run(team, "run-member-waiting-usage-limit", eid)
    assert got["state"] == "member_waiting", got["state"]
    assert (wait["why"] or "").startswith("usage limit: "), wait
    r = ta.answer(team, eid, wait["wait_id"], "stop", rid="ul-stop", auth=OWNER_KEY)
    assert r.status_code == 200, r.text
    pw.wait_ended(eid, 2)


def test_failed(team):
    ts.SCRIPTS["lead"] = [[{"error": "400 invalid_request_error: the request was refused"}]]
    eid = start(team, trial(team, "f-1"))["execution_id"]
    assert pw.wait_ended(eid, 1)[-1]["status"] == "failed"
    got = save_run(team, "run-failed", eid)
    assert got["state"] == "failed", got["state"]


def test_didnt_start(team, monkeypatch, tmp_path):
    ls.allow_projects(monkeypatch, tmp_path / "unseen-settings", str(team.ws),
                      "/srv/example/unseen/*")
    r = team.client.post("/api/team/trials",
                         json=trial(team, "d-1", project_path="/srv/example/unseen/notes-app"))
    got = team.saver.save("trial-start-201-note", START, r)
    assert r.status_code == 201 and got["notes"], r.text
    eid = got["execution_id"]
    assert pw.wait_ended(eid, 1)[-1]["status"] == "failed"
    view = save_run(team, "run-didnt-start", eid)
    assert view["state"] == "didnt_start", view["state"]


# --- the trial list ----------------------------------------------------------------------------


def test_trials(team):
    s = team.saver
    s.save("trials-empty", TRIALS, team.client.get("/api/team/trials"))
    rounds(team.led, ["done"])
    done = start(team, trial(team, "t-1"))["execution_id"]
    pw.wait_ended(done, 1)
    ts.SCRIPTS["lead"] = [[{"error": "400 invalid_request_error: the request was refused"}]]
    failed = start(team, trial(team, "t-2", goal="Make the empty notes list say what to do "
                                                "first."))["execution_id"]
    pw.wait_ended(failed, 1)
    rounds(team.led, ["keep_going", "done"])
    stopped = start(team, trial(team, "t-3", pause_after_rounds=1,
                                goal="Tidy the settings page's wording."))["execution_id"]
    wait = ta.parked(team, stopped, 1)
    ta.answer(team, stopped, wait["wait_id"], "stop", "Not needed after all.", rid="t-3-stop",
              auth=OWNER_KEY)
    pw.wait_ended(stopped, 2)
    rounds(team.led, ["keep_going", "done"])
    paused = start(team, trial(team, "t-4", pause_after_rounds=1,
                               goal="Name the three buttons on the share dialog."),
                   auth=CI_KEY)["execution_id"]
    wait = ta.parked(team, paused, 1)
    got = s.save("trials-list", TRIALS, team.client.get("/api/team/trials"))
    assert got["total"] == 4, got
    s.save("trials-page-2", TRIALS, team.client.get("/api/team/trials?limit=2&offset=2"))
    s.save("trials-filtered-paused", TRIALS, team.client.get("/api/team/trials?state=paused"))
    assert ta.answer(team, paused, wait["wait_id"], "continue", rid="t-4-go").status_code == 200
    assert pw.wait_ended(paused, 2)[-1]["status"] == "completed"


# --- part C: the settings wait (contract E24) and a refused done (E14) ---------------------


def change_extension(marker: str) -> None:
    """A deploy changed the identity extension: its digest is in every member's pin (as
    ``tests/test_runner/pi_parking/test_settings_wait.py`` does it)."""
    raw = json.loads(Path(os.environ["TEMPER_PI_BOX_CONFIG"]).read_text())
    (Path(raw["identity_extension"]) / "index.ts").write_text(
        f"export default function () {{}} // {marker}\n")


def settings_trial(team, rid: str) -> tuple[str, dict, dict]:
    """A trial paused after round 1; a deploy changes every member's settings; the owner's
    continue reopens it at the team's settings wait. Returns (run, the pause, the settings
    wait)."""
    rounds(team.led, ["keep_going", "done"])
    eid = start(team, trial(team, rid, pause_after_rounds=1))["execution_id"]
    pause = ta.parked(team, eid, 1)
    change_extension(f"EXAMPLE-{rid}")
    r = ta.answer(team, eid, pause["wait_id"], "continue", rid=f"{rid}-continue",
                  auth=OWNER_KEY)
    assert r.status_code == 200, r.text
    wait = ta.parked(team, eid, 2)
    assert wait["kind"] == "settings", wait
    return eid, pause, wait


def test_settings_wait(team):
    """Asked first with the pause's continue held; the held answer refused; words naming
    neither choice asked again; settings changed again before go on; then go on."""
    s = team.saver
    eid, pause, wait = settings_trial(team, "sw-1")
    got = save_run(team, "run-settings-changed", eid)
    assert got["state"] == "settings_changed", got["state"]
    assert [w["kind"] for w in got["open_waits"]] == ["settings", "pause"], got["open_waits"]
    listed = s.save("trials-settings", TRIALS, team.client.get("/api/team/trials"))
    assert listed["trials"][0]["state"] == "settings_changed", listed
    r = ta.answer(team, eid, pause["wait_id"], "continue", rid="sw-1-held")
    s.save("answer-409-behind-settings", ANSWER, r)
    assert r.status_code == 409, r.text

    # words naming neither choice (the run page's GateModal) decide nothing: asked again
    r = pw.pick(team.client, eid, wait["node_name"], event_id=wait["event_id"],
                question=wait["question"], custom="not sure yet")
    assert r.status_code == 200, r.text
    again = ta.parked(team, eid, 3)
    got = save_run(team, "run-settings-asked-again", eid)
    assert again["kind"] == "settings" and again["asked_again"] == 1, again

    # the settings change again before go on: go on applies nothing and a new wait asks
    change_extension("EXAMPLE-sw-1-again")
    r = ta.answer(team, eid, again["wait_id"], "go on", rid="sw-1-go-1", auth=OWNER_KEY)
    assert r.status_code == 200, r.text
    newer = ta.parked(team, eid, 4)
    got = save_run(team, "run-settings-changed-again", eid)
    assert newer["kind"] == "settings" and newer["wait_id"] != again["wait_id"], newer

    r = ta.answer(team, eid, newer["wait_id"], "go on", rid="sw-1-go-2", auth=OWNER_KEY)
    s.save("answer-200-settings-go-on", ANSWER, r)
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 5)[-1]["status"] == "completed"
    got = save_run(team, "run-settings-go-on", eid)
    assert got["state"] == "done", got["state"]


def test_settings_stop(team):
    eid, _pause, wait = settings_trial(team, "ss-1")
    r = ta.answer(team, eid, wait["wait_id"], "stop", "Not on these settings; I'll start a new "
                  "trial.", rid="ss-1-stop", auth=OWNER_KEY)
    team.saver.save("answer-200-settings-stop", ANSWER, r)
    assert r.status_code == 200, r.text
    assert pw.wait_ended(eid, 3)[-1]["status"] == "cancelled"
    got = save_run(team, "run-settings-stopped", eid)
    assert (got["state"], got["run_status"]) == ("stopped", "cancelled"), got["state"]


def test_refused_done(team):
    """lead says done on a copy it changed after the review: Temper refuses the done and the
    round counts as keep going, so two rounds without done pause the team."""
    rounds(team.led, ["done", "keep_going"])
    ts.SCRIPTS["lead"][1] = [ls.write("WELCOME.md", DRAFTS[1]),
                             ls.decide(team.led, None, "done", SUMMARIES[2])]
    eid = start(team, trial(team, "rd-1", pause_after_rounds=2))["execution_id"]
    wait = ta.parked(team, eid, 1)
    got = save_run(team, "run-refused-done", eid)
    assert got["state"] == "paused", got["state"]
    assert [r["decision"] for r in got["reviews"]] == ["done_refused", "keep_going"], \
        got["reviews"]
    r = ta.answer(team, eid, wait["wait_id"], "stop", rid="rd-stop", auth=OWNER_KEY)
    assert r.status_code == 200, r.text
    pw.wait_ended(eid, 2)


# --- the Team page journey (e2e/team-journey.spec.ts) --------------------------------------


def test_journey(team):
    """One trial the way the page journey drives it, read at each step it checks: started
    from the form with the owner's key and a pause after one round; running, then running
    with more entries; paused (the first answer offered is continue); answered by the owner
    while maker's next turn runs, then the owner's message to the leader, whom the page's
    message box picks first (pending: checker's turn comes first, then lead reads it with the
    views and decides done); done; the trials list."""
    s = team.saver
    rounds(team.led, ["keep_going", "done"])
    early, more, later = Hold(), Hold(), Hold()
    ts.SCRIPTS["lead"][0].insert(0, early.action())
    ts.SCRIPTS["checker"][0].insert(0, more.action())
    ts.SCRIPTS["maker"][1].insert(0, later.action())
    raw = trial(team, "j-1", goal=JOURNEY_GOAL, pause_after_rounds=1,
                members=[{"name": "lead", "role": "planner"},
                         {"name": "maker", "role": "builder"},
                         {"name": "checker", "role": "reviewer"}])
    r = team.client.post("/api/team/trials", json=raw, headers=ta.key(OWNER_KEY))
    started = s.save("journey-trial-start-201", START, r)
    assert r.status_code == 201, r.text
    eid = started["execution_id"]

    counts = []
    for hold, name in ((early, "journey-run-running"), (more, "journey-run-running-more")):
        assert hold.reached.wait(timeout=20), f"{name}: the held turn never began"
        try:
            view = save_run(team, name, eid)
            assert view["state"] == "running", (name, view["state"])
            counts.append(len(view["timeline"]["entries"]))
        finally:
            hold.release.set()
    assert counts[1] > counts[0], counts

    wait = ta.parked(team, eid, 1)
    view = save_run(team, "journey-run-paused", eid)
    assert view["state"] == "paused", view["state"]
    assert wait["answers"][0]["answer"] == "continue", wait["answers"]
    r = ta.answer(team, eid, wait["wait_id"], "continue", rid="j-a", auth=OWNER_KEY)
    got = s.save("journey-answer-200", ANSWER, r)
    assert r.status_code == 200 and got["by"] == "owner", r.text

    assert later.reached.wait(timeout=20), "maker's second turn never began"
    try:
        view = save_run(team, "journey-run-answered", eid)
        assert view["state"] == "running", view["state"]
        assert [e for e in view["timeline"]["entries"] if e["entry"] == "owner_answer"], \
            view["timeline"]["entries"]
        r = ta.message(team, eid, "lead", JOURNEY_MESSAGE, rid="j-m", auth=OWNER_KEY)
        sent = s.save("journey-message-201", MESSAGE, r)
        assert r.status_code == 201 and sent["state"] == "pending", r.text
        view = save_run(team, "journey-run-messaged", eid)
        assert first_message(view, sender="owner")["data"]["preview"].startswith(JOURNEY_TAG)
    finally:
        later.release.set()

    assert pw.wait_ended(eid, 2)[-1]["status"] == "completed"
    done = save_run(team, "journey-run-done", eid)
    assert done["state"] == "done", done["state"]
    trials = s.save("journey-trials", TRIALS, team.client.get("/api/team/trials"))
    assert [i["execution_id"] for i in trials["trials"]] == [eid], trials
