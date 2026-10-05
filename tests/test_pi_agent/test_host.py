"""The Pi step end to end in an in-process Temper, with the stand-in worker (no model, no
container, no network): turns, owner waits, the second message in the same session, the
run page's record, and failures that can never show green."""

from __future__ import annotations

import pytest

from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import CHECK_WORD, NOTE_WORD, FakeBox


def _turn_ended(eid: str, n: int) -> list[dict]:
    def ready():
        agents = sup.turn_agents(eid)
        if len(agents) >= n and sup.agent_end(eid, agents[n - 1]["id"]):
            return agents
        return None
    return sup.wait_for(ready, what=f"turn {n} of {eid} to end")


def _run_status(eid: str) -> str:
    return sup.wait_ended(eid)[-1]["status"]


def test_two_turns_in_one_session_then_done(pi):
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    first = sup.open_wait(eid, "owner")
    agents = _turn_ended(eid, 1)
    end1 = sup.agent_end(eid, agents[0]["id"])
    assert end1["type"] == "agent.completed"
    # The role read its note with the read tool and its notebook (the check word).
    assert NOTE_WORD in end1["data"]["output"] and CHECK_WORD in end1["data"]["output"]
    # Effective settings are what Pi reported, recorded with the turn.
    assert end1["data"]["pi_effective"] == {"provider": "openai-codex", "model": "gpt-6.1-sol",
                                            "thinking": "medium",
                                            "session_id": agents[0]["data"]["pi_turn"]["session_id"]}
    assert end1["data"]["pi_turn_checks"]["role"]["identity"] is True
    assert end1["data"]["executed_by"] == "pi"
    tools = [e for e in sup.events(eid) if e["type"].startswith("tool.call")
             and e["parent_id"] == agents[0]["id"]]
    assert tools, "the read tool call is recorded under the turn"
    # Asked through ask_owner under the ledger row's own id (C7).
    assert first["gate_name"] == f"talk~ask-{first['wait_id']}"

    r = sup.approve(pi.client, eid, first["gate_name"],
                    "Without using any tools: what was the first word of the note?")
    assert r.status_code == 200, r.text
    agents = _turn_ended(eid, 2)
    end2 = sup.agent_end(eid, agents[1]["id"])
    assert end2["type"] == "agent.completed"
    assert NOTE_WORD in end2["data"]["output"], "the second turn remembers the first one"
    t1, t2 = (a["data"]["pi_turn"] for a in agents)
    assert t1["session_id"] == t2["session_id"] and t1["participant_id"] == t2["participant_id"]
    assert (t1["turn_no"], t2["turn_no"]) == (1, 2)
    # One Pi session file; the role was bound once, in the first start only.
    pdir = sup.ledger().snapshot(eid)["participants"][0]["session_dir"]
    files = list(__import__("pathlib").Path(pdir).glob("*.jsonl"))
    assert len(files) == 1
    assert [s["session_id"] for s in FakeBox.STARTS] == [t1["session_id"]] * 2
    assert FakeBox.STARTS[0]["commands"].count("prompt") == 3  # /identity, state, the batch
    assert FakeBox.STARTS[1]["commands"].count("prompt") == 2  # state, the batch
    assert all(s["allowance_at_prompt"] == 4 for s in FakeBox.STARTS)

    second = sup.open_wait(eid, "owner")
    assert second["gate_name"] != first["gate_name"]
    # The answered wait is gone: an old tab approving it again finds nothing.
    assert sup.approve(pi.client, eid, first["gate_name"], "again").status_code == 404
    assert sup.approve(pi.client, eid, second["gate_name"], "done").status_code == 200
    assert _run_status(eid) == "completed"
    assert sup.node_status(eid, "talk")[-1] == "completed"
    assert sup.node_status(eid, "audit")[-1] == "completed"
    snap = sup.ledger().snapshot(eid)
    assert [t["state"] for t in snap["turns"]] == ["completed", "completed"]
    assert [m["sender"] for m in snap["messages"]] == ["owner", "owner"]
    assert snap["participants"][0]["state"] == "retired"
    assert len(FakeBox.STARTS) == 2


