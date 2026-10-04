"""Pi runs that let go of their worker at an approval (temper_ai/runner/parked.py).

Builds on L2's stand-in Pi (tests/test_pi_agent/support.py): the same fake box, stub loader
and ordinary steps, plus a gated step, a failing step, a count of what each step ran, and
ways to read back the waits, attempts and threads of a run.
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any

from temper_ai.agent.base import AgentABC
from temper_ai.shared.types import AgentResult, Status
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.models import NodeConfig
from tests.test_pi_agent import support as sup

FAIL_TYPE = "pi_waits_fail"
VERDICT_TYPE = "pi_waits_verdict"

#: How many times each ordinary step's agent ran, by node name (reset by the fixture).
RAN: Counter[str] = Counter()
#: What the verdict step says: "again" sends its loop round once more (set by a test).
VERDICT = {"say": "again"}


class FailAgent(AgentABC):
    """An ordinary step that fails every time it runs."""

    def run(self, input_data: dict, context: Any) -> AgentResult:
        RAN[self.name] += 1
        return AgentResult(status=Status.FAILED, output="", error=f"{self.name} failed")


class VerdictAgent(AgentABC):
    """A review step: says VERDICT["say"] as its structured verdict."""

    def run(self, input_data: dict, context: Any) -> AgentResult:
        RAN[self.name] += 1
        say = VERDICT["say"]
        return AgentResult(status=Status.COMPLETED, output=say, structured_output={"verdict": say})


def gated(name: str, depends_on=()) -> AgentNode:
    """An ordinary step behind an approval (``gate: true``)."""
    return AgentNode(NodeConfig(name=name, depends_on=list(depends_on), gate=True),
                     {"name": name, "type": sup.STEP_TYPE})


def failing(name: str, depends_on=()) -> AgentNode:
    return AgentNode(NodeConfig(name=name, depends_on=list(depends_on)),
                     {"name": name, "type": FAIL_TYPE})


def review_loop(name: str = "review", depends_on=("talk",), on_max_loops: str = "fail") -> AgentNode:
    """A gated review that goes round again while it says "again", at most twice."""
    config = NodeConfig(name=name, depends_on=list(depends_on), gate=True, loop_to=name,
                        max_loops=2, on_max_loops=on_max_loops,
                        loop_condition={"source": f"{name}.structured.verdict",
                                        "operator": "equals", "value": "again"})
    return AgentNode(config, {"name": name, "type": VERDICT_TYPE})


WORKFLOWS = {
    # A gate after the Pi step: the run lets go once the Pi step is done.
    "pw_after_pi": lambda: [sup.step("brief"), sup.pi_node(), gated("check", ["talk"]),
                            sup.step("ship", ["check"])],
    # The first node waits on you: nothing has run, nothing is checkpointed.
    "pw_first": lambda: [gated("ask"), sup.pi_node(depends_on=("ask",)),
                         sup.step("audit", ["talk"])],
    # A gate before the Pi step.
    "pw_before_pi": lambda: [sup.step("brief"), gated("check", ["brief"]),
                             sup.pi_node(depends_on=("check",))],
    # Two approvals one after the other: the run lets go twice.
    "pw_two_gates": lambda: [sup.step("brief"), gated("first", ["brief"]),
                             gated("second", ["first"]), sup.pi_node(depends_on=("second",))],
    # A gate next to a step that runs at the same time.
    "pw_side_by_side": lambda: [sup.step("brief"), gated("left", ["brief"]),
                                sup.step("right", ["brief"]),
                                sup.pi_node(depends_on=("left", "right"))],
    # Each round of a gated loop waits on you; running out stops the run red.
    "pw_loop": lambda: [sup.step("brief"), sup.pi_node(), review_loop(),
                        sup.step("ship", ["review"])],
    # A Pi workflow whose first step fails before anything is checkpointed.
    "pw_fails_first": lambda: [failing("first"), sup.pi_node(depends_on=("first",))],
    # Workflows without a Pi step: unchanged.
    "plain_gate": lambda: [sup.step("brief"), gated("check", ["brief"]), sup.step("ship", ["check"])],
    "plain_fails_first": lambda: [failing("plain_first"), sup.step("after", ["plain_first"])],
}


# --- reading a run back ------------------------------------------------------------------


def attempts(eid: str) -> list[dict]:
    return sup.attempts(eid)


def parked(attempt: dict) -> dict | None:
    """The attempt's parked record, when it let go at an approval."""
    value = (attempt.get("data") or {}).get("parked")
    return value if isinstance(value, dict) else None


