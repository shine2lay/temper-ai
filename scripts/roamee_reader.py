#!/usr/bin/env python3
"""roamee-reader — the one door between a temper run and roamee's staging stack.

A run happens inside its own container: no docker socket, and no route to
roamee's network. So a run can see neither the three staging containers nor
their database, however much it would like to. This little service is what it
asks instead.

It runs on the host, as the owner, and listens on a unix socket in
``~/.temper/roamee-reader/``. That folder is mounted **read-only** into
temper's worker, and every run container inherits the mount (the spawner
passes on a mount whose source and target differ), so a run can connect to
the socket and can neither move nor delete it. Nothing is published on any
port, and the folder is outside every repository.

What it will answer, and nothing else:

* ``GET  /stack``                     the three staging containers: up or down,
                                      healthy or not, which build, since when,
                                      how many restarts
* ``GET  /logs?container=&lines=``    the tail of one of those three containers'
                                      log, secrets blanked out
* ``POST /sql``                       ``tables``, ``columns`` or one plain read
                                      of staging's database
* ``GET  /health``                    that this service is alive

Everything else is a refusal. The fence lives here, not in the caller, so it
holds even for something that reaches the socket another way:

* the three container names are written down below; any other name is refused,
  so no other project's containers can be looked at through this door;
* a container's answer is built from an allowlist of fields. The environment,
  the command line and the mounts are never read out of ``docker inspect``, so
  a key cannot leave this way;
* logs and every message go through :func:`scrub`, which blanks passwords,
  tokens, keys and connection strings;
* the database is reached as a login that may only read (the first lock), and
  every statement must still be a single plain read, is wrapped in a row cap
  and runs under a statement timeout in a read-only session (the second).
  A column whose name sounds like a secret comes back blanked.

It reads with ``psql``, which the box has, rather than a database library:
this service then needs nothing installed for itself, and the query travels
as one argument of a fixed argument list - there is no shell anywhere in it.

Install (once, on the box):

    cp scripts/systemd/roamee-reader.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now roamee-reader

The read-only login it uses is ``temper_ro`` in staging's database; its
password lives with temper's other keys, in ``~/temper-ai/.env``
(``ROAMEE_READER_DB_PASSWORD``). Nothing else is read out of that file.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import socketserver
import subprocess  # noqa: S404 - intentional: this service shells out to `docker`, and to nothing else
import sys
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("roamee_reader")

# -- what may be looked at ---------------------------------------------------

PROJECT = "roamee-staging"
FRONTEND = "roamee-staging-frontend-1"
BACKEND = "roamee-staging-backend-1"
POSTGRES = "roamee-staging-postgres-1"
CONTAINERS = (FRONTEND, BACKEND, POSTGRES)

DEFAULT_DB = "trip_planner_staging"
DEFAULT_DB_USER = "temper_ro"
REPO = "shine2lay/roamee"
BRANCH = "staging"
# A branch name and nothing else: no spaces, no "..", nothing that could turn
# the path this file builds into another call.
BRANCH_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}")
BAD_CONCLUSIONS = ("failure", "timed_out", "cancelled", "action_required", "stale")
ENV_FILE = Path.home() / "temper-ai" / ".env"
SOCKET_PATH = Path.home() / ".temper" / "roamee-reader" / "reader.sock"

# -- how much may come back --------------------------------------------------

LOG_LINES_DEFAULT = 40
LOG_LINES_MAX = 200
LOG_CHARS = 8_000
ROW_CAP = 50           # rows of a plain read
LIST_CAP = 300         # rows of the tables/columns lists, which we build ourselves
CELL_CHARS = 300
STATEMENT_TIMEOUT_MS = 5_000
CONNECT_TIMEOUT_S = 5
DOCKER_TIMEOUT_S = 15
GH_TIMEOUT_S = 20
CHECKS_CAP = 30
# gh is the owner's, installed in ~/.local/bin, which a user unit's PATH does
# not have; this service is on the host for exactly these three programs.
GH = str(Path.home() / ".local" / "bin" / "gh")

VERSION = "1"


# -- secrets never leave -----------------------------------------------------

_DSN = re.compile(r"(?i)\b([a-z+]+://[^\s:@/]+):([^\s@/]+)@")
_ASSIGNED = re.compile(
    r"(?i)\b([a-z0-9_.\-]*(?:password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key"
    # the closing quote of a JSON key: {"secret": "..."} counts too
    r"|private[_-]?key|credential|session|cookie|auth[a-z_]*))\b([\"']?\s*[=:]\s*)"
    # not `authorization: Bearer <token>`: _BEARER has that one, and this rule
    # would otherwise blank the word Bearer and leave the token standing.
    r"(?!(?:bearer|basic)\b)(\"[^\"]*\"|'[^']*'|\S+)"
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}")
_KNOWN_SHAPES = re.compile(
    r"\b("
    r"sk-[A-Za-z0-9._\-]{12,}"          # OpenAI and friends
    r"|gh[pousr]_[A-Za-z0-9]{20,}"      # GitHub
    r"|xox[abposr]-[A-Za-z0-9-]{10,}"   # Slack
    r"|lin_(?:api|oauth)_[A-Za-z0-9]{10,}"  # Linear
    r"|eyJ[A-Za-z0-9._\-]{20,}"         # a JWT
    r"|AIza[A-Za-z0-9._\-]{20,}"        # Google
    r")"
)
BLANK = "[hidden]"

# A column whose name sounds like a secret comes back blanked, whatever it holds.
_SECRET_COLUMN = re.compile(
    r"(?i)(password|passwd|secret|token|api_?key|apikey|private_?key|credential|salt"
    r"|hash|session_id|cookie|authorization|access_key|refresh_token)"
)


def scrub(text: Any) -> str:
    """Blank out anything that looks like a password, a key or a token."""
    out = str(text or "")
    out = _DSN.sub(r"\1:" + BLANK + "@", out)
    out = _ASSIGNED.sub(lambda m: f"{m.group(1)}{m.group(2)}{BLANK}", out)
    out = _BEARER.sub(lambda m: f"{m.group(1)} {BLANK}", out)
    out = _KNOWN_SHAPES.sub(BLANK, out)
    return out


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n[... {len(text) - limit} more characters]"


def _from_csv(out: str) -> tuple[list[str], list[list[str]]]:
    """psql's --csv answer: the header row, then the rows."""
    rows = list(csv.reader(io.StringIO(out or "")))
    if not rows:
        return [], []
    return [str(c) for c in rows[0]], [list(r) for r in rows[1:]]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")


