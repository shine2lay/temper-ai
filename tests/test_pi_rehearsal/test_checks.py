"""What a rehearsal run must show (scripts/pi_rehearsal/checks.py), on stand-in readbacks.

``good()`` is the readback of a bundled normal run that went as it should: every check
passes. Each break after it changes one thing a real run could get wrong and names the check
that must catch it; the others stay as they were.
"""

from __future__ import annotations

import pytest

from .support import load

checks = load("checks")

SLOT = "anthropic-4"
OWNER = "owner-dashboard"
IMAGE = "sha256:" + "a" * 64
HEAD = "c" * 40
PINS = {"image_tar": "1" * 64, "runtime_dir": "2" * 64, "add_ons.pi-tldr.dir": "3" * 64}
BOXES = [f"temper-pi-{i:020x}" for i in range(1, 12)]
RUN = "0b5c3a1e-run"


def mount(destination: str, setting: str, *, rw: bool = False) -> dict:
    return {"type": "bind", "source": f"/tmp/pi-rehearsal/x{destination}",
            "destination": destination, "read_only": not rw, "settings": [setting],
            "rehearsal_only": destination == "/box-ca/ca.pem"}


def member_box(name: str) -> dict:
    return {"name": name, "refusal": None, "names": {
        "name": name, "image_id": IMAGE, "mounts": [
            mount("/pi-runtime", "runtime_dir"),
            mount("/ext/addons/pi-image-trim", "add_ons.pi-image-trim.dir"),
            mount("/ext/addons/pi-tldr", "add_ons.pi-tldr.dir"),
            mount("/box-ca/ca.pem", "rehearsal.ca_pem"),
            mount("/w", "state_root", rw=True)]}}


LEAD_TOOLS = ["decide", "edit", "find", "grep", "ls", "read", "request_review",
              "send_message", "tldr", "write"]
REVIEW_TOOLS = ["edit", "find", "give_view", "grep", "ls", "read", "send_message", "tldr",
                "write"]
#: How a member's request offers its tools: Pi's built-ins under Claude Code's names (OAuth).
CC_NAMES = {"edit": "Edit", "grep": "Grep", "read": "Read", "write": "Write"}
#: What a request for Opus 5.5 says about thinking (pi-ai: the member's effort closes it).
THINKING = {"type": "adaptive", "effort": "max", "effort_in": "closing system message",
            "request_effort": "high"}


def pinned_tools(member: str) -> list[str]:
    return LEAD_TOOLS if member == "product" else REVIEW_TOOLS


def participants() -> list[dict]:
    return [{"participant_id": f"p-{m}", "member": m,
             "pin": {"model": "claude-opus-5-5", "thinking": "max", "tools": pinned_tools(m)}}
            for m in ("product", "architecture", "design")]


def answers() -> list[dict]:
    rows = []
    for rule, member, hold in (("lead_first_version", "product", None),
                               ("review_round_one", "architecture", None),
                               ("review_round_one", "design", None),
                               ("lead_keep_going", "product", None),
                               ("review_later_round", "architecture", "owner-message"),
                               ("noted", "product", None),
                               ("lead_done", "product", None)):
        rows.append({"event": "answer", "member": member, "rule": rule, "flag": None,
                     "model": "claude-opus-5-5", "thinking": dict(THINKING),
                     "offered": sorted(CC_NAMES.get(t, t) for t in pinned_tools(member)),
                     "hold_gate": hold,
                     "held_s": {"seconds": 12.5, "released": True} if hold else None})
    return [{"event": "tripwire_armed", "port": 443}, {"event": "tripwire_armed", "port": 80},
            *rows]


def page_report() -> dict:
    return {"journey": "team-page", "mode": "live", "owner_key": "given", "result": "passed",
            "failed_step": None, "execution_id": RUN, "answered_by": "you", "answer": "continue",
            "outcome": "done", "guard_mode": "record", "exit_code": 0, "steps": [
                {"step": step, "passed": True, "looks": [
                    {"theme": theme, "passed": True, "screenshot": f"{step}-{theme}.png",
                     "axe": {"critical": 0, "serious": 0}, "small_targets": []}
                    for theme in checks.THEMES]}
                for step in checks.JOURNEY_STEPS]}


