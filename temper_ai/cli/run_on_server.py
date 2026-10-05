"""``temper run``: start a workflow on the temper server, then follow it until it ends.

    temper run <workflow> [-i key=value ...] [--workspace PATH] [--detach] [-v] [--server URL]

A run starts only on the server, through the same ``POST /api/runs`` the dashboard, Slack, Telegram
and the ``temper_start_run`` tool use, so every run is recorded in the server's database and shows on
the dashboard. The server loads the workflow from its own configs (the ~/temper-ai master folder), not
from the folder this is typed in, and it fills the input defaults and makes the run-start checks.

Nothing runs in the terminal. ``temper run`` used to run the workflow right here, recording it in
whatever database ``TEMPER_DATABASE_URL`` named in that shell (or in sqlite ``data/dev.db``), and those
runs never reached the dashboard. A server that does not answer is a refusal, never a reason to run
here instead.

Following looks at the run's record every few seconds and prints a line as each stage starts or ends,
and one line for each wait on the owner, which is answered on the dashboard or in Slack/Telegram,
never here. It exits with the run's outcome; Ctrl+C stops following and the run carries on.

The server is ``--server``, else ``TEMPER_SERVER_URL``, else http://127.0.0.1:8420 (right both on the
host and inside the server container), with the key ``client_key()`` finds (TEMPER_API_KEY_FILE,
TEMPER_RUN_TOKEN or TEMPER_API_TOKEN, api/api_keys.py; inside the server container none is needed,
it is the caller "server"). Dashboard links use
``TEMPER_UI_URL``, else https://temper.wai2shine.com.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from typing import IO, Any

import httpx

DEFAULT_SERVER = "http://127.0.0.1:8420"
DEFAULT_UI = "https://temper.wai2shine.com"

# Exit codes. The first three are the run's own outcome, as configs/product/bin/server_run.py has them.
COMPLETED, FAILED, CANCELLED = 0, 1, 2
NOT_STARTED = 3    # nothing was started: the server isn't answering, refused the start, or a flag was refused
LOST = 4           # stopped following before the run ended; the run carries on (or may have started)
INTERRUPTED = 130  # Ctrl+C: stopped following; the run carries on
OUTCOMES = {"completed": COMPLETED, "failed": FAILED, "cancelled": CANCELLED}

POLL_MIN_S = 3.0        # the shortest pause between two looks at the run
POLL_MAX_S = 30.0       # a big run's record takes a while to build: look at most this rarely
TROUBLE_PAUSE_S = 6.0   # between tries while the server isn't answering
LOST_AFTER_S = 15 * 60  # a restart takes seconds; this long without an answer, stop following
START_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
LOOK_TIMEOUT = httpx.Timeout(60.0, connect=5.0)

# Run and stage statuses that are neither a start nor an end: not begun yet, or waiting at a gate
# (the wait gets its own line, and the stage starts when it is answered).
NOT_STARTED_YET = frozenset({"pending", "queued", "waiting"})
STILL_GOING = frozenset({"pending", "queued", "running", "waiting"})
END_WORDS = {"completed": "done"}

# The old in-terminal run's flags. Still parsed, so each one is refused with what to do instead.
REFUSED_FLAGS = {
    "provider": ("--provider", "runs start on the server, which has no per-run model override. "
                               "Set it in the agent or workflow config."),
    "model": ("--model", "runs start on the server, which has no per-run model override. "
                         "Set it in the agent or workflow config."),
    "config_dir": ("--config-dir", "the server loads configs from ~/temper-ai. To try a config that hasn't "
                                   "landed, save it under a new name through the Studio config API "
                                   "(docs/product-runs.md) or use a throwaway stack (scripts/temper_ci/stack.py)."),
    "no_db": ("--no-db", "every run is recorded on the server, so it shows on the dashboard."),
}


def refusals(args: Any) -> list[str]:
    """One line for each flag of the old in-terminal run that was given."""
    return [f"{flag} isn't accepted any more: {why}"
            for attr, (flag, why) in REFUSED_FLAGS.items() if getattr(args, attr, None)]


class Unreachable(Exception):
    """Nothing reached the server: no connection, or no usable address."""


class NoAnswer(Exception):
    """The request went out, but no answer came back (it timed out or the connection dropped)."""


class Refused(Exception):
    """The server answered with an error status."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class Server:
    """As much of the temper server's HTTP API as ``temper run`` uses."""

    def __init__(self, url: str, token: str | None = None) -> None:
        self.url = url
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            self._http = httpx.Client(base_url=url, headers=headers)
        except (httpx.InvalidURL, ValueError) as exc:
            raise Unreachable(str(exc)) from exc

    def close(self) -> None:
        self._http.close()

    def call(self, method: str, path: str, body: Any = None, timeout: httpx.Timeout = LOOK_TIMEOUT) -> Any:
        try:
            response = self._http.request(method, path, json=body, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError, httpx.UnsupportedProtocol,
                httpx.InvalidURL) as exc:
            raise Unreachable(str(exc) or type(exc).__name__) from exc
        except httpx.TransportError as exc:
            raise NoAnswer(str(exc) or type(exc).__name__) from exc
        if response.status_code >= 400:
            raise Refused(response.status_code, _detail(response))
        try:
            return response.json()
        except ValueError as exc:
            raise Refused(response.status_code, "its answer was not JSON") from exc


