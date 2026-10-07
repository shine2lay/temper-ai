"""What one rehearsal run showed, from its readbacks: pure functions, no Docker, no network.

rig.py gathers the readbacks of a run (the rig database's rows through readback_inner.py,
the Team API's run view, the guard's counts, the stand-in's log, the member boxes' names-only
readings, the helper's log counts, the logs' counts, the page journey's report, the live
stack's start times) into one dict and calls :func:`run_checks`. Each check is one row,
``{"name", "ok", "detail"}``: an observation of this run on the rig, never an item pass.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

BOX_NAME = re.compile(r"temper-pi-[0-9a-f]{20}\Z")
#: The normal run's rules, in the order the stand-in must have used them (scenario.NORMAL).
NORMAL_RULES = ("lead_first_version", "review_round_one", "lead_keep_going",
                "review_later_round", "lead_done")
FLAGS = ("no_rule", "tool_refused", "done_refused", "extra_call", "tool_missing")
ADD_ONS = ("pi-image-trim", "pi-tldr")
#: Callers the exercised paths may be recorded under besides the owner's key (#45).
NAMED_CALLERS = ("pickup", "carry-on")
#: The Pi lane view's Redis key (temper_ai/shared/pi_lane_view.py KEY, ADR-M4-21).
LANE_VIEW_KEY = "temper:pi:lane-view"


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _pi_lane(run_row: dict) -> dict:
    meta = run_row.get("spawner_metadata") or {}
    lane = meta.get("pi_lane") if isinstance(meta, dict) else None
    return lane if isinstance(lane, dict) else {}


def run_end(data: dict) -> list[dict]:
    """The run ended normally with done accepted. The first trial's team starts empty (no
    project, ADR-M4-22), so its done records no branch and the helper's branch verb is never
    asked: the profile's verb-off refusal can't come up on this path."""
    ledger = data["ledger"]
    rows = ledger.get("run") or [{}]
    run_row = rows[0] if rows else {}
    outcomes = ledger.get("pi_team_outcomes") or []
    outcome = outcomes[-1] if outcomes else {}
    record = outcome.get("record") if isinstance(outcome.get("record"), dict) else {}
    trials = ledger.get("pi_team_trials") or []
    trial = trials[-1] if trials else {}
    view = data.get("run_view") or {}
    helper = data.get("helper") or {}
    return [
        check("the driver saw the run through without an error", not data.get("driver_error"),
              data.get("driver_error") or ""),
        check("run completed", run_row.get("status") == "completed",
              {"status": run_row.get("status"), "view_state": view.get("state")}),
        check("done accepted", outcome.get("decision") == "done",
              {"decision": outcome.get("decision"), "decided_by": outcome.get("decided_by")}),
        # team_leader.py starts the done record with branch None and sets it only for a
        # trial with a project folder; an empty start's record names no project source.
        check("empty start: the done records no branch",
              bool(record) and record.get("branch") is None
              and not (record.get("project") or {}).get("source")
              and len(trials) == 1 and not trial.get("project"),
              {"branch": record.get("branch"),
               "project_source": (record.get("project") or {}).get("source"),
               "trials": len(trials), "trial_project": trial.get("project")}),
        check("the helper's branch verb was never asked", helper.get("branch") == 0,
              {"branch": helper.get("branch")}),
    ]


def member_boxes(data: dict) -> list[dict]:
    ledger = data["ledger"]
    turns = ledger.get("pi_turns") or []
    named = [t.get("box_name") for t in turns]
    seen = data.get("boxes") or []
    refused = [b for b in seen if b.get("refusal")]
    seen_names = {b.get("name") for b in seen}
    image = data.get("expected", {}).get("image_id")
    images = {b["names"]["image_id"] for b in seen if b.get("names")}
    by_turn = [{"turn_no": t.get("turn_no"), "participant_id": t.get("participant_id"),
                "box": t.get("box_name"), "state": t.get("state")} for t in turns]
    add_on_sets = {b.get("name"): sorted(m["destination"].rsplit("/", 1)[-1]
                                         for m in b["names"]["mounts"]
                                         if m["destination"].startswith("/ext/addons/"))
                   for b in seen if b.get("names")}
    return [
        check("every member turn ran in its own real box (temper-pi-<20 hex>)",
              len(turns) >= data.get("expected", {}).get("min_turns", 1)
              and all(n and BOX_NAME.fullmatch(n) for n in named)
              and len(set(named)) == len(named), by_turn),
        check("the box watcher saw exactly the ledger's boxes",
              set(named) == seen_names and not refused,
              {"ledger": sorted(n or "" for n in named), "watched": sorted(seen_names),
               "refused": refused}),
        check("the boxes used the production image (by id)", bool(image) and images == {image},
              {"want": image, "have": sorted(images)}),
        check("every turn ended completed", bool(turns)
              and all(t.get("state") == "completed" for t in turns),
              Counter(t.get("state") for t in turns)),
        check("add-ons in every member box: exactly pi-image-trim and pi-tldr (observation)",
              bool(add_on_sets) and all(v == list(ADD_ONS) for v in add_on_sets.values()),
              add_on_sets),
        check("no Docker socket and no helper socket in any member box (PW04)",
              bool(seen) and not any(
                  "docker.sock" in m["source"] or "docker.sock" in m["destination"]
                  or "host_helper_socket" in m["settings"]
                  for b in seen if b.get("names") for m in b["names"]["mounts"]),
              len(seen)),
    ]


def stand_in(data: dict) -> list[dict]:
    rows = [r for r in data.get("standin") or [] if r.get("event") == "answer"]
    unexpected = [r for r in data.get("standin") or []
                  if r.get("event") in ("unexpected", "unreadable")]
    flagged = [r for r in rows if r.get("flag")]
    rules: list[str] = []
    for r in rows:
        if r.get("rule") and (not rules or rules[-1] != r["rule"]):
            rules.append(r["rule"])
    wanted = [r for r in rules if r in NORMAL_RULES]
    models = sorted({(r.get("member"), r.get("model"), repr(r.get("thinking"))) for r in rows})
    pins = member_pins(data)
    asked = {}
    for r in rows:
        asked.setdefault(r.get("member"), set()).add(
            (r.get("model"), (r.get("thinking") or {}).get("effort")))
    as_pinned = {m: {"pinned": [pins.get(m, {}).get("model"), pins.get(m, {}).get("thinking")],
                     "asked": sorted(map(list, seen), key=repr),
                     "same": seen == {(pins.get(m, {}).get("model"),
                                       pins.get(m, {}).get("thinking"))}}
                 for m, seen in sorted(asked.items(), key=lambda kv: str(kv[0]))}
    offered = {}
    for r in rows:
        offered.setdefault(r.get("member"), set()).add(
            tuple(sorted(str(t).lower() for t in r.get("offered") or ())))
    tools_as_pinned = {}
    for m, sets in sorted(offered.items(), key=lambda kv: str(kv[0])):
        pinned = {str(t).lower() for t in pins.get(m, {}).get("tools") or ()}
        seen_all = set().union(*map(set, sets))
        tools_as_pinned[m] = {"requests": len([r for r in rows if r.get("member") == m]),
                              "same": len(sets) == 1 and set(next(iter(sets))) == pinned,
                              "extra": sorted(seen_all - pinned),
                              "missing": sorted(pinned - seen_all),
                              "bash_offered": "bash" in seen_all}
    held = [r.get("held_s") or {} for r in rows if r.get("hold_gate")]
    events = data.get("standin") or []
    tripped = [r for r in events if r.get("event") == "tripwire"]
    armed = sorted({r.get("port") for r in data.get("standin_all") or events
                    if r.get("event") == "tripwire_armed"})
    return [
        check("zero connections toward a provider host (tripwires on 127.0.0.1:443 and :80 in "
              "pi-worker armed, none tripped; the relay reached only the stand-in)",
              armed == [80, 443] and not tripped and bool(rows),
              {"armed": armed, "tripped": len(tripped), "stand_in_answers": len(rows)}),
        check("the stand-in answered every model call by the script, no flag",
              bool(rows) and not flagged and not unexpected,
              {"answers": len(rows), "flagged": flagged, "unexpected": unexpected}),
        check("the normal run's steps came in order", wanted == list(NORMAL_RULES),
              {"rules": rules}),
        check("round 2's views waited until the owner's message had reached the team",
              bool(held) and all(h.get("released") is True for h in held), held),
        check("model and thinking for every member (from the requests)",
              bool(models) and all(m[1] for m in models) and bool(as_pinned)
              and set(as_pinned) == set(pins) and all(v["same"] for v in as_pinned.values()),
              {"seen": models, "as_pinned": as_pinned}),
        check("every member's requests offered exactly its pinned tools (names, no Bash)",
              bool(tools_as_pinned) and set(tools_as_pinned) == set(pins)
              and all(v["same"] and not v["bash_offered"] for v in tools_as_pinned.values()),
              tools_as_pinned),
    ]


def member_pins(data: dict) -> dict[str, dict]:
    """Each member's pinned model, thinking and tools, from the ledger's participants."""
    out: dict[str, dict] = {}
    for p in (data.get("ledger") or {}).get("pi_participants") or []:
        pin = p.get("pin") or {}
        out[p.get("member")] = {"model": pin.get("model"), "thinking": pin.get("thinking"),
                                "tools": list(pin.get("tools") or ())}
    return out


def owner_path(data: dict) -> list[dict]:
    ledger = data["ledger"]
    waits = ledger.get("pi_waits") or []
    pauses = [w for w in waits if w.get("kind") == "pause"]
    owner_msgs = [m for m in ledger.get("pi_messages") or [] if m.get("sender_kind") == "owner"]
    ids = [m.get("message_id") for m in ledger.get("pi_messages") or []]
    client_ids = [(m.get("sender_participant"), m.get("client_msg_id"))
                  for m in ledger.get("pi_messages") or [] if m.get("client_msg_id")]
    owners = set(data.get("expected", {}).get("owner_callers") or ())
    answers = [(w.get("decision") or {}).get("by") for w in pauses]
    sent = [a.get("caller") for a in ledger.get("caller_actions") or []
            if a.get("action") == "message"]
    return [
        check("the team paused for the owner once, and the answer closed it once",
              len(pauses) == 1 and pauses[0].get("state") != "open"
              and pauses[0].get("decision") is not None,
              [{k: w.get(k) for k in ("wait_id", "kind", "state", "decision", "opened_at",
                                      "decided_at")} for w in waits]),
        check("every wait answered once (none left open)",
              all(w.get("state") != "open" for w in waits), Counter(w.get("state") for w in waits)),
        check("one owner message reached the team", len(owner_msgs) == 1,
              [{k: m.get(k) for k in ("message_id", "to_member", "kind", "state")}
               for m in owner_msgs]),
        check("no doubled message (ids and client ids unique)",
              len(ids) == len(set(ids)) and len(client_ids) == len(set(client_ids)),
              {"messages": len(ids), "client_ids": len(client_ids)}),
        check("the owner's answer and message are recorded as by the owner",
              bool(owners) and bool(answers) and bool(sent)
              and all(b in owners for b in answers + sent),
              {"answer_by": answers, "message_by": sent, "owner_callers": sorted(owners)}),
    ]


def account(data: dict) -> list[dict]:
    ledger = data["ledger"]
    rows = ledger.get("run") or [{}]
    lane = _pi_lane(rows[0] if rows else {})
    acct = lane.get("account") if isinstance(lane.get("account"), dict) else {}
    slot = data.get("expected", {}).get("slot")
    turns = ledger.get("pi_turns") or []
    view_acct = (data.get("run_view") or {}).get("account") or {}
    return [
        check("the run's account is exactly {slot, picked_at, by settings_order, capacity "
              "not_checked}, no room figures",
              set(acct) == {"slot", "picked_at", "by", "capacity"} and acct.get("slot") == slot
              and acct.get("by") == "settings_order" and acct.get("capacity") == "not_checked",
              acct),
        check("every turn ran on that slot", bool(turns) and all(
            t.get("account_slot") == slot for t in turns),
              sorted({str(t.get("account_slot")) for t in turns})),
        check("the run view shows the slot with capacity not checked",
              view_acct.get("slot") == slot and view_acct.get("capacity") == "not_checked"
              and not view_acct.get("room"), view_acct),
        check("the helper's token verb was asked 0 times and minted nothing",
              data.get("helper", {}).get("token") == 0 and data.get("helper", {}).get(
                  "stub_mints") == 0, data.get("helper")),
    ]


def lane(data: dict) -> list[dict]:
    ledger = data["ledger"]
    rows = ledger.get("run") or [{}]
    run_row = rows[0] if rows else {}
    lane_rec = _pi_lane(run_row)
    commits = lane_rec.get("commits") or []
    start = commits[0] if commits else {}
    probe = data.get("preflight") or {}
    return [
        check("the real preflight, unchanged, passes in pi-worker with its pin check "
              "(check_pins and D3) (PW13, the passing half)",
              probe.get("failed") == [] and bool(probe.get("pins"))
              and probe.get("pins") == data.get("expected", {}).get("pins"),
              {"failed": probe.get("failed"), "pins": sorted(probe.get("pins") or {}),
               "host_pi": probe.get("host_pi")}),
        check("the real preflight passed at the claim (commit and pins recorded)",
              bool(start.get("commit")) and bool(start.get("pins"))
              and start.get("commit") == data.get("expected", {}).get("head")
              and not data.get("logs", {}).get("pi_preflight_refusals"),
              {"commit": start.get("commit"), "pins": sorted(start.get("pins") or {}),
               "host_pi": start.get("host_pi")}),
        check("the pins it checked match the rig's copies of production's",
              bool(start.get("pins")) and start.get("pins") == data.get("expected", {}).get("pins"),
              {"recorded": start.get("pins"), "expected": data.get("expected", {}).get("pins")}),
        check("the main worker never claimed the Pi run",
              data.get("logs", {}).get("main_worker_claims") == 0
              and run_row.get("spawner_kind") != "docker", {
                  "main_worker_claims": data.get("logs", {}).get("main_worker_claims"),
                  "spawner_kind": run_row.get("spawner_kind")}),
        check("0 'Failed to save checkpoint' lines across the rig's logs",
              data.get("logs", {}).get("failed_checkpoint") == 0,
              data.get("logs", {}).get("failed_checkpoint")),
        check("the database is PostgreSQL",
              (ledger.get("database") or {}).get("dialect") == "postgresql",
              (ledger.get("database") or {}).get("version")),
    ]


def guard(data: dict) -> list[dict]:
    seen = data.get("ledger", {}).get("api_guard_seen") or []
    refused = [s for s in seen if s.get("refused")]
    unknown = [s for s in seen if not s.get("caller") or str(s.get("caller")).startswith("?")]
    callers = sorted({(s.get("caller"), s.get("action")) for s in seen})
    mode = data.get("guard_mode")
    return [
        check("the guard ran in production's mode, never below record",
              mode in ("record", "enforce") and mode == data.get("prod", {}).get("guard_before"),
              mode),
        check("zero refusals and zero would-refuse records on the exercised paths",
              not refused and not unknown and data.get("logs", {}).get("guard_warnings") == 0,
              {"refused": refused, "unknown": unknown,
               "guard_log_lines": data.get("logs", {}).get("guard_warnings")}),
        check("named callers for the paths this run exercised (observation)", bool(callers),
              callers),
    ]


def boundaries(data: dict) -> list[dict]:
    pw03 = data.get("pw03") or []
    return [
        check("pi-worker's project, pin and identity roots are read-only (EROFS) (PW03)",
              bool(pw03) and all(p.get("errno") == 30 for p in pw03), pw03),
    ]


def production(data: dict) -> list[dict]:
    prod = data.get("prod") or {}
    return [
        check("the live containers kept their start times",
              bool(prod.get("before")) and prod.get("before") == prod.get("after"), prod),
        check("the live guard mode is unchanged", prod.get("guard_before") == prod.get(
            "guard_after"), {k: prod.get(k) for k in ("guard_before", "guard_after")}),
        check("the live Pi lane is off (temper-deploy status)", prod.get("pi_lane_off") is True,
              prod.get("pi_lane_line")),
        check("the rig's pi-worker published the Pi lane view only into the rig's own Redis "
              "(production's Redis holds no temper:pi:* key before or after)",
              prod.get("redis_pi_keys_before") == 0 and prod.get("redis_pi_keys_after") == 0
              and LANE_VIEW_KEY in (prod.get("rig_redis_pi_keys") or []),
              {k: prod.get(k) for k in ("redis_pi_keys_before", "redis_pi_keys_after",
                                        "rig_redis_pi_keys")}),
    ]


#: Frontend's journey steps (frontend/e2e/team-journey.ts JOURNEY_STEPS) and themes.
JOURNEY_STEPS = ("team", "form", "run", "needs-you", "message", "outcome")
THEMES = ("light", "dark")


def page(data: dict) -> list[dict]:
    """Frontend's live journey (its report.json, JourneyReport): every step passed, each looked
    at in light and dark with a screenshot, and the answer recorded as the owner's."""
    report = data.get("page")
    if report is None:
        return []
    steps = {s.get("step"): s for s in report.get("steps") or []}
    looks = {(s, look.get("theme")): look for s, step in steps.items()
             for look in step.get("looks") or []}
    summary = {s: {"passed": (steps.get(s) or {}).get("passed"),
                   "themes": sorted(t for (n, t) in looks if n == s)} for s in JOURNEY_STEPS}
    return [
        check("Frontend's live page journey passed every step",
              report.get("exit_code") == 0 and report.get("result") == "passed"
              and not report.get("failed_step")
              and all((steps.get(s) or {}).get("passed") is True for s in JOURNEY_STEPS),
              {"exit_code": report.get("exit_code"), "result": report.get("result"),
               "failed_step": report.get("failed_step"), "steps": summary}),
        check("each step looked at in light and dark, with a screenshot per theme",
              all(looks.get((s, t), {}).get("passed") is True
                  and looks.get((s, t), {}).get("screenshot")
                  for s in JOURNEY_STEPS for t in THEMES),
              {f"{s}/{t}": {"passed": looks.get((s, t), {}).get("passed"),
                            "axe": looks.get((s, t), {}).get("axe"),
                            "small_targets": len(looks.get((s, t), {}).get("small_targets")
                                                 or [])}
               for s in JOURNEY_STEPS for t in THEMES}),
        check("the page started this run and answered as the owner",
              report.get("execution_id") == data.get("run_id")
              and report.get("answered_by") == "you" and report.get("owner_key") == "given",
              {k: report.get(k) for k in ("execution_id", "answered_by", "owner_key", "answer",
                                          "outcome", "guard_mode")}),
    ]


SECTIONS = (run_end, member_boxes, stand_in, owner_path, account, lane, guard, boundaries,
            production, page)


def run_checks(data: dict) -> list[dict]:
    """Every check for one run, in a fixed order; a section that can't read its part fails
    with the error instead of stopping the others."""
    rows: list[dict] = []
    for section in SECTIONS:
        try:
            rows += section(data)
        except Exception as exc:  # noqa: BLE001 - a broken readback is a failed check
            rows.append(check(f"{section.__name__}: readback unreadable", False,
                              f"{type(exc).__name__}: {exc}"))
    return rows


def passed(rows: list[dict]) -> bool:
    return bool(rows) and all(r["ok"] for r in rows)