def good() -> dict:
    turns = [{"turn_no": i, "participant_id": f"p-{i % 5}", "box_name": box, "state": "completed",
              "account_slot": SLOT} for i, box in enumerate(BOXES, 1)]
    messages = [{"message_id": f"m-{i}", "sender_participant": f"p-{i % 5}",
                 "client_msg_id": f"toolu_{i}", "sender_kind": "member", "kind": "info"}
                for i in range(8)]
    messages.append({"message_id": "m-owner", "sender_participant": None, "client_msg_id": None,
                     "sender_kind": "owner", "kind": "owner_reply", "to_member": "product"})
    account = {"slot": SLOT, "picked_at": "2026-10-07T16:00:00+00:00", "by": "settings_order",
               "capacity": "not_checked"}
    ledger = {
        "run": [{"execution_id": RUN, "status": "completed", "spawner_kind": "subprocess",
                 "workspace_path": f"/tmp/pi-rehearsal/x/workspaces/{RUN}",
                 "spawner_metadata": {"pi_lane": {"account": account, "commits": [
                     {"at": "2026-10-07T16:00:00+00:00", "start": True, "commit": HEAD,
                      "pins": PINS, "host_pi": "0.0.0-stub"}]}}}],
        "pi_turns": turns,
        "pi_participants": participants(),
        "pi_messages": messages,
        "pi_waits": [{"wait_id": "w-1", "kind": "pause", "state": "answered",
                      "decision": {"by": OWNER, "source": "api"}}],
        "pi_team_outcomes": [{"decision": "done", "decided_by": "product",
                              "record": {"review_id": "rv-2", "commit": "d" * 40,
                                         "branch": None,
                                         "project": {"commit": None, "source": None}}}],
        "pi_team_trials": [{"trial_id": "t-1", "execution_id": RUN, "project": None}],
        "caller_actions": [{"action": "start", "caller": OWNER},
                           {"action": "message", "caller": OWNER}],
        "api_guard_seen": [{"caller": "pickup", "action": "pickup", "refused": False},
                           {"caller": "carry-on", "action": "resume", "refused": False},
                           {"caller": OWNER, "action": "answer", "refused": False}],
        "database": {"dialect": "postgresql", "version": "PostgreSQL 16.4"},
    }
    return {
        "run_id": RUN, "ledger": ledger, "guard_mode": "record",
        "run_view": {"state": "done", "account": {"slot": SLOT, "capacity": "not_checked",
                                                  "room": None}},
        "helper": {"branch": 0, "token": 0, "stub_mints": 0},
        "expected": {"image_id": IMAGE, "min_turns": 11, "owner_callers": [OWNER],
                     "slot": SLOT, "head": HEAD, "pins": PINS},
        "boxes": [member_box(name) for name in BOXES],
        "standin": answers(),
        "logs": {"pi_preflight_refusals": 0, "main_worker_claims": 0, "failed_checkpoint": 0,
                 "guard_warnings": 0},
        "preflight": {"failed": [], "pins": PINS, "host_pi": "0.0.0-stub"},
        "pw03": [{"path": p, "errno": 30} for p in ("/rig/projects", "/rig/share", "/app/.git")],
        "prod": {"before": {"temper-ai-server-1": "2026-10-07T13:56:00Z"},
                 "after": {"temper-ai-server-1": "2026-10-07T13:56:00Z"},
                 "guard_before": "record", "guard_after": "record", "pi_lane_off": True,
                 "pi_lane_line": "Pi lane: off.", "redis_pi_keys_before": 0,
                 "redis_pi_keys_after": 0, "rig_redis_pi_keys": [checks.LANE_VIEW_KEY]},
        "page": page_report(),
    }


def by_name(rows: list[dict]) -> dict[str, dict]:
    return {r["name"]: r for r in rows}