def run(workflow: str, inputs: dict, *, workspace: str | None = None, server: str | None = None,
        ui: str | None = None, detach: bool = False, verbose: int = 0, out: IO[str] | None = None,
        sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> int:
    """Start ``workflow`` on the server and, unless ``detach``, follow it. Returns the exit code."""
    out = out or sys.stdout
    err = sys.stderr
    url = (server or os.environ.get("TEMPER_SERVER_URL") or DEFAULT_SERVER).strip().rstrip("/")
    ui = (ui or os.environ.get("TEMPER_UI_URL") or DEFAULT_UI).strip().rstrip("/")
    body = {
        "workflow": workflow,
        "inputs": inputs,
        "workspace_path": os.path.abspath(os.path.expanduser(workspace)) if workspace else None,
    }
    not_answering = (f"The temper server at {url} isn't answering; runs start only on the server "
                     "so they show on the dashboard. Nothing was run.")
    try:
        from temper_ai.api.api_keys import client_key

        api = Server(url, client_key())
    except Unreachable:
        print(not_answering, file=err)
        return NOT_STARTED
    try:
        try:
            started = api.call("POST", "/api/runs", body, timeout=START_TIMEOUT)
        except Unreachable:
            print(not_answering, file=err)
            return NOT_STARTED
        except Refused as exc:
            print(f"The temper server refused to start {workflow} ({exc.status}): {exc.detail}", file=err)
            return NOT_STARTED
        except NoAnswer as exc:
            print(f"The temper server at {url} got the start but gave no answer ({_one_line(str(exc))}); "
                  f"the run may have started, look on the dashboard: {ui}/app", file=err)
            return LOST
        except KeyboardInterrupt:
            print(f"\nInterrupted before the server answered; the run may have started, look on the "
                  f"dashboard: {ui}/app", file=err)
            return INTERRUPTED
        execution_id = str(started.get("execution_id") or "") if isinstance(started, dict) else ""
        if not execution_id:
            print(f"The temper server answered the start without a run id; look on the dashboard: {ui}/app",
                  file=err)
            return LOST
        link = f"{ui}/app/workflow/{execution_id}"
        print(f"Started {workflow} on the temper server: run {execution_id}", file=out)
        print(f"  {link}", file=out)
        if detach:
            return 0
        print("Following it here; Ctrl+C stops following, the run keeps going.", file=out, flush=True)
        try:
            return _Follower(api, execution_id, link, out, verbose, sleep, clock).follow()
        except KeyboardInterrupt:
            print(f"\nStopped following. The run keeps going on the server; see or stop it at {link}", file=out)
            return INTERRUPTED
    finally:
        api.close()


class _Follower:
    """Looks at one run until it ends, printing what changed since the last look."""

    def __init__(self, api: Server, execution_id: str, link: str, out: IO[str], verbose: int,
                 sleep: Callable[[float], None], clock: Callable[[], float]) -> None:
        self._api = api
        self._id = execution_id
        self._link = link
        self._out = out
        self._verbose = verbose
        self._sleep = sleep
        self._clock = clock
        self._stages: dict[str, str] = {}  # stage path -> the status last printed for it
        self._waits: set[str] = set()       # the waits already printed
        self._status = ""
        self._trouble_since: float | None = None

    def follow(self) -> int:
        while True:
            began = self._clock()
            try:
                record = self._api.call("GET", f"/api/workflows/{self._id}")
            except (Unreachable, NoAnswer, Refused) as exc:
                if self._gave_up(exc):
                    return LOST
                self._sleep(TROUBLE_PAUSE_S)
                continue
            if self._trouble_since is not None:
                self._trouble_since = None
                self._say("  the server is answering again.")
            record = record if isinstance(record, dict) else {}
            for node in record.get("nodes") or []:
                self._show_stage(node, depth=0, parent="")
            self._show_waits()
            status = str(record.get("status") or "")
            if status in OUTCOMES:
                self._finish(record, status)
                return OUTCOMES[status]
            if status != self._status:
                self._status = status
                if status not in STILL_GOING:
                    self._say(f"  the run is {status or 'in an unknown state'}; still following.")
            took = self._clock() - began
            self._sleep(max(POLL_MIN_S, min(POLL_MAX_S, 2 * took)))

    def _gave_up(self, exc: Exception) -> bool:
        now = self._clock()
        if self._trouble_since is None:
            self._trouble_since = now
            self._say(f"  the server isn't answering about the run ({_one_line(str(exc), 160)}); "
                      "still trying. The run itself keeps going.")
            return False
        if now - self._trouble_since < LOST_AFTER_S:
            return False
        self._say(f"Stopped following: the server hasn't answered for {LOST_AFTER_S // 60} minutes. "
                  f"The run may still be going: {self._link}")
        return True

    def _show_stage(self, node: Any, depth: int, parent: str) -> None:
        if not isinstance(node, dict):
            return
        name = str(node.get("name") or node.get("id") or "?")
        path = f"{parent}/{name}" if parent else name
        status = str(node.get("status") or "")
        shown = self._stages.get(path)
        if status == "running" and shown != status:
            self._stages[path] = status
            self._line(depth, "started", name)
        if self._verbose:
            for child in node.get("child_nodes") or []:
                self._show_stage(child, depth + 1, path)
        if status and status not in NOT_STARTED_YET and status != "running" and shown != status:
            self._stages[path] = status
            self._line(depth, END_WORDS.get(status, status), name, _stage_detail(node, status))

    def _show_waits(self) -> None:
        try:
            answer = self._api.call("GET", f"/api/runs/{self._id}/gates")
        except (Unreachable, NoAnswer, Refused):
            return  # the record said how the run is; an open wait is still there at the next look
        for gate in (answer.get("gates") if isinstance(answer, dict) else None) or []:
            if not isinstance(gate, dict):
                continue
            key = str(gate.get("event_id") or f"{gate.get('node_name')}|{gate.get('path')}|{gate.get('round')}")
            if key in self._waits:
                continue
            self._waits.add(key)
            self._say(f"  waiting on you: {_question(gate)} Answer on the dashboard or in Slack/Telegram.")

    def _finish(self, record: dict, status: str) -> None:
        if self._verbose and status == "completed":
            output = record.get("workflow_output") or record.get("output_data")
            if output:
                text = output if isinstance(output, str) else json.dumps(output, indent=2, default=str)
                self._say("Output:")
                self._say(text if len(text) <= 2000 else text[:2000] + "…")
        took = _duration(record.get("duration_seconds"))
        when = (" in " if status == "completed" else " after ") + took if took else ""
        spent = f"${_number(record.get('total_cost_usd')):.2f}"
        error = _one_line(str(record.get("error_message") or ""), 300) if status == "failed" else ""
        if error:
            self._say(f"Run failed{when}, {spent}: {error.rstrip('.')}. {self._link}")
        else:
            self._say(f"Run {status}{when}, {spent}: {self._link}")

    def _line(self, depth: int, word: str, name: str, detail: str = "") -> None:
        self._say(f"{'  ' * (depth + 1)}{word:<8} {name}{detail}")

    def _say(self, text: str) -> None:
        print(text, file=self._out, flush=True)


def _stage_detail(node: dict, status: str) -> str:
    if status == "completed":
        took = _duration(node.get("duration_seconds"))
        return f" ({took})" if took else ""
    error = node.get("error_message")
    if status == "failed" and error:
        return f": {_one_line(error if isinstance(error, str) else json.dumps(error, default=str), 200)}"
    return ""


def _question(gate: dict) -> str:
    """What a wait asks, in one line: its first question (and how many more), or its step's name."""
    texts = []
    for item in gate.get("questions") or []:
        text = item.get("question") or item.get("header") if isinstance(item, dict) else item
        text = _one_line(str(text or ""), 240)
        if text:
            texts.append(text)
    if not texts:
        return f"{gate.get('node_name') or 'a step'} needs your approval."
    first = texts[0] if texts[0][-1] in ".?!:…" else texts[0] + "."
    return first + (f" (and {len(texts) - 1} more)" if len(texts) > 1 else "")


def _detail(response: httpx.Response) -> str:
    """An error answer's ``detail``, in one line (FastAPI's 422 gives a list of problems)."""
    try:
        body = response.json()
    except ValueError:
        return _one_line(response.text) or response.reason_phrase
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, list):
        detail = "; ".join(_problem(item) for item in detail)
    elif not isinstance(detail, str):
        detail = json.dumps(detail, default=str)
    return _one_line(detail)


def _problem(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)
    where = ".".join(str(part) for part in item.get("loc") or [] if part != "body")
    message = str(item.get("msg") or item)
    return f"{where}: {message}" if where else message


def _one_line(text: Any, limit: int = 600) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _duration(seconds: Any) -> str:
    try:
        total = round(float(seconds))
    except (TypeError, ValueError):
        return ""
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m{total % 60:02d}s"
    return f"{total // 3600}h{total % 3600 // 60:02d}m"


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