def test_the_run_page_shows_each_turn_after_a_refresh(pi):
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    w = sup.open_wait(eid, "owner")
    sup.approve(pi.client, eid, w["gate_name"], "And once more, without tools?")
    w2 = sup.open_wait(eid, "owner", other_than=w["wait_id"])
    sup.approve(pi.client, eid, w2["gate_name"], "done")
    _run_status(eid)
    page = pi.client.get(f"/api/workflows/{eid}")
    assert page.status_code == 200
    body = page.json()
    talk = _find_node(body, "talk")
    agents = talk.get("agents") or [talk.get("agent")]
    assert len(agents) == 2, "both turns are on the page, read back from the store"
    for a in agents:
        assert a["status"] == "completed"
        assert a["output"]
        assert a.get("llm_calls"), "the turn's model calls are listed"
    waits = [c for c in talk.get("child_nodes") or [] if "~ask-" in c.get("name", "")]
    assert len(waits) == 2 and all(c["status"] == "approved" for c in waits)


def _find_node(body: dict, name: str) -> dict:
    stack = list(body.get("nodes") or [])
    while stack:
        node = stack.pop()
        if node.get("name") == name:
            return node
        stack += node.get("child_nodes") or []
    raise AssertionError(f"node {name} not on the page: {[n.get('name') for n in body.get('nodes') or []]}")


def test_provider_error_fails_the_step_red(pi):
    FakeBox.behaviour = "provider_error"
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    assert _run_status(eid) == "failed"
    agents = sup.turn_agents(eid)
    assert len(agents) == 1
    end = sup.agent_end(eid, agents[0]["id"])
    assert end["type"] == "agent.failed" and end["status"] == "failed"
    assert sup.node_status(eid, "talk")[-1] == "failed"
    assert "audit" not in [(e["data"] or {}).get("name")
                            for e in sup.events(eid, event_type="stage.started")
                            if e["status"] == "completed"]
    assert sup.ledger().snapshot(eid)["turns"][0]["state"] == "failed"


@pytest.mark.parametrize("lie, code", [
    ("model", "settings_not_effective"),
    ("identity", "role_not_verified"),
    ("tools", "role_not_verified"),
    ("notebook", "role_not_verified"),
    ("stray_extension", "extensions_not_allowed"),
])
def test_a_worker_that_fails_a_check_never_reaches_the_model(pi, lie, code):
    FakeBox.lie = lie
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    assert _run_status(eid) == "failed"
    assert [s["prompts"] for s in FakeBox.STARTS] == [0], "no model prompt was sent"
    assert FakeBox.STARTS[0]["allowance_at_prompt"] is None
    end = sup.agent_end(eid, sup.turn_agents(eid)[0]["id"])
    assert end["type"] == "agent.failed" and code in end["data"]["error"]
    turn = sup.ledger().snapshot(eid)["turns"][0]
    assert turn["state"] == "failed" and turn["effect_state"] == "none"


def test_an_owner_question_from_an_extension_is_refused(pi):
    FakeBox.behaviour = "ui"
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    _turn_ended(eid, 1)
    # The request got one bounded "cancelled" reply; the turn went on without an answer.
    assert FakeBox.STARTS[0]["ui_replies"] == [
        {"type": "extension_ui_response", "id": "ui-1", "cancelled": True}]
    assert FakeBox.STARTS[0]["prompts"] == 1
    w = sup.open_wait(eid, "owner")
    sup.approve(pi.client, eid, w["gate_name"], "done")
    assert _run_status(eid) == "completed"


def test_a_worker_that_dies_mid_turn_is_held_for_the_owner_never_green(pi):
    FakeBox.behaviour = "die"
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    rec = sup.open_wait(eid, "recovery")
    agents = sup.turn_agents(eid)
    end = sup.agent_end(eid, agents[0]["id"])
    assert end["type"] == "agent.failed", "a cut-off turn is red on the page"
    turn = sup.ledger().snapshot(eid)["turns"][0]
    assert turn["state"] == "uncertain" and turn["effect_state"] == "intent"
    assert rec["subject"]["options"] == ["accept", "retry"]
    # Retry: the same messages go to the same session again, as a new numbered turn.
    FakeBox.behaviour = "answer"
    assert sup.approve(pi.client, eid, rec["gate_name"], "retry").status_code == 200
    _turn_ended(eid, 2)
    owner = sup.open_wait(eid, "owner")
    snap = sup.ledger().snapshot(eid)
    assert [t["state"] for t in snap["turns"]] == ["superseded", "completed"]
    assert [t["turn_no"] for t in snap["turns"]] == [1, 2]
    # The retry got the same message again, same id, marked as given again (R2 B1/G3):
    # never re-posted as a new copy.
    [goal] = snap["messages"]
    assert (goal["turn_id"], goal["delivery_count"]) == (snap["turns"][1]["turn_id"], 2)
    assert snap["turns"][1]["retry_of"] == snap["turns"][0]["turn_id"]
    assert snap["turns"][1]["input_seqs"] == snap["turns"][0]["input_seqs"]
    assert len({s["session_id"] for s in FakeBox.STARTS}) == 1
    # The retry went on from the last settled entry of the same session file: the cut-off
    # branch (the unanswered prompt) stays in the file, off the active branch.
    assert len(FakeBox.STARTS[1].get("rewinds") or []) == 1
    end2 = sup.agent_end(eid, sup.turn_agents(eid)[1]["id"])
    assert end2["data"]["pi_turn_checks"]["rewound"]["to"] == FakeBox.STARTS[1]["rewinds"][0]
    files = list(__import__("pathlib").Path(snap["participants"][0]["session_dir"]).glob("*.jsonl"))
    assert len(files) == 1
    users = [line for line in files[0].read_text().splitlines() if '"role": "user"' in line]
    assert len(users) == 2
    sup.approve(pi.client, eid, owner["gate_name"], "done")
    assert _run_status(eid) == "completed"