def test_a_bundled_normal_run_that_went_right_passes_every_check():
    rows = checks.run_checks(good())

    failed = [r for r in rows if not r["ok"]]
    assert not failed, failed
    assert checks.passed(rows)
    assert len(rows) == len(by_name(rows))  # every check named once
    assert all(section(good()) for section in checks.SECTIONS)  # and every section has some
    named = by_name(rows)
    assert named["the normal run's steps came in order"]["detail"]["rules"] == [
        "lead_first_version", "review_round_one", "lead_keep_going", "review_later_round",
        "noted", "lead_done"]
    assert named["named callers for the paths this run exercised (observation)"]["detail"] == [
        ("carry-on", "resume"), (OWNER, "answer"), ("pickup", "pickup")]


def _set(path: str, value):
    def change(data: dict) -> None:
        *head, last = path.split(".")
        node = data
        for key in head:
            node = node[int(key)] if isinstance(node, list) else node[key]
        if isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value
    return change


def _drop_turn_box(data):
    data["boxes"].pop()


def _doubled_message(data):
    data["ledger"]["pi_messages"].append(dict(data["ledger"]["pi_messages"][0]))


def _second_pause(data):
    data["ledger"]["pi_waits"].append({"wait_id": "w-2", "kind": "pause", "state": "open",
                                       "decision": None})


def _flagged_answer(data):
    data["standin"][-1]["flag"] = "tool_refused"


def _out_of_order(data):
    rows = data["standin"]
    rows[2], rows[5] = rows[5], rows[2]


def _tripped(data):
    data["standin"].append({"event": "tripwire", "port": 443})


def _unexpected_path(data):
    data["standin"].append({"event": "unexpected", "method": "GET", "path": "/v1/models"})


def _room_figures(data):
    data["ledger"]["run"][0]["spawner_metadata"]["pi_lane"]["account"]["room"] = {"week": 0.4}


def _extra_add_on(data):
    data["boxes"][0]["names"]["mounts"].append(mount("/ext/addons/pi-extra", "add_ons.x.dir"))


def _docker_socket(data):
    data["boxes"][1]["names"]["mounts"].append(mount("/var/run/docker.sock", "PW02"))


def _guard_refused(data):
    data["ledger"]["api_guard_seen"][0]["refused"] = True


def _branch_in_done(data):
    data["ledger"]["pi_team_outcomes"][0]["record"]["branch"] = {"made": False}


def _project_given(data):
    data["ledger"]["pi_team_trials"][0]["project"] = "/projects/fixture"


def _not_owner(data):
    data["ledger"]["pi_waits"][0]["decision"]["by"] = "unknown"


def _top_level_effort(data):
    # The request's fixed top-level "high" read as the member's effort (the rig's old reading).
    for row in data["standin"]:
        if row.get("event") == "answer":
            row["thinking"] = {"type": "adaptive", "effort": "high"}


def _bash_offered(data):
    data["standin"][3]["offered"] = sorted([*data["standin"][3]["offered"], "Bash"])


def _page_step_failed(data):
    data["page"]["steps"][3]["passed"] = False
    data["page"]["failed_step"] = "needs-you"


def _dark_without_screenshot(data):
    data["page"]["steps"][0]["looks"][1]["screenshot"] = None