def _since(stamp: str) -> str:
    """'2 days, 3 hours' from docker's own timestamp; '' when it can't be read."""
    try:
        started = datetime.fromisoformat(str(stamp).replace("Z", "+00:00").split(".")[0] + "+00:00")
    except (TypeError, ValueError):
        return ""
    seconds = int((datetime.now(UTC) - started).total_seconds())
    if seconds < 0:
        return ""
    days, rest = divmod(seconds, 86_400)
    hours, rest = divmod(rest, 3_600)
    minutes = rest // 60
    parts = [f"{days} days" if days != 1 else "1 day"] if days else []
    parts += [f"{hours} hours" if hours != 1 else "1 hour"] if hours else []
    if not days:
        parts += [f"{minutes} minutes" if minutes != 1 else "1 minute"]
    return ", ".join(parts) or "under a minute"


class Refused(Exception):
    """Something this service will not do. The caller is told why, plainly."""


# -- the service -------------------------------------------------------------


def _docker(args: list[str]) -> tuple[int, str, str]:
    done = subprocess.run(  # noqa: S603 - a fixed program with arguments this file builds
        ["docker", *args], capture_output=True, text=True, timeout=DOCKER_TIMEOUT_S, check=False)
    return done.returncode, done.stdout, done.stderr


def _env_value(name: str, default: str = "") -> str:
    """One value out of temper's .env, without pulling the rest into this process."""
    if os.environ.get(name):
        return str(os.environ[name])
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return default


def _gh(args: list[str]) -> tuple[int, str, str]:
    """One GitHub read through the box's own `gh`. No shell, and no way to
    write: every call this file builds is a plain GET."""
    done = subprocess.run(  # noqa: S603 - a fixed program with arguments this file builds
        [GH, *args], capture_output=True, text=True, timeout=GH_TIMEOUT_S, check=False)
    return done.returncode, done.stdout, done.stderr


