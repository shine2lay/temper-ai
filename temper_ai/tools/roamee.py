"""Three tools that let an answer about roamee see past its code.

The ``roamee_answer`` workflow already reads a fresh read-only copy of the
repository. These add the three other places a question about roamee can
only be answered from, and each is read-only by construction:

* :class:`RoameeStack` — the three staging containers: up or down, healthy or
  not, which build, since when, how many restarts, the tail of a log.
* :class:`RoameeData`  — staging's database: its tables, one table's shape, or
  one plain read.
* :class:`RoameeWork`  — roamee's open pull requests, recent commits, failing
  checks (GitHub) and open issues (Linear's ROA team).

How the first two reach anything at all: a run happens inside its own
container, with no docker socket and no route to roamee's network, so they
ask ``roamee-reader`` — a small service on the host, over a unix socket in a
folder temper's containers have mounted read-only (scripts/roamee_reader.py,
docs/roamee.md). The fence lives in that service: the three container names,
an allowlist of fields that leaves out the environment, the command line and
the mounts, a login that may only read, a row cap, a statement timeout, and
every answer blanked of anything shaped like a key.

None of the three has a parameter that takes a shell command, and none can
write: there is no endpoint on the other side that would.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from http.client import HTTPConnection
from typing import Any
from urllib.parse import quote

from temper_ai.shared.secrets import blank_secrets
from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

REPO = "shine2lay/roamee"
BRANCH = "staging"
LINEAR_TEAM = "ROA"
CONTAINERS = ("roamee-staging-frontend-1", "roamee-staging-backend-1", "roamee-staging-postgres-1")

SOCKET_ENV = "ROAMEE_READER_SOCKET"
DEFAULT_SOCKET = "/app/roamee-reader/reader.sock"
READER_TIMEOUT_S = 30.0

MAX_ITEMS = 30
DEFAULT_ITEMS = 10
TEXT_CHARS = 300


class _Refused(Exception):
    """Something the tool will not do, or could not reach. The agent is told why."""


# -- the one way to the host -------------------------------------------------


def socket_path() -> str:
    return os.environ.get(SOCKET_ENV) or DEFAULT_SOCKET


class _UnixConnection(HTTPConnection):
    """HTTP over a unix socket: no port, no network, no name to resolve."""

    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("roamee-reader", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def ask_reader(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """One question to roamee-reader. Raises :class:`_Refused` with its words."""
    where = socket_path()
    connection = _UnixConnection(where, READER_TIMEOUT_S)
    try:
        payload = json.dumps(body or {}).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
    except FileNotFoundError as exc:
        raise _Refused(
            "I can't reach roamee-reader, the service on the box that looks at staging "
            f"({where} isn't there), so I can't see the containers or the database right now."
        ) from exc
    except OSError as exc:
        raise _Refused(f"roamee-reader didn't answer ({type(exc).__name__}), "
                       "so I can't see staging right now.") from exc
    finally:
        connection.close()
    try:
        answer = json.loads(raw or b"{}")
    except ValueError as exc:
        raise _Refused("roamee-reader's answer could not be read.") from exc
    if status != 200 or not isinstance(answer, dict):
        said = answer.get("error") if isinstance(answer, dict) else ""
        raise _Refused(str(said or f"roamee-reader said {status}."))
    return answer


def _clip(text: Any, limit: int = TEXT_CHARS) -> str:
    out = blank_secrets(text).replace("\r", "").strip()
    one_line = " ".join(out.split("\n")[:1])
    return one_line if len(one_line) <= limit else one_line[:limit] + "…"


def _count(value: Any, fallback: int = DEFAULT_ITEMS) -> int:
    try:
        return max(1, min(int(value), MAX_ITEMS))
    except (TypeError, ValueError):
        return fallback


def _table(columns: list[str], rows: list[list[Any]]) -> str:
    """A small fixed-width table, the way a person would write one."""
    if not columns:
        return "(nothing)"
    widths = [len(c) for c in columns]
    for row in rows:
        for i, cell in enumerate(row[:len(columns)]):
            widths[i] = max(widths[i], min(len(str(cell)), 60))
    line = "  ".join(c.ljust(widths[i])[:60] for i, c in enumerate(columns))
    out = [line, "  ".join("-" * widths[i] for i in range(len(columns)))]
    for row in rows:
        out.append("  ".join(str(row[i] if i < len(row) else "").ljust(widths[i])[:60]
                             for i in range(len(columns))).rstrip())
    return "\n".join(out)


# -- the staging stack -------------------------------------------------------


class RoameeStack(BaseTool):
    """Whether roamee's staging is up, what it's running, and what its logs say."""

    name = "RoameeStack"
    description = (
        "Look at roamee's staging stack on the box: the three containers "
        f"({', '.join(CONTAINERS)}). what='status' says, for each one, whether it is running, "
        "whether its health check passes, which build (commit) it is running, when it started, "
        "how long it has been up and how many times it has restarted. what='logs' gives the tail "
        "of one container's log (name it in container=, up to 200 lines). Read-only: it cannot "
        "start, stop, change or run anything, and it looks at no other project's containers. "
        "Environment variables, command lines and mounts are never returned."
    )
    parameters = {
        "type": "object",
        "properties": {
            "what": {"type": "string", "enum": ["status", "logs"],
                     "description": "'status' for all three containers, 'logs' for one container's log tail."},
            "container": {"type": "string", "enum": list(CONTAINERS),
                          "description": "Which container's log to read. Only for what='logs'."},
            "lines": {"type": "integer", "description": "Log lines from the end, 1-200. Default 40."},
        },
        "required": ["what"],
    }
    modifies_state = False
    local_paths = False

    def execute(self, **params: Any) -> ToolResult:
        what = str(params.get("what") or "").strip().lower()
        try:
            if what == "status":
                return ToolResult(success=True, result=_stack_text(ask_reader("GET", "/stack")))
            if what == "logs":
                container = str(params.get("container") or "").strip()
                if not container:
                    raise _Refused("name the container whose log you want: " + ", ".join(CONTAINERS))
                lines = str(params.get("lines") or "").strip()
                query = f"/logs?container={quote(container, safe='')}" + (f"&lines={int(lines)}" if lines.isdigit() else "")
                found = ask_reader("GET", query)
                return ToolResult(success=True, result=(
                    f"{found.get('container')}, last {found.get('lines')} lines, "
                    f"looked at {found.get('looked_at')} ({found.get('source')}):\n{found.get('log') or '(empty)'}"))
            raise _Refused(f"'{what}' is not something I can look at; I know 'status' and 'logs'")
        except _Refused as exc:
            return ToolResult(success=False, result="", error=str(exc))


def _stack_text(found: dict[str, Any]) -> str:
    rows = []
    for one in found.get("containers") or []:
        if one.get("state") == "not there":
            rows.append([one.get("container"), "NOT THERE", "-", "-", "-", "-"])
            continue
        rows.append([
            one.get("container"),
            str(one.get("state") or ""),
            str(one.get("health") or ""),
            str(one.get("build") or "(no build label)"),
            str(one.get("up_for") or (f"exit {one.get('exit_code')}" if "exit_code" in one else "")),
            str(one.get("restarts", "")),
        ])
    table = _table(["container", "state", "health", "build", "up for", "restarts"], rows)
    head = "roamee staging is up" if found.get("up") else "roamee staging is NOT fully up"
    return (f"{head}. Looked at {found.get('looked_at')} ({found.get('source')}).\n{table}")


# -- staging's database ------------------------------------------------------


class RoameeData(BaseTool):
    """Counts and shapes out of roamee's staging database, read-only."""

    name = "RoameeData"
    description = (
        "Read roamee's staging database (never change it). what='tables' lists every table with a "
        "row estimate and its size; what='columns' with table= gives one table's columns and types; "
        "what='read' with sql= runs ONE plain SELECT and returns at most 50 rows — use it for counts "
        "and shapes, e.g. \"select count(*) from trips\" or \"select status, count(*) from trips "
        "group by 1 order by 2 desc\". It connects as a login that may only read, under a 5-second "
        "limit, so anything that writes, or that takes too long, is refused and nothing changes. "
        "Columns whose name sounds like a secret come back blanked."
    )
    parameters = {
        "type": "object",
        "properties": {
            "what": {"type": "string", "enum": ["tables", "columns", "read"],
                     "description": "'tables', 'columns' (with table=), or 'read' (with sql=)."},
            "table": {"type": "string", "description": "Table name, for what='columns'."},
            "sql": {"type": "string", "description": "One SELECT, for what='read'. No writes, one statement."},
        },
        "required": ["what"],
    }
    modifies_state = False
    local_paths = False

    def execute(self, **params: Any) -> ToolResult:
        what = str(params.get("what") or "").strip().lower()
        try:
            if what == "tables":
                found = ask_reader("POST", "/sql", {"action": "tables"})
                return ToolResult(success=True, result=_data_text(found, "tables in staging's database"))
            if what == "columns":
                table = str(params.get("table") or "").strip()
                if not table:
                    raise _Refused("name the table whose columns you want, e.g. table='trips'")
                found = ask_reader("POST", "/sql", {"action": "columns", "table": table})
                return ToolResult(success=True, result=_data_text(found, f"the columns of {table}"))
            if what == "read":
                sql = str(params.get("sql") or "").strip()
                if not sql:
                    raise _Refused("give me the SELECT to run, e.g. sql='select count(*) from trips'")
                found = ask_reader("POST", "/sql", {"action": "read", "sql": sql})
                return ToolResult(success=True, result=_data_text(found, sql))
            raise _Refused(f"'{what}' is not something I can do with the database; "
                           "I know 'tables', 'columns' and 'read'")
        except _Refused as exc:
            return ToolResult(success=False, result="", error=str(exc))