def test_a_tool_that_never_ends_is_uncertain_and_accept_goes_on(pi):
    FakeBox.behaviour = "die_in_tool"
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    rec = sup.open_wait(eid, "recovery")
    assert sup.agent_end(eid, sup.turn_agents(eid)[0]["id"])["type"] == "agent.failed"
    starts = len(FakeBox.STARTS)
    sup.approve(pi.client, eid, rec["gate_name"], "accept")
    owner = sup.open_wait(eid, "owner")
    assert len(FakeBox.STARTS) == starts, "accept never re-runs the turn"
    assert sup.ledger().snapshot(eid)["turns"][0]["state"] == "accepted"
    # The next message goes on from the session's last settled entry (the dangling tool
    # call is left on the abandoned branch), never on top of it.
    FakeBox.behaviour = "answer"
    sup.approve(pi.client, eid, owner["gate_name"], "Without using any tools: still there?")
    agents = _turn_ended(eid, 2)
    assert sup.agent_end(eid, agents[1]["id"])["type"] == "agent.completed"
    assert len(FakeBox.STARTS[-1].get("rewinds") or []) == 1
    last = sup.open_wait(eid, "owner", other_than=owner["wait_id"])
    sup.approve(pi.client, eid, last["gate_name"], "done")
    assert _run_status(eid) == "completed"
    assert [t["state"] for t in sup.ledger().snapshot(eid)["turns"]] == ["accepted", "completed"]


def test_a_pi_step_may_be_the_first_node(pi):
    """C7: nothing runs before the Pi step, and its owner wait still lets the worker go --
    under the wait's own checkpoint -- and the answer carries the run on to the end."""
    eid = sup.start(pi.client, "pi_first", pi.ws)
    w = sup.open_wait(eid, "owner")
    first = sup.wait_for(lambda: next((a for a in sup.attempts(eid)[:1]
                                       if (a["data"] or {}).get("parked")), None),
                         what="the first attempt to let its worker go")
    assert first["data"]["parked"]["path"] == "talk"
    assert first["data"]["parked"]["wait_id"] == w["wait_id"]
    assert sup.approve(pi.client, eid, w["gate_name"], "done").status_code == 200
    assert _run_status(eid) == "completed"
    assert len(FakeBox.STARTS) == 1, "the answer never runs the settled turn again"
    assert sup.node_status(eid, "audit")[-1] == "completed"
    assert [t["state"] for t in sup.ledger().snapshot(eid)["turns"]] == ["completed"]


def test_one_role_per_step(pi):
    eid = sup.start(pi.client, "pi_two_roles", pi.ws)
    assert _run_status(eid) == "failed"
    assert FakeBox.STARTS == []


def test_cancel_while_waiting_closes_the_wait(pi, monkeypatch):
    # The wait lets the worker go (C7), so the cancel finds the run parked: the parked run's
    # cancel ends its Pi conversations, with the switch on as it is wherever Pi steps run.
    monkeypatch.setenv("TEMPER_PI_AGENT", "1")
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    w = sup.open_wait(eid, "owner")
    assert pi.client.post(f"/api/runs/{eid}/cancel").status_code in (200, 202)
    sup.wait_ended(eid)
    # The parked run's cancel ends the attempt first (its compare-and-set), then the ledger.
    snap = sup.wait_for(
        lambda: (s := sup.ledger().snapshot(eid))["waits"][0]["state"] != "open" and s,
        what="the cancel to end the Pi conversation")
    assert [x["state"] for x in snap["waits"]] == ["cancelled"]
    gate = [e for e in sup.events(eid) if e["id"] == w["ask_event_id"]][0]
    assert gate["status"] == "rejected"
    assert sup.approve(pi.client, eid, w["gate_name"], "too late").status_code == 404


