"""The owner's own controls, tried once on the live temper after each deploy.

The live look (``deploy.live_check``) asks the temper that is serving people whether it
is up, runs a free run and shows the dashboard. These parts try what the owner does to
his live Projects, and what Security asked to have looked at:

* an ordinary run's box environment: ``ci_box_env`` completes, and its one step with it.
  Its probe fails itself when a server-only name is in a box or a secret is in a tool's
  environment (configs/agents/ci_box_env.yaml, docs/boxes.md). It prints names, never
  values, and nothing of its output is copied here. It covers its own box, an ordinary
  run's: Pi member boxes are not covered (Security's watch covers those during a
  Project). Fail closed (Security, rm-ddba2969): an error, a timeout, or a cancel by
  anyone but temper-ci itself fails it. It goes first, being the shortest;
* stop, then resume: a ``ci_slow`` run is stopped mid-step, leaves a checkpoint, and is
  resumed to the end;
* a gate answered through the API: a ``gate_smoke`` run parks at its gate, temper-ci's
  key answers it, the run completes, and the decision names temper-ci as its caller.

They run on the live temper because there is no other (AGENTS.md rule 15: no separate
copies of Temper). Until 2026-10-08 they ran in a throwaway temper per commit
(``git show c8a4788c:scripts/temper_ci/smoke.py``). Every workflow here is script agents
only: they cost nothing.

Quiet: every run started here says ``notify`` off for every kind, so none of them reaches
the owner's Slack or Telegram. They do show in the dashboard's run list (temper has no
way to hide a run), never on the Team page.

Tidy: pass or fail, each check cancels the runs it started that have not ended, before
its verdict. A run left going would hold every later deploy, and the revert of this one
too (``deploy.LIVE_STATUSES``). A run that will not end even then fails the check.

Never beside another run: each box on the live temper while a Team Project runs is a
STOP for Security's watch of that Project (Security, rm-ddba2969). The deploy itself waits
until no run is going, so the look normally has the temper to itself; if someone else's
run is going all the same, a part does not start, and a part under way stops its own
runs at once. Either way that part is owed: not passed, and not failed. Owed only on
temper-ci's own record, though (Security, reply to rm-e71dc2dc): the runs it cancelled
have ended, and none of them has a box left up; a part that cannot show both fails. The
deploy stays live but is not recorded as good, and temper-ci tries the owed parts again
once no run is going, before any newer deploy (deploy.settle_owed); only then does the
commit become the one to go back to. The third look in a row at a commit that ends owed
fails it.

A part that fails counts like the live look's other parts: the live check fails, and the
deploy is reverted.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")

# notify off for every kind (docs/notify.md): the run's own block wins over every other.
QUIET = {"question": "off", "stuck": "off", "failed": "off", "finished": "off"}
# The statuses of a run that is not over yet: the same list the deploy waits on
# (deploy.LIVE_STATUSES; a test keeps the two equal). Anything else is over.
NOT_OVER = ("pending", "queued", "running", "waiting", "cancelling")
POLL_SECONDS = 2.0
# How long ci_slow's long step has been going when it is stopped.
MID_STEP_SECONDS = 5.0
TIDY_REASON = "temper-ci's live look tidies up its own run"
# How often a check that is waiting looks for someone else's run (see Overlap).
OTHERS_EVERY = 10.0
# A run's box is a container labelled with the run's id (temper_ai/spawner/docker_spawner.py).
# It goes a moment after its run ends; a part that stepped aside gives it this long.
BOX_LABEL = "temper.execution_id"
BOX_GONE_SECONDS = 60.0

FREE_RUN = "a free run on the live temper"
FREE_RUN_WORKFLOW = "smoke_test"      # what the dashboard's look expects to see listed
STOP_THEN_RESUME = "stop, then resume"
GATE_THROUGH_API = "a gate answered through the API"
BOX_ENV = "an ordinary run's box environment"


class LiveError(Exception):
    """A check found something wrong; the message says what."""


class Overlap(Exception):  # noqa: N818 - it is not an error: the part steps aside
    """Someone else's run is going on the live temper, so this part steps aside.

    ``runs`` are those runs, as the run list showed them: id, workflow, status.
    """

    def __init__(self, runs: list[dict]) -> None:
        self.runs = runs
        said = ", ".join(f"{r['id'][:8]} ({r['workflow']}, {r['status']})" for r in runs[:3])
        super().__init__(f"someone else's run is going: {said}")


def _box_up(run_id: str) -> bool:
    """Is a box of this run still up? Asked of docker on the host, by the run's label."""
    r = subprocess.run(["docker", "ps", "-q", "--filter", f"label={BOX_LABEL}={run_id}"],  # noqa: S607
                       capture_output=True, text=True, timeout=30, check=False)
    if r.returncode:
        raise LiveError(f"docker could not say (exit {r.returncode}: {(r.stderr or '').strip()[:120]})")
    return bool(r.stdout.strip())