def waits(eid: str, name: str) -> list[dict]:
    """Every approval wait a gated step opened (its stage.started events with a wait path)."""
    return [e for e in sup.events(eid, event_type="stage.started")
            if (e.get("data") or {}).get("name") == name and (e.get("data") or {}).get("gate_path")]


def run_threads(eid: str) -> list[threading.Thread]:
    """The threads running this run in the server (in-process mode names them after it)."""
    return [t for t in threading.enumerate() if t.name == f"temper-run-{eid}" and t.is_alive()]


def wait_parked(state, eid: str, n_attempts: int = 1, timeout: float = 20.0) -> dict:
    """Wait until attempt ``n_attempts`` has let go at an approval and no thread holds the run."""
    def ready():
        a = attempts(eid)
        if len(a) < n_attempts or a[-1]["status"] != "waiting" or not parked(a[-1]):
            return None
        if eid in state.running or run_threads(eid):
            return None
        return a[-1]
    return sup.wait_for(ready, timeout, what=f"attempt {n_attempts} of {eid} to let go")


def wait_ended(eid: str, n_attempts: int, timeout: float = 20.0) -> list[dict]:
    """Wait until attempt ``n_attempts`` has finished (completed, failed or cancelled)."""
    def ended():
        a = attempts(eid)
        if len(a) >= n_attempts and a[-1]["status"] in ("completed", "failed", "cancelled"):
            return a
        return None
    return sup.wait_for(ended, timeout, what=f"attempt {n_attempts} of {eid} to end")


def open_gate(client, eid: str, name: str, timeout: float = 20.0) -> dict:
    """The open wait of a gated step, as GET .../gates lists it."""
    def find():
        listed = client.get(f"/api/runs/{eid}/gates").json()["gates"]
        return next((g for g in listed if g["node_name"] == name and g["event_id"]), None)
    return sup.wait_for(find, timeout, what=f"an open wait at {name} in {eid}")


def approve(client, eid: str, name: str, *, event_id: str | None = None,
            request_id: str | None = None, response: str = "go on"):
    body: dict[str, Any] = {"response": response}
    if event_id:
        body["event_id"] = event_id
    if request_id:
        body["request_id"] = request_id
    return client.post(f"/api/runs/{eid}/approve/{name}", json=body)


def finish_pi(client, eid: str) -> None:
    """Answer the Pi step's own "what next" wait with ``done``: the step finishes."""
    wait = sup.open_wait(eid, "owner")
    r = sup.approve(client, eid, wait["gate_name"], "done")
    assert r.status_code == 200, r.text


def detail(client, eid: str) -> dict:
    r = client.get(f"/api/workflows/{eid}")
    assert r.status_code == 200, r.text
    return r.json()


def listed(client, eid: str) -> dict:
    r = client.get("/api/workflows", params={"limit": 50})
    assert r.status_code == 200, r.text
    return next(w for w in r.json()["runs"] if eid in (w.get("execution_id"), w.get("id")))


def agent_runs(eid: str, name: str) -> int:
    """How many times a step's agent started, from the stored events."""
    return sum(1 for e in sup.events(eid, event_type="agent.started")
               if (e.get("data") or {}).get("agent_name", (e.get("data") or {}).get("name")) == name)