def _data_text(found: dict[str, Any], about: str) -> str:
    table = _table([str(c) for c in (found.get("columns") or [])],
                   [list(r) for r in (found.get("rows") or [])])
    more = "\n(there were more rows; this is where I stopped)" if found.get("truncated") else ""
    hidden = found.get("hidden_columns") or []
    blanked = f"\n(blanked, because the column name sounds like a secret: {', '.join(hidden)})" if hidden else ""
    return (f"{about} — {found.get('row_count', 0)} rows, looked at {found.get('looked_at')} "
            f"({found.get('source')}).\n{table}{more}{blanked}")


# -- GitHub and Linear -------------------------------------------------------


class RoameeWork(BaseTool):
    """What is open and what landed on roamee: GitHub and Linear, read-only."""

    name = "RoameeWork"
    description = (
        f"What is open and what has landed on roamee ({REPO} on GitHub, team {LINEAR_TEAM} in Linear). "
        "what='pulls' lists the open pull requests; what='commits' the most recent commits on the "
        f"{BRANCH} branch; what='checks' how the checks on that branch's latest commit went (failing "
        "ones first); what='issues' the open Linear issues. Read-only: it opens, closes, comments on "
        "and changes nothing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "what": {"type": "string", "enum": ["pulls", "commits", "checks", "issues"],
                     "description": "Which list you want."},
            "limit": {"type": "integer", "description": f"How many, 1-{MAX_ITEMS}. Default {DEFAULT_ITEMS}."},
            "branch": {"type": "string", "description": f"Branch for 'commits' and 'checks'. Default {BRANCH}."},
        },
        "required": ["what"],
    }
    modifies_state = False
    local_paths = False

    def execute(self, **params: Any) -> ToolResult:
        what = str(params.get("what") or "").strip().lower()
        limit = _count(params.get("limit"))
        branch = str(params.get("branch") or BRANCH).strip() or BRANCH
        try:
            if what == "pulls":
                return ToolResult(success=True, result=_pulls(limit))
            if what == "commits":
                return ToolResult(success=True, result=_commits(branch, limit))
            if what == "checks":
                return ToolResult(success=True, result=_checks(branch))
            if what == "issues":
                return ToolResult(success=True, result=_issues(limit))
            raise _Refused(f"'{what}' is not a list I keep; I know 'pulls', 'commits', 'checks' and 'issues'")
        except _Refused as exc:
            return ToolResult(success=False, result="", error=str(exc))