@dataclass
class Live:
    """The live API as one check talks to it: temper-ci's key on every call, and a list
    of the runs this check started, which ``tidy`` ends."""

    api: str
    headers: dict[str, str] = field(default_factory=dict)
    # Looked up when called, not when this module is loaded, so a test's stand-in clock reaches them.
    sleep: Callable[[float], None] = field(default=lambda seconds: time.sleep(seconds))
    clock: Callable[[], float] = field(default=lambda: time.monotonic())
    box_up: Callable[[str], bool] = field(default=lambda run_id: _box_up(run_id))
    started: list[str] = field(default_factory=list)
    looked_for_others: float = float("-inf")

    # -- talking to it ------------------------------------------------------

    def call(self, method: str, path: str, body: object = None, timeout: int = 30):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(  # noqa: S310 - the live temper, on loopback
            self.api + path, data=data, method=method,
            headers={"Content-Type": "application/json", **self.headers})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            text = resp.read().decode()
        return json.loads(text) if text else {}

    def get(self, path: str, timeout: int = 30):
        return self.call("GET", path, timeout=timeout)

    def post(self, path: str, body: object = None, timeout: int = 30):
        return self.call("POST", path, {} if body is None else body, timeout=timeout)

    # -- runs ---------------------------------------------------------------

    def start(self, workflow: str, inputs: dict | None = None) -> str:
        got = self.post("/api/runs", {"workflow": workflow, "inputs": inputs or {}, "notify": QUIET},
                        timeout=60)
        run_id = str((got or {}).get("execution_id") or "") if isinstance(got, dict) else ""
        if not run_id:
            raise LiveError(f"starting {workflow} gave back no run id")
        self.started.append(run_id)
        return run_id

    def run(self, run_id: str) -> dict:
        got = self.get(f"/api/workflows/{run_id}")
        return got if isinstance(got, dict) else {}

    def status(self, run_id: str) -> str:
        return str(self.run(run_id).get("status") or "")

    # -- never beside someone else's run ----------------------------------------

    def others(self) -> list[dict]:
        """The runs going on the live temper that this check did not start."""
        mine = set(self.started)
        found: list[dict] = []
        for status in NOT_OVER:
            got = self.get(f"/api/workflows?status={status}&limit=20")
            rows = got.get("runs") if isinstance(got, dict) else got
            for row in rows or []:
                run_id = str((row or {}).get("id") or "") if isinstance(row, dict) else ""
                if run_id and run_id not in mine:
                    found.append({"id": run_id, "workflow": str(row.get("workflow_name") or "?"),
                                  "status": status})
        return found

    def step_aside(self, *, now: bool = False) -> None:
        """Raise Overlap when someone else's run is going.

        Asked before a part starts (``now``: a dropped read is asked again, and a temper
        that cannot say within 30 s fails the part), then every ``OTHERS_EVERY`` seconds
        while it waits (a missed read there is let pass: the wait's own reads notice a
        temper that stopped answering).
        """
        if not now and self.clock() - self.looked_for_others < OTHERS_EVERY:
            return
        self.looked_for_others = self.clock()
        if now:
            others = self._looked(self.others, "which runs are going", self.clock() + 30)
        else:
            try:
                others = self.others()
            except Exception:  # noqa: BLE001 - let pass, as above
                return
        if others:
            raise Overlap(others)

    def pause(self, seconds: float) -> None:
        """Wait, then make sure the temper is still the look's alone."""
        self.sleep(seconds)
        self.step_aside()

    def _looked(self, ask: Callable[[], T], what: str, deadline: float) -> T:
        """``ask()``, asked again on an error until ``deadline``: one missed read of a run is
        not the run going wrong, and a failed part reverts the deploy."""
        while True:
            try:
                return ask()
            except Exception as exc:  # noqa: BLE001 - raised below once the time is up
                if self.clock() >= deadline:
                    raise LiveError(f"could not read {what}: {_said(exc)}") from exc
                self.sleep(POLL_SECONDS)

    def wait_for(self, run_id: str, want: tuple[str, ...] = ("completed",), seconds: float = 240) -> str:
        """Wait until the run is in one of ``want``; a run that ends otherwise fails at once."""
        deadline = self.clock() + seconds
        status = ""
        while True:
            status = str(self._looked(lambda: self.status(run_id), f"run {run_id[:8]}", deadline))
            if status in want:
                return status
            if status and status not in NOT_OVER:
                raise LiveError(f"run {run_id[:8]} ended as {status}; it was meant to reach "
                                f"{'/'.join(want)}")
            if self.clock() >= deadline:
                raise LiveError(f"run {run_id[:8]} was still {status or 'unknown'} after {seconds:.0f} s")
            self.pause(POLL_SECONDS)

    def open_wait(self, run_id: str, seconds: float = 180) -> dict:
        """The first wait open on the run, as ``GET .../gates`` lists it."""
        deadline = self.clock() + seconds
        while True:
            got = self._looked(lambda: self.get(f"/api/runs/{run_id}/gates"),
                               f"the gates of {run_id[:8]}", deadline)
            waits = got if isinstance(got, list) else (got.get("gates") or [])
            if waits:
                return waits[0]
            status = str(self._looked(lambda: self.status(run_id), f"run {run_id[:8]}", deadline))
            if status and status not in NOT_OVER:
                raise LiveError(f"run {run_id[:8]} ended as {status} without ever opening its gate")
            if self.clock() >= deadline:
                raise LiveError(f"no gate opened on {run_id[:8]} within {seconds:.0f} s (it is {status or 'unknown'})")
            self.pause(POLL_SECONDS)

    def tidy(self, seconds: float = 90) -> tuple[list[str], list[str]]:
        """Cancel each run this check started that has not ended, and wait for it to end.

        Returns (cancelled, left): the ids of the runs it cancelled, and the ones still not
        over (or that could not be asked about) when it gave up, each as a short line.
        """
        cancelled: list[str] = []
        left: list[str] = []
        for run_id in dict.fromkeys(self.started):
            try:
                status = self.status(run_id)
            except Exception as exc:  # noqa: BLE001 - said, and counted as left going
                left.append(f"{run_id[:8]} (could not ask: {type(exc).__name__})")
                continue
            if status and status not in NOT_OVER:
                continue
            try:
                self.post(f"/api/runs/{run_id}/cancel", {"reason": TIDY_REASON})
            except Exception:  # noqa: BLE001, S110 - whether it ended is looked at next
                pass
            cancelled.append(run_id)
            deadline = self.clock() + seconds
            while True:
                try:
                    status = self.status(run_id)
                except Exception:  # noqa: BLE001 - ask again until the deadline
                    status = "unknown"
                if status and status not in NOT_OVER and status != "unknown":
                    break
                if self.clock() >= deadline:
                    left.append(f"{run_id[:8]} still {status or 'unknown'}")
                    break
                self.sleep(POLL_SECONDS)
        return cancelled, left

    def boxes_left(self, seconds: float = BOX_GONE_SECONDS) -> list[str]:
        """Each run this check started whose box is still up after ``seconds`` (or that docker
        could not answer about), as a short line. Asked again until then: a box goes a
        moment after its run ends."""
        deadline = self.clock() + seconds
        while True:
            left: list[str] = []
            for run_id in dict.fromkeys(self.started):
                try:
                    if self.box_up(run_id):
                        left.append(f"{run_id[:8]}'s box is up")
                except Exception as exc:  # noqa: BLE001 - not knowing is not gone
                    left.append(f"{run_id[:8]}'s box: {_said(exc)}")
            if not left or self.clock() >= deadline:
                return left
            self.sleep(POLL_SECONDS)


