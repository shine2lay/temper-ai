"""A test step that asks the owner from inside its own work (temper_ai/stage/step_waits.py).

The pattern a real step follows (the team step will, task #38): it keeps a durable record of
how far it got and what it was told, and asks with a wait id taken from that record, so a step
that runs again starts from its record, asks the same wait, and gets the answer instead of
opening a new wait. Here the record is a JSON file per run and step, in the folder named by
``PW_ASK_RECORDS``; a round's "work" is a count.

Nothing here reaches a model or the network: it builds on L2's stand-in Pi
(tests/test_pi_agent/support.py) and #35's helpers (support.py next to this file).
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from temper_ai.agent.base import AgentABC
from temper_ai.shared.types import AgentResult, ExecutionContext, NodeResult, Status
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.node import Node
from temper_ai.stage.stage_node import StageNode
from temper_ai.stage.step_waits import ask_owner, wait_name
from tests.test_pi_agent import support as sup

ASK_TYPE = "pi_waits_ask"
#: The folder the asking steps keep their records in (set by the fixture; by the rehearsal's
#: launcher for its processes).
RECORDS_ENV = "PW_ASK_RECORDS"
#: When set, a file each test appends its counts of what held a parked run to (JSONL).
EVIDENCE_ENV = "PW_PARK_EVIDENCE"

#: How many times each asking step ran (started), by step name.
RUNS: Counter[str] = Counter()
#: Each round's work, by (step name, round): done once per round, however often the step runs.
WORK: Counter[tuple[str, int]] = Counter()
#: Every answer a step read, as (step name, wait id, answer text), in order.
READ: list[tuple[str, str, str]] = []
#: Steps told to fail once (``fail_once``) that have failed already.
FAILED: set[str] = set()
_LOCK = threading.Lock()


def reset() -> None:
    RUNS.clear()
    WORK.clear()
    READ.clear()
    FAILED.clear()


def install(monkeypatch: Any, tmp: Path) -> None:
    """Make the asking step and its workflows known for one test (on top of #35's pw_run):
    everything goes back when the test's monkeypatch does, after pw_run has stopped its runs."""
    from temper_ai.agent import AGENT_TYPES

    monkeypatch.setenv(RECORDS_ENV, str(tmp / "records"))
    monkeypatch.setitem(AGENT_TYPES, ASK_TYPE, AskAgent)
    for name, build in WORKFLOWS.items():
        monkeypatch.setitem(sup.WORKFLOWS, name, build)
    reset()


def wait_id(n: int) -> str:
    """The wait id of the pause after round ``n``: the same however often the step runs."""
    return f"pause-after-round-{n}"


def name_of(path: str, n: int = 1) -> str:
    """What the wait after round ``n`` of the step at ``path`` is called (GET .../gates)."""
    return wait_name(path, wait_id(n))


# --- the step's durable record ---------------------------------------------------------------


def _record_file(run_id: str, path: str) -> Path:
    return Path(os.environ[RECORDS_ENV]) / f"{run_id}--{path}.json"


def load_record(run_id: str, path: str) -> dict[str, Any]:
    f = _record_file(run_id, path)
    if f.exists():
        return json.loads(f.read_text())
    return {"done": 0, "answers": {}}


def _save_record(run_id: str, path: str, record: dict[str, Any]) -> None:
    f = _record_file(run_id, path)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    tmp.replace(f)


def _ask_rounds(name: str, cfg: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    """Do each round's work once and ask after it; the record says what is done already."""
    with _LOCK:
        RUNS[name] += 1
    rounds = int(cfg.get("rounds", 1))
    keep = bool(cfg.get("keep_record", True))
    path = str(context.step_path)
    record = load_record(context.run_id, path) if keep else {"done": 0, "answers": {}}
    for n in range(1, rounds + 1):
        if record["done"] < n:
            with _LOCK:
                WORK[(name, n)] += 1
            record["done"] = n
            if keep:
                _save_record(context.run_id, path, record)
        wid = wait_id(n)
        if wid not in record["answers"]:
            # Raises RunParked when a Pi workflow lets its worker go here.
            answer = ask_owner(context, wid, question=f"Round {n} of {path} is done. Go on?",
                               header="pause", options=("go on", "stop"))
            with _LOCK:
                READ.append((name, wid, answer.text))
            record["answers"][wid] = answer.text
            if keep:
                _save_record(context.run_id, path, record)
        if record["answers"][wid] == "stop":
            break
    return record


def _verdict(record: dict[str, Any]) -> dict[str, Any]:
    answers = dict(record["answers"])
    last = list(answers.values())[-1] if answers else ""
    return {"answers": answers, "verdict": "again" if last == "again" else "done"}


class AskAgent(AgentABC):
    """An agent step that pauses for the owner after each of its rounds.

    Config: ``rounds`` (1), ``keep_record`` (True: a run again starts from its record; False:
    each go starts afresh, as a loop's lap does), ``fail_once`` (fail the first time, after
    its answers).
    """

    def run(self, input_data: dict, context: Any) -> AgentResult:
        record = _ask_rounds(self.name, self.config, context)
        if self.config.get("fail_once"):
            with _LOCK:
                first = self.name not in FAILED
                FAILED.add(self.name)
            if first:
                return AgentResult(status=Status.FAILED, output="",
                                   error=f"{self.name} failed after its answers")
        out = _verdict(record)
        return AgentResult(status=Status.COMPLETED, output=f"{self.name} done: {out['answers']}",
                           structured_output=out)


class AskNode(Node):
    """A step that is not an agent and asks from its own ``run`` (the team step's shape)."""

    def __init__(self, config: NodeConfig, **cfg: Any):
        super().__init__(config)
        self.cfg = cfg

    def run(self, input_data: dict, context: ExecutionContext) -> NodeResult:
        out = _verdict(_ask_rounds(self.name, self.cfg, context))
        return NodeResult(status=Status.COMPLETED, output=f"{self.name} done: {out['answers']}",
                          structured_output=out)


def asking(name: str, depends_on=(), *, rounds: int = 1, gate: bool = False,
           keep_record: bool = True, fail_once: bool = False, **node_cfg: Any) -> AgentNode:
    """An agent step that pauses for the owner after each round."""
    return AgentNode(NodeConfig(name=name, depends_on=list(depends_on), gate=gate, **node_cfg),
                     {"name": name, "type": ASK_TYPE, "rounds": rounds,
                      "keep_record": keep_record, "fail_once": fail_once})


def asking_loop(name: str = "ask", depends_on=("talk",)) -> AgentNode:
    """A step that asks each lap (no record: each lap is a new go) and goes round again while
    the answer is "again", at most twice; running out stops the run red."""
    return asking(name, depends_on, keep_record=False, loop_to=name, max_loops=2,
                  on_max_loops="fail",
                  loop_condition={"source": f"{name}.structured.verdict", "operator": "equals",
                                  "value": "again"})


def team_stage(name: str = "team", depends_on=("talk",), rounds: int = 2) -> StageNode:
    """A stage holding one step that is not an agent and asks (the team stage's shape)."""
    return StageNode(NodeConfig(name=name, type="stage", depends_on=list(depends_on)),
                     [AskNode(NodeConfig(name="asker"), rounds=rounds)])


WORKFLOWS = {
    # A step after the Pi step asks once: the run lets go there.
    "sw_after_pi": lambda: [sup.step("brief"), sup.pi_node(), asking("ask", ["talk"]),
                            sup.step("ship", ["ask"])],
    # Two rounds, a pause after each: two waits, two checkpoints.
    "sw_rounds": lambda: [sup.step("brief"), sup.pi_node(), asking("ask", ["talk"], rounds=2),
                          sup.step("ship", ["ask"])],
    # The first step asks: nothing has run, nothing is checkpointed.
    "sw_first": lambda: [asking("ask"), sup.pi_node(depends_on=("ask",)),
                         sup.step("audit", ["talk"])],
    # A gated step that also asks from inside its work.
    "sw_gated": lambda: [sup.step("brief"), sup.pi_node(), asking("ask", ["talk"], gate=True),
                         sup.step("ship", ["ask"])],
    # Asks each lap of a loop.
    "sw_loop": lambda: [sup.step("brief"), sup.pi_node(), asking_loop(),
                        sup.step("ship", ["ask"])],
    # Asks while the step next to it runs.
    "sw_side_by_side": lambda: [sup.step("brief"), asking("left", ["brief"]),
                                sup.step("right", ["brief"]),
                                sup.pi_node(depends_on=("left", "right"))],
    # Fails once after its answer: Resume runs it again and it asks nothing twice.
    # (No record of its own: the answer it reads again is the one the run kept unspent.)
    "sw_fails": lambda: [sup.step("brief"), sup.pi_node(),
                         asking("ask", ["talk"], keep_record=False, fail_once=True),
                         sup.step("ship", ["ask"])],
    # Not an agent, inside a stage, two rounds (the team stage's shape).
    "sw_stage": lambda: [sup.step("brief"), sup.pi_node(), team_stage(),
                         sup.step("ship", ["team"])],
    # Without a Pi step: the step waits with its worker held, as a gate does there.
    "plain_ask": lambda: [sup.step("brief"), asking("ask", ["brief"]), sup.step("ship", ["ask"])],
}


# --- what holds a parked run, counted ----------------------------------------------------------


def threads_now() -> set[int]:
    """The idents of the threads alive now (taken before a run starts)."""
    return {t.ident for t in threading.enumerate() if t.ident is not None}


def child_processes() -> list[int]:
    """This process's live child processes (from /proc, so no extra package is needed)."""
    me, kids = os.getpid(), []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        # pid (comm) state ppid ...: comm may hold spaces, so split after its closing ')'.
        fields = stat.rsplit(")", 1)[-1].split()
        if len(fields) > 1 and fields[1] == str(me) and fields[0] != "Z":
            kids.append(int(entry.name))
    return sorted(kids)


def _in_temper_code(ident: int | None) -> bool:
    """Is this thread running Temper's code right now (anywhere on its stack)?"""
    frame = sys._current_frames().get(ident) if ident is not None else None
    while frame is not None:
        if f"{os.sep}temper_ai{os.sep}" in frame.f_code.co_filename:
            return True
        frame = frame.f_back
    return False


def held(state: Any, eid: str, *, before: set[int], test: str, mode: str = "inprocess",
         **extra: Any) -> dict[str, Any]:
    """Count what holds the run while it waits on the owner: the server's running entry, the
    run's thread, threads started since the run did (and whether they are idle: a web
    server's request threads stay around between requests), threads running Temper's code,
    and child processes.

    A pytest worker runs many tests in one process, and threads an earlier test left behind
    are still there (a Pi box's socket servers stay blocked in ``accept()`` after their
    socket is closed). Those were alive before this run started, so they cannot be held for
    it: they are listed apart, as ``older_threads_in_temper_code``.

    Written to the evidence file when ``PW_PARK_EVIDENCE`` names one.
    """
    me = threading.get_ident()
    alive = [t for t in threading.enumerate() if t.is_alive() and t.ident != me]
    new = [t for t in alive if t.ident not in before]
    counts: dict[str, Any] = {
        "test": test,
        "mode": mode,
        "database": os.environ.get("TEMPER_DATABASE_URL", "").split(":", 1)[0].split("+")[0],
        "execution_id": eid,
        "running_entry": int(state is not None and eid in getattr(state, "running", {})),
        "run_threads": sum(1 for t in alive if t.name == f"temper-run-{eid}"),
        "new_threads": sorted(t.name for t in new),
        "new_threads_in_temper_code": sorted(t.name for t in new if _in_temper_code(t.ident)),
        "older_threads_in_temper_code": sorted(
            t.name for t in alive if t.ident in before and _in_temper_code(t.ident)),
        "threads_alive": len(alive) + 1,
        "child_processes": child_processes(),
        **extra,
    }
    out = os.environ.get(EVIDENCE_ENV)
    if out:
        with _LOCK, open(out, "a") as f:
            f.write(json.dumps(counts, sort_keys=True) + "\n")
    return counts


def nothing_held(counts: dict[str, Any]) -> bool:
    return (counts["running_entry"] == 0 and counts["run_threads"] == 0
            and not [n for n in counts["new_threads"] if n.startswith("temper-run-")]
            and counts["new_threads_in_temper_code"] == []
            and counts["child_processes"] == [])


# --- reading a run back --------------------------------------------------------------------------


def step_waits(eid: str, path: str) -> list[dict]:
    """Every wait the step at ``path`` asked from inside its work, oldest first."""
    return [e for e in sup.events(eid, event_type="stage.started")
            if (e.get("data") or {}).get("type") == "step_wait"
            and (e.get("data") or {}).get("gate_path") == path]


def checkpoints(client, eid: str, kind: str) -> list[dict]:
    """The run's checkpoints of one kind (``step_parked``, ``gate_parked``, ...)."""
    r = client.get(f"/api/runs/{eid}/checkpoints")
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body.get("checkpoints", body) if isinstance(body, dict) else body
    return [c for c in rows if c.get("event_type") == kind]