def test_an_owner_wait_is_answered_once_through_the_gate_engine(pi):
    """The approve route's compare-and-set: a second answer to the same wait (another tab,
    a double click) gets a 409 and the role hears only the first."""
    eid = sup.start(pi.client, "pi_talk", pi.ws)
    w = sup.open_wait(eid, "owner")
    body = {"response": "What was the word?", "event_id": w["ask_event_id"]}
    first = pi.client.post(f"/api/runs/{eid}/approve/{w['gate_name']}", json=body)
    assert first.status_code == 200, first.text
    again = pi.client.post(f"/api/runs/{eid}/approve/{w['gate_name']}",
                           json={**body, "response": "a second answer"})
    assert again.status_code == 409
    owner2 = sup.open_wait(eid, "owner", other_than=w["wait_id"])
    messages = [m["body"] for m in sup.ledger().snapshot(eid)["messages"]]
    assert "What was the word?" in messages and "a second answer" not in messages
    assert owner2["gate_name"] != w["gate_name"], "every wait has its own name"
    sup.approve(pi.client, eid, owner2["gate_name"], "done")
    assert _run_status(eid) == "completed"


def test_a_gate_steps_resume_never_takes_a_pi_wait(pi):
    """A gate step sorting out its earlier waits on resume (adopt one, retire the rest as
    replaced) never matches a Pi step's waits: a gate reads the waits named after it, and a
    Pi wait's name is its own (``<step>~ask-<wait id>``), even at the same step path."""
    from temper_ai.observability.recorder import gate_events
    from temper_ai.stage.gate import earlier_waits

    eid = sup.start(pi.client, "pi_talk", pi.ws)
    w = sup.open_wait(eid, "owner")
    [pi_wait] = [e for e in gate_events(eid) if e["id"] == w["ask_event_id"]]
    assert (pi_wait["data"]["gate_path"], pi_wait["data"]["type"]) == ("talk", "step_wait")
    history = gate_events(eid, "talk")
    assert pi_wait["id"] not in [e["id"] for e in history]
    got = earlier_waits(history, "talk", "talk")
    assert (got.answer, got.adopt, got.retire) == (None, None, [])
    sup.approve(pi.client, eid, w["gate_name"], "done")
    assert _run_status(eid) == "completed"


_PIN_IN_A_NEW_PROCESS = """
import json, sys
from types import SimpleNamespace
from temper_ai.pi_agent.host import pin_for
from temper_ai.stage.loader import GraphLoader
from temper_ai.stage.models import NodeConfig

class Store:
    def get(self, name, config_type):
        return {"agent": {"name": "scout_talk", "type": "pi", "role": "scout",
                          "provider": "openai-codex", "model": "gpt-6.1-sol",
                          "thinking": "medium", "tools": ["Read"], "add_ons": [],
                          "message": "Read note.txt and tell me its first word."}}

node = GraphLoader(config_store=Store())._resolve_agent_node(NodeConfig.from_dict(
    {"name": "talk", "type": "agent", "agent": "scout_talk", "depends_on": ["brief"]}))
box = SimpleNamespace(pi_version="0.87.1", image="img", add_ons={},
                      routes={"openai-codex": SimpleNamespace(extension=None, host="h")},
                      identity_extension=sys.argv[1])
print(json.dumps(pin_for(box, node.agent_config, workflow="w"), sort_keys=True))
"""


def test_the_settings_pin_is_the_same_in_every_worker_process(tmp_path):
    """An answered wait carries the run on in a new worker process, which reopens the Pi
    conversation only if its settings pin matches the first worker's. The pin is taken from
    the step's config as the real loader resolves it -- which carries the node's
    ``_KNOWN_FIELDS`` set, printed in an order that changes with each process's string-hash
    salt -- so three processes with three hash seeds must agree (C7's rehearsal found it)."""
    import os
    import subprocess
    import sys

    (tmp_path / "identity").mkdir()
    (tmp_path / "identity" / "index.ts").write_text("export {}\n")
    pins = set()
    for seed in ("1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(sup.WORKTREE)}
        out = subprocess.run([sys.executable, "-c", _PIN_IN_A_NEW_PROCESS,
                              str(tmp_path / "identity")],
                             cwd=sup.WORKTREE, env=env, capture_output=True, text=True,
                             timeout=60, check=True)
        pins.add(out.stdout.strip())
    assert len(pins) == 1, "the same settings gave different pins in different processes"