def _github(path: str, **params: Any) -> Any:
    from temper_ai.integrations.github.app import GitHubAppError, check_repo, get_app

    try:
        repo = check_repo(REPO)
        response = get_app().request("GET", repo, path, params=params or None)
    except GitHubAppError as exc:
        raise _Refused(f"I couldn't ask GitHub about {REPO}: {blank_secrets(exc)}") from exc
    except Exception as exc:  # noqa: BLE001 - transport or HTTP: the agent is told plainly
        raise _Refused(f"GitHub didn't answer about {REPO}: {type(exc).__name__}") from exc
    if not response.is_success:
        raise _Refused(f"GitHub answered {response.status_code} for {REPO}{path}")
    return response.json()


def _source(what: str) -> str:
    from datetime import UTC, datetime

    return f"(GitHub {REPO}, {what}, looked at {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%SZ')})"


def _said(found: dict[str, Any], what: str) -> str:
    """Where an answer from roamee-reader came from, in its own words."""
    return f"({found.get('source') or what}, looked at {found.get('looked_at') or 'just now'})"


def _pulls(limit: int) -> str:
    found = _github("/pulls", state="open", sort="updated", direction="desc", per_page=limit)
    rows = [[f"#{p.get('number')}", _clip(p.get("title"), 60),
             str(((p.get("user") or {}).get("login")) or ""),
             "draft" if p.get("draft") else "ready",
             str(((p.get("head") or {}).get("ref")) or ""),
             str(p.get("updated_at") or "")[:10]]
            for p in (found if isinstance(found, list) else [])]
    if not rows:
        return f"No open pull requests on {REPO}. {_source('open pull requests')}"
    return (f"{len(rows)} open pull requests on {REPO} {_source('open pull requests')}\n"
            + _table(["pr", "title", "by", "state", "branch", "updated"], rows))