def _psql(args: list[str], env: dict[str, str], timeout: float) -> tuple[int, str, str]:
    """Run psql with exactly these arguments. No shell, ever."""
    done = subprocess.run(  # noqa: S603 - a fixed program with arguments this file builds
        ["psql", *args], capture_output=True, text=True, timeout=timeout, check=False,
        env={**os.environ, **env})
    return done.returncode, done.stdout, done.stderr


class Reader:
    """Answers the four questions, and refuses everything else.

    ``docker`` and ``connect`` are injected so the tests can drive the whole
    thing with fakes and never touch the live stack.
    """

    def __init__(self, docker: Any = _docker, psql: Any = _psql, gh: Any = _gh) -> None:
        self._docker = docker
        self._psql = psql
        self._gh = gh

    # -- the stack ----------------------------------------------------------

    def _inspect(self, container: str) -> dict[str, Any] | None:
        code, out, err = self._docker(["inspect", container])
        if code != 0:
            if "No such object" in err or "no such object" in err.lower():
                return None
            raise Refused(f"docker could not look at {container}: {scrub(err.strip())[:200]}")
        try:
            found = json.loads(out)
        except ValueError as exc:
            raise Refused(f"docker's answer about {container} could not be read: {exc}") from exc
        return found[0] if found else None

    @staticmethod
    def _fields(container: str, raw: dict[str, Any]) -> dict[str, Any]:
        """The allowlist: what a container may say about itself.

        Everything is picked out by name. ``Env``, ``Cmd``, ``Entrypoint`` and
        ``Mounts`` are never among them, so a key cannot leave through here.
        """
        state = raw.get("State") or {}
        config = raw.get("Config") or {}
        labels = config.get("Labels") or {}
        health = (state.get("Health") or {}).get("Status")
        ports = sorted({
            f"{bind.get('HostIp') or '0.0.0.0'}:{bind.get('HostPort')} -> {inside}"
            for inside, binds in ((raw.get("NetworkSettings") or {}).get("Ports") or {}).items()
            for bind in (binds or [])
        })
        entry = {
            "container": container,
            "service": labels.get("com.docker.compose.service") or "",
            "project": labels.get("com.docker.compose.project") or "",
            "state": state.get("Status") or "unknown",
            "health": health or "no health check",
            "image": config.get("Image") or "",
            "image_id": str(raw.get("Image") or "")[:19],
            "build": labels.get("standee.commit") or "",
            "started_at": state.get("StartedAt") or "",
            "up_for": _since(state.get("StartedAt") or "") if state.get("Running") else "",
            "restarts": raw.get("RestartCount", 0),
            "ports": ports,
        }
        if not state.get("Running"):
            entry["exit_code"] = state.get("ExitCode")
            entry["finished_at"] = state.get("FinishedAt") or ""
        return entry

    def stack(self) -> dict[str, Any]:
        containers = []
        for name in CONTAINERS:
            raw = self._inspect(name)
            if raw is None:
                containers.append({"container": name, "state": "not there",
                                   "health": "", "note": "no container by that name is on the box"})
            else:
                containers.append(self._fields(name, raw))
        running = [c for c in containers if c.get("state") == "running"]
        return {
            "looked_at": _now(),
            "source": f"docker inspect on the box, compose project {PROJECT}",
            "up": len(running) == len(CONTAINERS),
            "containers": containers,
        }

    def logs(self, container: str, lines: int = LOG_LINES_DEFAULT) -> dict[str, Any]:
        if container not in CONTAINERS:
            raise Refused(f"{container!r} is not one of roamee's staging containers "
                          f"({', '.join(CONTAINERS)}); I only look at those three")
        try:
            want = max(1, min(int(lines), LOG_LINES_MAX))
        except (TypeError, ValueError):
            want = LOG_LINES_DEFAULT
        code, out, err = self._docker(["logs", "--tail", str(want), "--timestamps", container])
        if code != 0:
            raise Refused(f"docker could not read {container}'s log: {scrub(err.strip())[:200]}")
        text = _clip(scrub((out or "") + (err or "")), LOG_CHARS)
        return {"looked_at": _now(), "source": f"docker logs --tail {want} {container}",
                "container": container, "lines": want, "log": text}

    # -- the checks ---------------------------------------------------------

    def checks(self, branch: str = BRANCH) -> dict[str, Any]:
        """How the checks went on roamee's branch, read through `gh`.

        Temper's own GitHub token is deliberately narrow (contents, issues and
        pull requests), so it cannot see check runs at all; the box's `gh` can.
        The call is built here: one repository, one branch whose name has to
        look like a branch name, and GET.
        """
        name = str(branch or BRANCH).strip() or BRANCH
        if not BRANCH_OK.fullmatch(name) or ".." in name:
            raise Refused(f"{name!r} does not look like a branch name, so I won't ask GitHub about it")
        try:
            code, out, err = self._gh(["api", "--method", "GET",
                                       f"repos/{REPO}/commits/{name}/check-runs",
                                       "-F", "per_page=100"])
        except FileNotFoundError as exc:
            raise Refused("this box has no gh, so I can't see how the checks went") from exc
        except subprocess.TimeoutExpired as exc:
            raise Refused("GitHub took too long to say how the checks went") from exc
        if code != 0:
            text = scrub(err.strip() or out.strip())
            if "404" in text or "Not Found" in text:
                raise Refused(f"GitHub has no branch {name} on {REPO}")
            raise Refused(f"GitHub would not say how the checks went: {text[:200]}")
        try:
            found = json.loads(out or "{}")
        except ValueError as exc:
            raise Refused(f"GitHub's answer about the checks could not be read: {exc}") from exc
        runs = found.get("check_runs") or []
        bad = [r for r in runs if str(r.get("conclusion") or "") in BAD_CONCLUSIONS]
        rest = [r for r in runs if r not in bad]
        rows = [{"check": _clip(scrub(str(r.get("name") or "")), 60),
                 "status": str(r.get("status") or ""),
                 "result": str(r.get("conclusion") or "running"),
                 "started_at": str(r.get("started_at") or "")}
                for r in (bad + rest)[:CHECKS_CAP]]
        sha = ""
        for run in runs:
            sha = str(run.get("head_sha") or "")
            if sha:
                break
        return {"looked_at": _now(), "source": f"GitHub check runs for {REPO} {name}",
                "repo": REPO, "branch": name, "commit": sha[:8], "total": len(runs),
                "failed": len(bad), "checks": rows}

    # -- the database -------------------------------------------------------

    def _db_host(self) -> tuple[str, int]:
        """Where staging's postgres is, right now: its own address on the box."""
        raw = self._inspect(POSTGRES)
        if raw is None:
            raise Refused(f"{POSTGRES} is not on the box, so there is no database to read")
        if not ((raw.get("State") or {}).get("Running")):
            raise Refused(f"{POSTGRES} is not running, so I can't read the database")
        networks = ((raw.get("NetworkSettings") or {}).get("Networks") or {})
        for settings in networks.values():
            address = (settings or {}).get("IPAddress")
            if address:
                return str(address), 5432
        raise Refused(f"{POSTGRES} has no address I can reach")

    def _query(self, sql: str, cap: int = ROW_CAP) -> dict[str, Any]:
        """One read, through psql, as the login that may only read.

        psql is what the box has (temper's own driver lives in its containers,
        not here), and it keeps this service free of a database library. The
        query is one argument of a fixed argument list: no shell, nothing
        interpolated by a program that could mean something else by it.
        """
        host, port = self._db_host()
        user = _env_value("ROAMEE_READER_DB_USER", DEFAULT_DB_USER)
        password = _env_value("ROAMEE_READER_DB_PASSWORD")
        dbname = _env_value("ROAMEE_READER_DB_NAME", DEFAULT_DB)
        if not password:
            raise Refused("the read-only login for staging's database is not set up "
                          "(ROAMEE_READER_DB_PASSWORD in ~/temper-ai/.env), so I can't read it")
        capped = f"select * from ({sql}) as roamee_reader limit {cap + 1}"
        # --csv last, and no --no-align after it: either one switches the
        # format back to psql's own, where the answer comes back as one
        # pipe-joined string with a "(1 row)" line under it.
        args = ["--no-psqlrc", "--pset=pager=off", "--pset=footer=off", "--csv", "-w",
                "-v", "ON_ERROR_STOP=1",
                "-h", host, "-p", str(port), "-U", user, "-d", dbname, "-c", capped]
        env = {
            "PGPASSWORD": password,
            "PGCONNECT_TIMEOUT": str(CONNECT_TIMEOUT_S),
            # The second lock's teeth: the session cannot write, cannot run
            # long, and cannot sit in a transaction.
            "PGOPTIONS": (f"-c statement_timeout={STATEMENT_TIMEOUT_MS} "
                          "-c default_transaction_read_only=on "
                          "-c idle_in_transaction_session_timeout=10000"),
        }
        try:
            code, out, err = self._psql(args, env, (STATEMENT_TIMEOUT_MS / 1000) + CONNECT_TIMEOUT_S + 5)
        except subprocess.TimeoutExpired as exc:
            raise Refused(f"that query took longer than {STATEMENT_TIMEOUT_MS // 1000} seconds, "
                          "so I stopped waiting for it") from exc
        except FileNotFoundError as exc:
            raise Refused("psql is not on this box, so I can't read staging's database") from exc
        if code != 0:
            text = scrub(err).strip()
            low = text.lower()
            if "statement timeout" in low or "canceling statement" in low:
                raise Refused(f"that query took longer than {STATEMENT_TIMEOUT_MS // 1000} seconds, "
                              "so staging's database stopped it")
            if "read-only transaction" in low or "permission denied" in low or "must be owner" in low:
                raise Refused(f"staging's database would not let this login do that: {text[:300]}")
            raise Refused(f"staging's database refused that: {text[:300]}")
        names, rows = _from_csv(out)
        hidden = [i for i, name in enumerate(names) if _SECRET_COLUMN.search(name)]
        shown = []
        for row in rows[:cap]:
            cells = []
            for i, value in enumerate(row):
                cells.append(BLANK if i in hidden else _clip(scrub(value) if value is not None else "", CELL_CHARS))
            shown.append(cells)
        return {
            "looked_at": _now(),
            "source": f"staging's database {dbname} on {POSTGRES}, read-only login {user}",
            "columns": names,
            "rows": shown,
            "row_count": len(shown),
            "truncated": len(rows) > cap,
            "hidden_columns": [names[i] for i in hidden],
        }

    def tables(self) -> dict[str, Any]:
        return self._query(
            "select c.relname as table_name, c.reltuples::bigint as rows_estimate, "
            "pg_size_pretty(pg_total_relation_size(c.oid)) as size "
            "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relkind = 'r' order by c.relname",
            cap=LIST_CAP)

    def columns(self, table: str) -> dict[str, Any]:
        name = str(table or "").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", name):
            raise Refused(f"{table!r} is not a table name")
        # The name is already only letters, digits and underscores (above), so
        # there is nothing in it a quoted literal could turn into something
        # else; it is still written as one, because the next person will copy
        # this line.
        found = self._query(
            "select column_name, data_type, is_nullable, coalesce(column_default, '') as column_default "
            "from information_schema.columns where table_schema = 'public' "
            f"and table_name = '{name}' order by ordinal_position", cap=LIST_CAP)
        if not found["rows"]:
            raise Refused(f"staging's database has no table called {name!r} in public")
        found["table"] = name
        return found

    def read(self, sql: str) -> dict[str, Any]:
        return self._query(plain_read(sql))

    # -- the door -----------------------------------------------------------

    def handle(self, method: str, path: str, query: dict[str, list[str]],
               body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            if method == "GET" and path == "/health":
                return 200, {"ok": True, "version": VERSION, "looked_at": _now(),
                             "containers": list(CONTAINERS)}
            if method == "GET" and path == "/stack":
                return 200, self.stack()
            if method == "GET" and path == "/checks":
                return 200, self.checks(_one(query, "branch") or BRANCH)
            if method == "GET" and path == "/logs":
                return 200, self.logs(_one(query, "container"),
                                      _one(query, "lines") or LOG_LINES_DEFAULT)
            if method == "POST" and path == "/sql":
                action = str(body.get("action") or "").strip().lower()
                if action == "tables":
                    return 200, self.tables()
                if action == "columns":
                    return 200, self.columns(str(body.get("table") or ""))
                if action == "read":
                    return 200, self.read(str(body.get("sql") or ""))
                raise Refused(f"'{action}' is not something I can do with the database; "
                              "I know 'tables', 'columns' and 'read'")
        except Refused as exc:
            return 403, {"error": scrub(exc)}
        except Exception as exc:  # noqa: BLE001 - the caller gets a plain reason, never a traceback
            logger.warning("roamee-reader: %s %s went wrong: %s", method, path, exc)
            return 500, {"error": scrub(f"{type(exc).__name__}: {exc}")[:300]}
        return 404, {"error": f"{method} {path} is not something I answer"}


def _one(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name) or []
    return str(values[0]) if values else ""


# -- the one plain read ------------------------------------------------------

_CHANGES = re.compile(
    r"(?is)\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|reindex|"
    r"comment|call|do|merge|set|begin|commit|rollback|notify|listen|unlisten|lock|refresh|cluster|"
    r"prepare|execute|deallocate|discard|reset|savepoint|release|import|load|security|"
    r"pg_read_file|pg_read_binary_file|pg_ls_dir|lo_import|lo_export|dblink|copy_from)\b"
)


def plain_read(sql: str) -> str:
    """The query, if it is one plain read. Anything else raises :class:`Refused`.

    This is the second lock. The first is the login itself, which may only
    read; this one means a mistake in the first cannot be reached, and it says
    no in words a person can act on.
    """
    text = str(sql or "").strip().rstrip(";").strip()
    if not text:
        raise Refused("there is no query to run")
    if len(text) > 4_000:
        raise Refused("that query is longer than I will run (4,000 characters)")
    if ";" in text:
        raise Refused("I run one statement at a time, so a ';' in the middle is a no")
    if "\\" in text:
        raise Refused("a backslash is not something I pass on: psql would read it as a command of its own")
    if not re.match(r"(?is)^(select|with)\b", text):
        raise Refused("I only run a plain read: it has to start with SELECT (or WITH ... SELECT)")
    found = _CHANGES.search(text)
    if found:
        raise Refused(f"'{found.group(1).upper()}' is not something I will run: "
                      "this reads staging's database and never changes it")
    return text


# -- the socket --------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = f"roamee-reader/{VERSION}"
    reader: Reader = Reader()

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - BaseHTTPRequestHandler's name
        logger.info("roamee-reader: " + fmt, *args)

    def _answer(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        parsed = urlparse(self.path)
        self._answer(*self.reader.handle("GET", parsed.path, parse_qs(parsed.query), {}))

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(min(length, 16_384)) if length else b""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            self._answer(400, {"error": "that was not JSON"})
            return
        if not isinstance(body, dict):
            self._answer(400, {"error": "that was not a JSON object"})
            return
        self._answer(*self.reader.handle("POST", parsed.path, parse_qs(parsed.query), body))


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    request_queue_size = 32

    def get_request(self) -> tuple[Any, Any]:
        request, _ = super().get_request()
        return request, ("run-container", 0)


def serve(path: Path = SOCKET_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)  # a socket left behind by a crash
    server = _Server(str(path), _Handler)
    # A run container runs as another user; the socket's folder reaches it
    # only through the read-only mount temper's containers have (connecting
    # to a socket is allowed on a read-only mount; creating a file is not).
    os.chmod(path, 0o666)  # noqa: S103 - deliberate: see above
    logger.info("roamee-reader: listening on %s for %s", path, ", ".join(CONTAINERS))
    try:
        server.serve_forever()
    finally:
        server.server_close()
        path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args and args[0] == "--check":
        reader = Reader()
        status, payload = reader.handle("GET", "/stack", {}, {})
        print(json.dumps(payload, indent=2, default=str))
        return 0 if status == 200 else 1
    path = Path(args[0]) if args else SOCKET_PATH
    try:
        serve(path)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