# -- the checks --------------------------------------------------------------
# Each takes a Live of its own and returns what it saw; it raises when something is wrong.


def free_run(live: Live) -> str:
    """One free run, in a box: the first thing a person would try. Does it run anything?"""
    run_id = live.start(FREE_RUN_WORKFLOW, {"message": "after the deploy"})
    live.wait_for(run_id, ("completed",), seconds=240)
    return f"{FREE_RUN_WORKFLOW} {run_id[:8]} completed (at {live.api})"


def stop_then_resume(live: Live) -> str:
    """The owner's Stop and Resume, on a run in the middle of a step."""
    run_id = live.start("ci_slow", {"seconds": "40"})
    # Stop it a few seconds after `before` is done and `work` (40 s of sleep) has begun: about
    # 12 s in, mid-step, and never before `before` has left a checkpoint to come back to.
    deadline = live.clock() + 120
    while True:
        run = live._looked(lambda: live.run(run_id), f"run {run_id[:8]}", deadline)
        nodes = {str(n.get("name")): str(n.get("status")) for n in run.get("nodes") or []}
        if nodes.get("before") == "completed" and nodes.get("work") not in (None, "", "pending"):
            break
        status = str(run.get("status") or "")
        if status and status not in NOT_OVER:
            raise LiveError(f"{run_id[:8]} ended as {status} before it could be stopped; nodes: {nodes}")
        if live.clock() >= deadline:
            raise LiveError(f"{run_id[:8]} never got to its long step within 120 s; nodes: {nodes}")
        live.pause(1)
    live.pause(MID_STEP_SECONDS)
    live.post(f"/api/runs/{run_id}/cancel", {"reason": "temper-ci's live look stops it on purpose"})
    deadline = live.clock() + 90
    while True:
        stopped = str(live._looked(lambda: live.status(run_id), f"run {run_id[:8]}", deadline))
        if stopped == "completed":
            raise LiveError(f"{run_id[:8]} finished instead of stopping")
        if stopped and stopped not in NOT_OVER:
            break
        if live.clock() >= deadline:
            raise LiveError(f"{run_id[:8]} would not stop; it is {stopped or 'unknown'} after 90 s")
        live.pause(POLL_SECONDS)
    got = live.get(f"/api/runs/{run_id}/checkpoints")
    rows = got if isinstance(got, list) else (got.get("checkpoints") or [])
    if not rows:
        raise LiveError(f"{run_id[:8]} stopped ({stopped}), but left no checkpoint to resume from")
    # What the dashboard's Resume sends when nothing is ticked to run again.
    resumed = live.post(f"/api/runs/{run_id}/resume", {}, timeout=60)
    again = str((resumed or {}).get("execution_id") or run_id) if isinstance(resumed, dict) else run_id
    if again != run_id:
        live.started.append(again)
    live.wait_for(again, ("completed",), seconds=240)
    return (f"ci_slow {run_id[:8]}: stopped mid-step ({stopped}), {len(rows)} checkpoint(s), "
            f"resumed{'' if again == run_id else ' as ' + again[:8]} and completed")