@pytest.mark.parametrize(("change", "caught_by"), [
    (_set("driver_error", "RigError: an open wait of kind 'stalled'"),
     "the driver saw the run through without an error"),
    (_set("ledger.run.0.status", "failed"), "run completed"),
    (_set("ledger.pi_team_outcomes.0.decision", "keep_going"), "done accepted"),
    (_branch_in_done, "empty start: the done records no branch"),
    (_project_given, "empty start: the done records no branch"),
    (_set("helper.branch", 1), "the helper's branch verb was never asked"),
    (_set("ledger.pi_turns.0.box_name", "temper-pi-run"),
     "every member turn ran in its own real box (temper-pi-<20 hex>)"),
    (_drop_turn_box, "the box watcher saw exactly the ledger's boxes"),
    (_set("boxes.0.names.image_id", "sha256:" + "b" * 64),
     "the boxes used the production image (by id)"),
    (_set("ledger.pi_turns.4.state", "failed"), "every turn ended completed"),
    (_set("ledger.pi_team_outcomes.0.record.project", {"commit": "c" * 40, "source": "/p"}),
     "empty start: the done records no branch"),
    (_extra_add_on, "add-ons in every member box: exactly pi-image-trim and pi-tldr "
                    "(observation)"),
    (_docker_socket, "no Docker socket and no helper socket in any member box (PW04)"),
    (_tripped, "zero connections toward a provider host (tripwires on 127.0.0.1:443 and :80 in "
               "pi-worker armed, none tripped; the relay reached only the stand-in)"),
    (_unexpected_path, "the stand-in answered every model call by the script, no flag"),
    (_flagged_answer, "the stand-in answered every model call by the script, no flag"),
    (_out_of_order, "the normal run's steps came in order"),
    (_set("standin.6.held_s", {"seconds": 240.0, "released": False}),
     "round 2's views waited until the owner's message had reached the team"),
    (_top_level_effort, "model and thinking for every member (from the requests)"),
    (_bash_offered, "every member's requests offered exactly its pinned tools (names, no Bash)"),
    (_second_pause, "the team paused for the owner once, and the answer closed it once"),
    (_doubled_message, "no doubled message (ids and client ids unique)"),
    (_not_owner, "the owner's answer and message are recorded as by the owner"),
    (_room_figures, "the run's account is exactly {slot, picked_at, by settings_order, capacity "
                    "not_checked}, no room figures"),
    (_set("ledger.pi_turns.2.account_slot", "anthropic-2"), "every turn ran on that slot"),
    (_set("helper.token", 1), "the helper's token verb was asked 0 times and minted nothing"),
    (_set("preflight.failed", ["pins"]), "the real preflight, unchanged, passes in pi-worker "
                                         "with its pin check (check_pins and D3) (PW13, the "
                                         "passing half)"),
    (_set("logs.main_worker_claims", 1), "the main worker never claimed the Pi run"),
    (_set("logs.failed_checkpoint", 2), "0 'Failed to save checkpoint' lines across the rig's "
                                        "logs"),
    (_set("ledger.database.dialect", "sqlite"), "the database is PostgreSQL"),
    (_set("guard_mode", "off"), "the guard ran in production's mode, never below record"),
    (_guard_refused, "zero refusals and zero would-refuse records on the exercised paths"),
    (_set("pw03.1.errno", 13), "pi-worker's project, pin and identity roots are read-only "
                               "(EROFS) (PW03)"),
    (_set("prod.after", {"temper-ai-server-1": "2026-10-07T16:30:00Z"}),
     "the live containers kept their start times"),
    (_set("prod.redis_pi_keys_after", 1), "the rig's pi-worker published the Pi lane view only "
                                          "into the rig's own Redis (production's Redis holds "
                                          "no temper:pi:* key before or after)"),
    (_page_step_failed, "Frontend's live page journey passed every step"),
    (_dark_without_screenshot, "each step looked at in light and dark, with a screenshot per "
                               "theme"),
    (_set("page.answered_by", "unknown caller"),
     "the page started this run and answered as the owner"),
])
def test_each_way_a_run_can_go_wrong_fails_its_own_check(change, caught_by):
    data = good()
    change(data)

    failed = [r["name"] for r in checks.run_checks(data) if not r["ok"]]

    assert caught_by in failed
    assert len(failed) <= 3, failed  # one wrong thing shows up where it belongs


def test_a_readback_that_cannot_be_read_fails_its_section_and_the_others_still_run():
    data = good()
    data["ledger"]["pi_turns"] = None
    data["boxes"] = [{"name": BOXES[0], "names": {"mounts": None}}]

    rows = checks.run_checks(data)

    assert by_name(rows)["member_boxes: readback unreadable"]["ok"] is False
    assert by_name(rows)["run completed"]["ok"] is True
    assert by_name(rows)["Frontend's live page journey passed every step"]["ok"] is True
    assert not checks.passed(rows) and not checks.passed([])


def test_a_run_driven_through_the_api_has_no_page_rows():
    data = good()
    data["page"] = None

    rows = checks.run_checks(data)

    assert checks.passed(rows)
    assert not any("page" in r["name"] for r in rows)