def _commits(branch: str, limit: int) -> str:
    found = _github("/commits", sha=branch, per_page=limit)
    rows = [[str(c.get("sha") or "")[:8],
             _clip(((c.get("commit") or {}).get("message")), 70),
             str((((c.get("commit") or {}).get("author")) or {}).get("name") or ""),
             str((((c.get("commit") or {}).get("author")) or {}).get("date") or "")[:10]]
            for c in (found if isinstance(found, list) else [])]
    if not rows:
        return f"No commits found on {REPO} {branch}. {_source(f'{branch} commits')}"
    return (f"The last {len(rows)} commits on {REPO} {branch} {_source(f'{branch} commits')}\n"
            + _table(["commit", "message", "by", "when"], rows))


def _checks(branch: str) -> str:
    """How the checks went, read through roamee-reader.

    Not through temper's own GitHub token: that one carries contents, issues
    and pull requests only (integrations/github/app.py PERMISSIONS), so GitHub
    answers 403 for check runs. The box's own `gh` can read them, and the
    reader is where a run may use it — for this one repository and a GET.
    """
    found = ask_reader("GET", f"/checks?branch={quote(branch, safe='')}")
    runs = found.get("checks") or []
    total, failed = int(found.get("total") or 0), int(found.get("failed") or 0)
    sha = str(found.get("commit") or "")
    rows = [[_clip(r.get("check"), 40), str(r.get("status") or ""), str(r.get("result") or "running")]
            for r in runs]
    where = f"{REPO} {found.get('branch') or branch}" + (f" at {sha}" if sha else "")
    if not total:
        return f"No checks have run on {where}. {_said(found, 'the checks')}"
    head_line = (f"{failed} of {total} checks failed on {where}"
                 if failed else f"All {total} checks passed on {where}")
    return f"{head_line} {_said(found, 'the checks')}\n" + _table(["check", "status", "result"], rows)


_ISSUES = """
query($team: String!, $first: Int!) {
  issues(filter: {team: {key: {eq: $team}}}, first: $first, orderBy: updatedAt) {
    nodes {
      identifier title updatedAt priorityLabel
      state { name type }
      assignee { name }
    }
  }
}
"""


def _issues(limit: int) -> str:
    from datetime import UTC, datetime

    from temper_ai.triggers import linear

    try:
        found = linear.graphql(_ISSUES, {"team": LINEAR_TEAM, "first": 50})
    except Exception as exc:  # noqa: BLE001 - no app, transport or GraphQL: say so plainly
        raise _Refused(f"I couldn't ask Linear about team {LINEAR_TEAM}: {type(exc).__name__}") from exc
    nodes = ((found or {}).get("issues") or {}).get("nodes") or []
    open_ones = [n for n in nodes
                 if str(((n.get("state") or {}).get("type")) or "") not in ("completed", "canceled")]
    rows = [[str(n.get("identifier") or ""), _clip(n.get("title"), 60),
             str(((n.get("state") or {}).get("name")) or ""),
             str(((n.get("assignee") or {}).get("name")) or "nobody"),
             str(n.get("priorityLabel") or ""),
             str(n.get("updatedAt") or "")[:10]]
            for n in open_ones[:limit]]
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    where = f"(Linear team {LINEAR_TEAM}, open issues, looked at {when})"
    if not rows:
        return f"No open issues in Linear team {LINEAR_TEAM}. {where}"
    return (f"{len(open_ones)} open issues in Linear team {LINEAR_TEAM}, the {len(rows)} most "
            f"recently touched {where}\n"
            + _table(["issue", "title", "state", "assignee", "priority", "updated"], rows))