def gate_through_api(live: Live, caller: str) -> str:
    """A gate answered over the API with temper-ci's key, and the record of who answered."""
    run_id = live.start("gate_smoke")
    wait = live.open_wait(run_id, seconds=180)
    node = str(wait.get("node_name") or wait.get("node") or "")
    if not node:
        raise LiveError(f"the gate open on {run_id[:8]} names no step: {wait}")
    body = {"response": "temper-ci's live look says yes", "by": "temper-ci (live look)"}
    if wait.get("event_id"):
        body["event_id"] = str(wait["event_id"])
    live.post(f"/api/runs/{run_id}/approve/{node}", body)
    live.wait_for(run_id, ("completed",), seconds=180)
    got = live.get(f"/api/runs/{run_id}/decisions")
    rows = got if isinstance(got, list) else (got.get("decisions") or [])
    callers = sorted({str(r.get("caller") or "") for r in rows if isinstance(r, dict)})
    if caller not in callers:
        raise LiveError(f"gate_smoke {run_id[:8]} completed, but its decision does not name "
                        f"{caller}; callers: {callers or 'none'}")
    return f"gate_smoke {run_id[:8]}: the gate on '{node}' answered by {caller}, and the run completed"


def box_env(live: Live) -> str:
    """No server-only name in its own box, no secret in its tools' environment.

    Fail closed: the run must complete, and so must every step it lists (its probe exits 0
    only when it found nothing). Only statuses and step names are read; never its output.
    """
    run_id = live.start("ci_box_env")
    live.wait_for(run_id, ("completed",), seconds=180)
    deadline = live.clock() + 30
    nodes = {str(n.get("name")): str(n.get("status"))
             for n in live._looked(lambda: live.run(run_id), f"run {run_id[:8]}", deadline).get("nodes") or []}
    if not nodes or any(status != "completed" for status in nodes.values()):
        raise LiveError(f"ci_box_env {run_id[:8]} completed, but not every step did: {nodes or 'none listed'}")
    return (f"ci_box_env {run_id[:8]} completed in its own box (an ordinary run's): no server-only "
            "name, no secret in its tools. Pi member boxes are not covered here")


