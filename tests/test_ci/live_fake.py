"""A stand-in for the live temper's API, as temper-ci's live look talks to it.

It is put in place of ``urllib.request.urlopen``: no network, no Docker. Each workflow
behaves the way the real one does, as far as the look can tell:

* smoke_test and ci_box_env complete, ci_box_env's one step (``probe``) with it;
* ci_slow runs ``before``, then ``work`` until it is stopped; stopped, it leaves a
  checkpoint, and resumed, it completes;
* gate_smoke parks at ``decide`` until it is answered, and keeps who answered;
* ``GET /api/workflows?status=...`` lists the runs in that status: its own, and
  someone else's (a Team Project, say) from the moment ``someone_else`` says;
* asked whether a run's box is up (docker, on the host), it says yes while the run is
  not over, and after that only for the workflows in ``boxes_linger``.

The knobs make one thing go wrong at a time. Its own clock (``clock``/``sleep``) lets a
check wait minutes in no time.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class FakeRun:
    run_id: str
    workflow: str
    inputs: dict
    notify: object
    status: str = "running"
    nodes: dict = field(default_factory=dict)
    caller: str | None = None
    resumed: bool = False


class _Answer:
    def __init__(self, body: object) -> None:
        self._body = json.dumps(body).encode()

    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class FakeLiveTemper:
    """The live API, one request at a time; ``calls`` keeps every request it was sent."""

    def __init__(self, *, key_name: str = "temper-ci", ends_as: dict | None = None,
                 gate_never_opens: bool = False, stuck: tuple[str, ...] = (),
                 no_checkpoint: bool = False, flaky_reads: int = 0,
                 caller_recorded: str | None = None,
                 someone_else: tuple[float, str] | None = None,
                 steps_end_as: dict | None = None, boxes_linger: tuple[str, ...] = (),
                 boxes_unknown: bool = False) -> None:
        self.key_name = key_name
        self.ends_as = dict(ends_as or {})        # workflow -> how it ends instead of completed
        self.gate_never_opens = gate_never_opens  # gate_smoke goes on running, never parks
        self.stuck = set(stuck)                   # workflows a cancel does not end
        self.no_checkpoint = no_checkpoint        # ci_slow leaves nothing to resume from
        self.flaky_reads = flaky_reads            # this many reads fail first, as a dropped line
        self.caller_recorded = caller_recorded    # the caller a decision names, if not the key's
        self.someone_else = someone_else          # (from when, workflow): a run the look did not start
        self.steps_end_as = dict(steps_end_as or {})  # workflow -> how its steps end, if not completed
        self.boxes_linger = set(boxes_linger)     # workflows whose box stays up after the run ends
        self.boxes_unknown = boxes_unknown        # docker cannot say whether a box is up
        self.boxes_asked: list[str] = []
        self.runs: dict[str, FakeRun] = {}
        self.calls: list[tuple[str, str, object, dict]] = []
        self.now = 0.0

    # -- its clock, for a Live under test ------------------------------------

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def install(self, monkeypatch) -> FakeLiveTemper:
        monkeypatch.setattr(urllib.request, "urlopen", self.urlopen)
        # docker, asked whether a run's box is up: no Docker here either. scripts/ is on
        # sys.path in every test that uses this fake.
        from temper_ci import live_checks
        monkeypatch.setattr(live_checks, "_box_up", self.box_up)
        return self

    def box_up(self, run_id: str) -> bool:
        self.boxes_asked.append(run_id)
        if self.boxes_unknown:
            raise RuntimeError("docker could not say (exit 1: Cannot connect to the Docker daemon)")
        run = self.runs.get(run_id)
        return run is not None and (run.run_id in self.going() or run.workflow in self.boxes_linger)

    # -- what it was asked -----------------------------------------------------

    def started(self) -> list[tuple[str, object]]:
        """(workflow, notify) of every run start, in order."""
        return [((body or {}).get("workflow"), (body or {}).get("notify"))
                for method, path, body, _ in self.calls if (method, path) == ("POST", "/api/runs")]

    def going(self) -> list[str]:
        return [r.run_id for r in self.runs.values()
                if r.status in ("pending", "queued", "running", "waiting", "cancelling")]

    # -- answering -------------------------------------------------------------

    def urlopen(self, req, timeout=None):  # noqa: ARG002 - same shape as urlopen
        if isinstance(req, str):
            method, url, body, headers = "GET", req, None, {}
        else:
            method, url = req.get_method(), req.full_url
            body = json.loads(req.data.decode()) if req.data else None
            headers = dict(req.header_items())
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        self.calls.append((method, path, body, headers))
        if method == "GET" and self.flaky_reads > 0:
            self.flaky_reads -= 1
            raise urllib.error.URLError("the line dropped")
        return _Answer(self._answer(method, path, body or {}, headers, url))

    def _refuse(self, url: str, code: int, detail: str):
        raise urllib.error.HTTPError(url, code, detail, {},  # type: ignore[arg-type]
                                     io.BytesIO(json.dumps({"detail": detail}).encode()))

    def _ended(self, run: FakeRun) -> str:
        return self.ends_as.get(run.workflow, "completed")

    def _answer(self, method: str, path: str, body: dict, headers: dict, url: str) -> object:
        parts = path.strip("/").split("/")
        if method == "GET" and path.startswith("/api/workflows?"):
            query = dict(p.split("=", 1) for p in path.split("?", 1)[1].split("&") if "=" in p)
            rows = [{"id": r.run_id, "workflow_name": r.workflow, "status": r.status}
                    for r in self.runs.values() if r.status == query.get("status")]
            if self.someone_else and self.now >= self.someone_else[0] and query.get("status") == "running":
                rows.append({"id": "c8626bf7-team-project", "workflow_name": self.someone_else[1],
                             "status": "running"})
            return {"runs": rows, "total": len(rows)}
        if (method, path) == ("POST", "/api/runs"):
            run_id = f"run-{len(self.runs) + 1:04d}-{body.get('workflow')}"
            run = FakeRun(run_id, str(body.get("workflow")), dict(body.get("inputs") or {}),
                          body.get("notify"))
            if run.workflow == "ci_slow":
                run.nodes = {"before": "completed", "work": "running", "after": "pending"}
            elif run.workflow == "ci_box_env":
                run.nodes = {"probe": "running"}
            elif run.workflow == "gate_smoke" and not self.gate_never_opens:
                run.status = "waiting"
            self.runs[run_id] = run
            return {"execution_id": run_id, "status": "queued"}
        if method == "GET" and parts[:2] == ["api", "workflows"] and len(parts) == 3:
            run = self.runs.get(parts[2]) or self._refuse(url, 404, "no such run")
            if run.status == "running" and run.workflow not in self.stuck and (
                    run.workflow in ("smoke_test", "ci_box_env") or run.resumed):
                run.status = self._ended(run)
                run.nodes = {name: self.steps_end_as.get(run.workflow, "completed") for name in run.nodes}
            return {"id": run.run_id, "status": run.status,
                    "nodes": [{"name": n, "status": s} for n, s in run.nodes.items()]}
        if parts[:2] != ["api", "runs"] or len(parts) < 4:
            return self._refuse(url, 404, f"nothing at {path}")
        run = self.runs.get(parts[2]) or self._refuse(url, 404, "no such run")
        what = parts[3]
        if (method, what) == ("GET", "gates"):
            open_ = run.workflow == "gate_smoke" and run.status == "waiting"
            return {"execution_id": run.run_id,
                    "gates": [{"node_name": "decide", "status": "waiting",
                               "event_id": f"ev-{run.run_id}"}] if open_ else []}
        if (method, what) == ("POST", "approve"):
            if run.status != "waiting" or parts[4:] != ["decide"]:
                return self._refuse(url, 409, "no wait open there")
            if body.get("event_id") not in (None, f"ev-{run.run_id}"):
                return self._refuse(url, 409, "that wait was replaced")
            has_key = any(k.lower() == "authorization" for k in headers)
            run.caller = self.caller_recorded or (self.key_name if has_key else None)
            run.status = self._ended(run)
            return {"ok": True}
        if (method, what) == ("GET", "decisions"):
            rows = [] if run.workflow != "gate_smoke" else [
                {"node_name": "decide", "status": "approved" if run.caller is not None else "waiting",
                 "caller": run.caller}]
            return {"execution_id": run.run_id, "decisions": rows}
        if (method, what) == ("POST", "cancel"):
            if run.status in ("pending", "queued", "running", "waiting", "cancelling"):
                if run.workflow in self.stuck:
                    run.status = "cancelling"
                else:
                    run.status = "cancelled"
                    run.nodes = {n: ("cancelled" if s == "running" else s) for n, s in run.nodes.items()}
            return {"execution_id": run.run_id, "status": run.status}
        if (method, what) == ("GET", "checkpoints"):
            rows = [] if (self.no_checkpoint or run.workflow != "ci_slow") else [
                {"sequence": 1, "node": "before"}]
            return {"execution_id": run.run_id, "checkpoints": rows, "total": len(rows)}
        if (method, what) == ("POST", "resume"):
            if self.no_checkpoint or run.workflow != "ci_slow":
                return self._refuse(url, 400, "No checkpoints found")
            run.resumed, run.status = True, "running"
            run.nodes["work"] = "running"
            return {"execution_id": run.run_id, "status": "resuming"}
        return self._refuse(url, 404, f"nothing at {path}")
