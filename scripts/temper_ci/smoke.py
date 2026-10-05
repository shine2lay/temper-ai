"""The smoke set: what a commit has to survive in its throwaway temper.

Every check here costs nothing. The stack has no model keys at all, so the
workflows it runs (``smoke_test``, ``ci_parallel``, ``ci_slow``,
``gate_smoke``) use script agents only; if a commit ever made one of them
call a model, the box has no key and the check fails loudly, which is the
behaviour we want.

Each check returns a :class:`Result`. A check that raises is a failure with
the error as its reason — nothing here is allowed to take the whole run
down, because the report is most useful exactly when something broke.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .paths import log, sh
from .stack import Box, BoxError


@dataclass
class Result:
    name: str
    what: str            # what it proves, in the owner's words
    ok: bool = False
    detail: str = ""
    seconds: float = 0.0
    shots: list[str] = field(default_factory=list)


def _timed(name: str, what: str, fn) -> Result:
    started = time.time()
    try:
        detail = fn() or ""
        return Result(name, what, True, str(detail), time.time() - started)
    except Exception as exc:  # noqa: BLE001 - a failed check is a result, not a crash
        return Result(name, what, False, f"{type(exc).__name__}: {exc}", time.time() - started)


# -- the checks --------------------------------------------------------------


def plain_run(box: Box) -> str:
    run_id = box.start_run("smoke_test", {"message": "boxes"})
    box.wait_for(run_id, ("completed",), seconds=180)
    out = box.get(f"/api/workflows/{run_id}")
    return f"smoke_test {run_id[:8]} completed ({out.get('status')})"


def box_env(box: Box) -> str:
    # The probe step fails itself when a server-only name is anywhere in the box or a
    # secret is in a tool's environment (configs/agents/ci_box_env.yaml, docs/boxes.md).
    run_id = box.start_run("ci_box_env")
    box.wait_for(run_id, ("completed",), seconds=180)
    return f"ci_box_env {run_id[:8]} completed: no server-only name in the box, no secret in its tools"


def parallel_and_stage(box: Box) -> str:
    run_id = box.start_run("ci_parallel")
    box.wait_for(run_id, ("completed",), seconds=240)
    run = box.get(f"/api/workflows/{run_id}")
    nodes = {str(n.get("name")): str(n.get("status")) for n in (run.get("nodes") or [])}
    for wanted in ("start", "left", "right", "join"):
        if nodes.get(wanted) != "completed":
            raise BoxError(f"node '{wanted}' is {nodes.get(wanted) or 'missing'}; nodes: {nodes}")
    # The three agents of the stage in 'right' are named in the workflow; the run has to show
    # all three, and one of them has to have led — which is what makes it a stage and not
    # three agents in a row. (Their node_name is the stage's, which the engine may name after
    # the node or after the stage itself, so go by the agents' own names.)
    rows = (box.get(f"/api/workflows/{run_id}/agents") or {}).get("agents") or []
    names = {str(a.get("agent_name") or "") for a in rows}
    missing = [n for n in ("right_one", "right_two", "right_lead") if n not in names]
    if missing:
        raise BoxError(f"the stage in 'right' never ran {', '.join(missing)}; agents: {sorted(names)}")
    # Six agents in four nodes: one to start, one on the left, three in the stage on the right,
    # and the join, which only runs when both branches are done.
    if len(rows) < 6:
        raise BoxError(f"the run started {len(rows)} agents, not the six the workflow describes")
    return (f"ci_parallel {run_id[:8]} completed: {', '.join(sorted(nodes))}; "
            f"{len(rows)} agents, the stage in 'right' among them, and the join saw both branches")


def gate_through_api(box: Box) -> str:
    run_id = box.start_run("gate_smoke")
    node = ""
    deadline = time.time() + 180
    while time.time() < deadline:
        gates = box.get(f"/api/runs/{run_id}/gates")
        waiting = gates if isinstance(gates, list) else gates.get("gates", [])
        if waiting:
            node = str(waiting[0].get("node_name") or waiting[0].get("node") or "")
            break
        time.sleep(2)
    if not node:
        raise BoxError("no gate ever appeared on gate_smoke")
    box.post(f"/api/runs/{run_id}/approve/{node}", {"response": "the machine check says yes"})
    box.wait_for(run_id, ("completed",), seconds=180)
    decisions = box.get(f"/api/runs/{run_id}/decisions")
    rows = decisions if isinstance(decisions, list) else decisions.get("decisions", [])
    return f"gate on '{node}' answered through the API; {len(rows)} decision(s) recorded"


def _waiting_node(box: Box, run_id: str, seconds: int = 180) -> str:
    deadline = time.time() + seconds
    while time.time() < deadline:
        gates = box.get(f"/api/runs/{run_id}/gates")
        waiting = gates if isinstance(gates, list) else gates.get("gates", [])
        if waiting:
            return str(waiting[0].get("node_name") or waiting[0].get("node") or "")
        time.sleep(2)
    raise BoxError(f"no gate ever appeared on {run_id[:8]}")


def write_guard(box: Box) -> str:
    """The write guard in enforce (docs/api-access.md), the way security's repro goes.

    A gate_smoke run parks; a keyless answer from outside is refused; a run whose
    workflow holds its own key (ci_run_token) tries to answer and cancel it from its
    box and is refused, and starts a smoke_test run, which it may. The wait is still
    open after all that, and the check's own key then answers it, under its name.
    """
    waiting = box.start_run("gate_smoke")
    node = _waiting_node(box, waiting)
    status, _ = box.status_of("POST", f"/api/runs/{waiting}/approve/{node}",
                              raw=b'{"response": "no key"}', with_key=False)
    if status != 401:
        raise BoxError(f"a keyless approve came back {status}, not 401")
    probe = box.start_run("ci_run_token", {"wait_run": waiting, "wait_node": node})
    box.wait_for(probe, ("completed",), seconds=180)
    run = box.get(f"/api/workflows/{probe}")
    seen = (run.get("workflow_output") or {}).get("seen") or run.get("output") or ""
    text = seen if isinstance(seen, str) else json.dumps(seen)
    started = ""
    for line in reversed(text.splitlines()):
        try:
            started = str(json.loads(line).get("started") or "")
            break
        except (ValueError, AttributeError):
            continue
    if _waiting_node(box, waiting, seconds=10) != node:
        raise BoxError("the wait is not open any more after the box tried to answer it")
    if started:
        box.wait_for(started, ("completed",), seconds=180)
    box.post(f"/api/runs/{waiting}/approve/{node}", {"response": "the machine check's own key says yes"})
    box.wait_for(waiting, ("completed",), seconds=180)
    decisions = box.get(f"/api/runs/{waiting}/decisions")
    rows = decisions if isinstance(decisions, list) else decisions.get("decisions", [])
    callers = {str(r.get("caller") or "") for r in rows}
    if "temper-ci-box" not in callers:
        raise BoxError(f"the decision does not name its caller; callers seen: {sorted(callers)}")
    return (f"keyless approve 401; box {probe[:8]} refused approve and cancel, started "
            f"{started[:8] or '?'}; wait {waiting[:8]} stayed open, then answered by temper-ci-box")


def stop_then_resume(box: Box) -> str:
    run_id = box.start_run("ci_slow", {"seconds": "40"})
    time.sleep(12)                     # let `before` finish and `work` start
    box.post(f"/api/runs/{run_id}/cancel", {"reason": "the machine check is stopping it on purpose"})
    stopped = time.time() + 90
    state = ""
    while time.time() < stopped:
        state = box.run_status(run_id)
        if state in ("cancelled", "stopped", "failed", "interrupted"):
            break
        time.sleep(2)
    if state not in ("cancelled", "stopped", "failed", "interrupted"):
        raise BoxError(f"the run would not stop; it is {state or 'unknown'}")
    checkpoints = box.get(f"/api/runs/{run_id}/checkpoints")
    rows = checkpoints if isinstance(checkpoints, list) else checkpoints.get("checkpoints", [])
    if not rows:
        raise BoxError("it stopped, but left no checkpoint to resume from")
    box.post(f"/api/runs/{run_id}/resume", {"workflow": "ci_slow"}, timeout=60)
    box.wait_for(run_id, ("completed",), seconds=240)
    return f"{run_id[:8]}: stopped at {state}, {len(rows)} checkpoint(s), resumed and completed"


def fork(box: Box) -> str:
    source = box.start_run("smoke_test", {"message": "to be forked"})
    box.wait_for(source, ("completed",), seconds=180)
    checkpoints = box.get(f"/api/runs/{source}/checkpoints")
    rows = checkpoints if isinstance(checkpoints, list) else checkpoints.get("checkpoints", [])
    if not rows:
        raise BoxError("the finished run left no checkpoint to fork from")
    sequence = int(rows[0].get("sequence", 1))
    made = box.post("/api/runs/fork", {
        "source_execution_id": source, "sequence": sequence, "workflow": "smoke_test",
    }, timeout=60)
    forked = made.get("execution_id") or ""
    if not forked:
        raise BoxError(f"the fork gave back no run id: {made}")
    box.wait_for(forked, ("completed",), seconds=180)
    return f"forked {source[:8]} at sequence {sequence} → {forked[:8]}, which completed on its own"


def restart_mid_run(box: Box) -> str:
    """The run lives in its own box, so the server can go away under it."""
    run_id = box.start_run("ci_slow", {"seconds": "45"})
    time.sleep(12)
    before = box.run_status(run_id)
    box.restart_server()
    after = box.run_status(run_id)
    box.wait_for(run_id, ("completed",), seconds=300)
    return (f"{run_id[:8]} was {before} when the box's server was restarted, "
            f"{after} right after, and it still finished")


def finished_run_page(box: Box, shots: Path) -> tuple[str, list[str]]:
    """The dashboard really renders a finished run \u2014 with the picture to prove it.

    Not merely "a screenshot came out". The dashboard is a single-page app under
    /app (its router's basename), served from the image's built dist; the API's own
    root is a 404 by design. Photographing that 404 and calling it a pass is exactly
    what this check did on its first outing, so now each page has to *show* something
    only the real thing shows.
    """
    run_id = box.start_run("smoke_test", {"message": "for the picture"})
    box.wait_for(run_id, ("completed",), seconds=180)
    shots.mkdir(parents=True, exist_ok=True)
    taken: list[str] = []
    trouble: list[str] = []
    script = Path(__file__).with_name("shot.py")
    # What to expect has to be something the page really shows, and something a page that
    # failed to load its run could not show. The dashboard puts the workflow's name in the
    # title and the run's state in the body; it does not print the raw id anywhere, and the
    # single-page app answers *any* /app/... path with the same shell \u2014 so a run that did not
    # load renders an empty frame with neither of these in it.
    pages = (
        ("runs-list", f"{box.api}/app/", ["smoke_test"]),
        ("finished-run", f"{box.api}/app/workflow/{run_id}", ["smoke_test", "completed"]),
    )
    for name, url, expect in pages:
        target = shots / f"{name}.png"
        args = ["python3", str(script), url, str(target)]
        for text in expect:
            args += ["--expect", text]
        r = sh(*args, timeout=180)
        if target.exists():
            taken.append(target.name)
        if r.returncode != 0:
            why = (r.stdout or "").strip().splitlines()[-1:] or [(r.stderr or "").strip()[:200]]
            trouble.append(f"{name}: {why[0][:220]}")
    if trouble:
        # The pictures stay in the report: a failure you can look at beats a sentence.
        raise BoxError("the dashboard did not show the finished run \u2014 " + "; ".join(trouble))
    return (f"run {run_id[:8]} finished, and the dashboard showed it: the list names its "
            f"workflow, and its own page says completed ({', '.join(taken)})"), taken


def hooks(box: Box) -> str:
    """The public hooks turn away what isn't signed, and take the test entries."""
    said: list[str] = []

    # -- Linear: hex hmac-sha256 of the raw body, with a fresh timestamp.
    body = json.dumps({
        "action": "create", "type": "Comment",
        "webhookTimestamp": int(time.time() * 1000),
        "data": {"id": "box-1", "body": "from the machine check"},
    }).encode()
    secret = "box-linear-secret"
    good = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    code, _ = box.status_of("POST", "/api/hooks/linear", raw=body)
    if code != 401:
        raise BoxError(f"the Linear hook took an unsigned call ({code}); it must refuse it")
    said.append("Linear refused unsigned (401)")
    code, text = box.status_of("POST", "/api/hooks/linear", raw=body,
                               headers={"Linear-Signature": good})
    if code not in (200, 202):
        raise BoxError(f"the Linear hook refused a correctly signed test entry ({code}): {text}")
    said.append(f"Linear took the signed test entry ({code})")

    # -- Notion: the same shape, its own secret and header.
    # Notion names each delivery with an `id`; the hook refuses one without.
    nbody = json.dumps({"id": f"box-notion-{int(time.time())}", "type": "page.created",
                        "entity": {"id": "box-page", "type": "page"}}).encode()
    nsig = "sha256=" + hmac.new(b"box-notion-secret", nbody, hashlib.sha256).hexdigest()
    code, _ = box.status_of("POST", "/api/hooks/notion", raw=nbody)
    if code != 401:
        raise BoxError(f"the Notion hook took an unsigned call ({code}); it must refuse it")
    said.append("Notion refused unsigned (401)")
    code, text = box.status_of("POST", "/api/hooks/notion", raw=nbody,
                               headers={"X-Notion-Signature": nsig})
    if code not in (200, 202):
        raise BoxError(f"the Notion hook refused a correctly signed test entry ({code}): {text}")
    said.append(f"Notion took the signed test entry ({code})")

    # -- Slack's test entry: its own token, and nothing without it.
    code, _ = box.status_of("GET", "/api/test/slack")
    if code != 401:
        raise BoxError(f"the Slack test entry answered without its token ({code})")
    said.append("Slack's test entry refused a call with no token (401)")
    code, text = box.status_of("GET", "/api/test/slack",
                               headers={"X-Temper-Test-Token": "box-slack-test-token"})
    if code != 200:
        raise BoxError(f"the Slack test entry refused its own token ({code}): {text}")
    info = box.get_with_token("/api/test/slack")
    if info.get("slack"):
        raise BoxError("Slack is connected in the throwaway stack; it must be off")
    said.append("Slack's test entry took its token, and says Slack itself is off")

    # -- Telegram: off here, which is what keeps the real bot out of a check.
    tele = box.get("/api/telegram/status")
    if tele.get("running") or tele.get("connected"):
        raise BoxError(f"Telegram is connected in the throwaway stack: {tele}")
    said.append("Telegram is off in the box")
    return "; ".join(said)


# -- the whole set -----------------------------------------------------------

# How many things the set checks, when it gets all the way through. Used to say
# how much was not reached when it stops early.
SET_SIZE = 10


def run_all(box: Box, shots: Path) -> list[Result]:
    """The smoke set, in order, stopping at the first thing that fails.

    Stopping matters. When the stack is properly broken \u2014 a worker that never
    picks anything up, say \u2014 every one of these waits its full three minutes
    before giving up, so carrying on would take twenty-five minutes to say
    what the first one already said, while every other land waits behind it.
    The first failure is the answer; the rest are the same failure again.
    """
    results: list[Result] = []
    stopped_early = False

    def add(name: str, what: str, fn) -> Result | None:
        nonlocal stopped_early
        if stopped_early:
            return None
        r = _timed(name, what, fn)
        log(f"  {'ok  ' if r.ok else 'FAIL'} {name} ({r.seconds:.0f}s) {r.detail[:160]}")
        results.append(r)
        if not r.ok:
            stopped_early = True
            log(f"  stopping here: with '{name}' broken the rest would only say so again, "
                "slowly, while everything else waits")
        return r

    add("plain run", "a workflow runs end to end", lambda: plain_run(box))
    add("box env", "a box holds only the listed variables, its tools no secret",
        lambda: box_env(box))
    add("parallel and stage", "branches run side by side, with a stage inside one",
        lambda: parallel_and_stage(box))
    add("gate", "a gate parks the run and an API answer releases it",
        lambda: gate_through_api(box))
    add("write guard", "a run's box can start a run but not answer or cancel a wait",
        lambda: write_guard(box))
    add("stop and resume", "a stopped run comes back from its checkpoint",
        lambda: stop_then_resume(box))
    add("fork", "a fork of a finished run carries on by itself", lambda: fork(box))
    add("server restart mid-run", "the run lives in its own box and survives the server",
        lambda: restart_mid_run(box))

    shot_files: list[str] = []

    def page() -> str:
        nonlocal shot_files
        detail, shot_files = finished_run_page(box, shots)
        return detail

    r = add("the page", "the dashboard shows a finished run", page)
    if r is not None:
        r.shots = shot_files

    add("hooks", "the public hooks refuse what isn't signed and take the test entries",
        lambda: hooks(box))
    return results