# -- running them --------------------------------------------------------------


def checks(caller: str) -> list[tuple[str, Callable[[Live], str]]]:
    """The checks, in the order they run, each with the name its part goes by."""
    return [
        (BOX_ENV, box_env),
        (STOP_THEN_RESUME, stop_then_resume),
        (GATE_THROUGH_API, lambda live: gate_through_api(live, caller)),
    ]


def run_one(name: str, check: Callable[[Live], str], live: Live) -> dict:
    """One check as a part of the live look: ok, what it saw, how long it took.

    Its runs are tidied whatever happened, and before the verdict: a run it could not end
    fails it, even when everything else went well. A part that steps aside for someone
    else's run (Overlap) is owed: ``ok`` is None, neither passed nor failed, and ``owed``
    is true, with temper-ci's own record of it: ``because`` (the other runs' ids) and
    ``cancelled`` (its own). Only when its runs have ended and none has a box left up,
    though (Security, reply to rm-e71dc2dc); otherwise it fails.
    """
    began = live.clock()
    ok: bool | None
    aside: Overlap | None = None
    try:
        live.step_aside(now=True)
        detail, ok = check(live), True
    except Overlap as exc:
        aside, ok = exc, None
        detail = f"{'stopped part-way' if live.started else 'not started'}: {exc}"
    except Exception as exc:  # noqa: BLE001 - a failed check is a result, not a crash
        detail, ok = _said(exc), False
    finally:
        try:
            cancelled, left = live.tidy()
        except Exception as exc:  # noqa: BLE001 - tidy must not take the look down
            cancelled, left = [], [f"tidying failed: {type(exc).__name__}: {exc}"]
    tail = f"; cancelled its own {', '.join(c[:8] for c in cancelled)}" if cancelled else ""
    if left:
        ok = False
        tail += f"; LEFT GOING: {', '.join(left)}"
    elif aside is not None:
        boxes = live.boxes_left()
        if boxes:
            ok = False
            tail += f"; BOX LEFT UP: {', '.join(boxes)}"
    if aside is not None:
        detail += ("; the look never runs beside another run, so temper-ci tries it again once "
                   "no run is going" if ok is None else
                   "; it stepped aside, but did not leave the temper as it found it, so it fails")
    seconds = live.clock() - began
    owed = aside is not None and ok is None
    said = f"{'owed, ' if owed else ''}{detail}{tail} ({seconds:.0f} s)"
    result: dict = {"name": name, "ok": ok, "detail": said[:600], "seconds": round(seconds, 1)}
    if owed and aside is not None:
        result.update(owed=True, because=[str(r["id"]) for r in aside.runs], cancelled=list(cancelled))
    return result


def run_all(api: str, headers: dict[str, str], caller: str, only: Collection[str] | None = None,
            **live_kw) -> list[dict]:
    """Every check (or those named in ``only``), one after another, each with a Live of its own."""
    return [run_one(name, check, Live(api, dict(headers), **live_kw))
            for name, check in checks(caller) if only is None or name in only]


def _said(exc: BaseException) -> str:
    if isinstance(exc, LiveError):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode(errors="replace")[:200]
        except Exception:  # noqa: BLE001
            body = ""
        return f"HTTP {exc.code} from {exc.url or 'the live temper'}{': ' + body if body else ''}"
    return f"{type(exc).__name__}: {exc}"
