"""roamee-reader: the one door between a run and roamee's staging stack.

Pinned here, because this file is the fence: it looks at roamee's three
staging containers and nothing else; it never reads a container's
environment, command line or mounts; it blanks anything shaped like a key
out of a log, an error or a cell; it runs one plain read and refuses
everything that writes, chains or takes too long; and it answers four
questions and no more.

Docker, psql and gh are fakes throughout: no test here touches the live
stack, the live database or GitHub.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "roamee_reader.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("roamee_reader", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reader_module = _load()
Refused = reader_module.Refused
CONTAINERS = reader_module.CONTAINERS
BLANK = reader_module.BLANK


# -- fakes -------------------------------------------------------------------


RUNNING = {
    "State": {"Status": "running", "Running": True, "StartedAt": "2026-09-29T10:00:00.000000000Z",
              "Health": {"Status": "healthy"}},
    "Config": {
        "Image": "roamee-staging-backend:latest",
        "Labels": {"com.docker.compose.service": "backend", "com.docker.compose.project": "roamee-staging",
                   "standee.commit": "abc1234"},
        # The three things that must never come back:
        "Env": ["DATABASE_URL=postgresql://roamee:hunter2@postgres:5432/trip_planner_staging",
                "OPENAI_API_KEY=sk-live-0123456789abcdefghij"],
        "Cmd": ["uvicorn", "app.main:app", "--host", "0.0.0.0"],
        "Entrypoint": ["/entrypoint.sh"],
    },
    "Image": "sha256:0123456789abcdef0123456789abcdef",
    "RestartCount": 2,
    "Mounts": [{"Source": "/home/shinelay/roamee/.env", "Destination": "/app/.env"}],
    "NetworkSettings": {"Networks": {"roamee-staging_default": {"IPAddress": "172.31.0.5"}},
                        "Ports": {"8500/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8500"}]}},
}


class FakeDocker:
    """`docker inspect` and `docker logs` for roamee's three containers."""

    def __init__(self, missing: tuple[str, ...] = (), stopped: tuple[str, ...] = ()) -> None:
        self.calls: list[list[str]] = []
        self.missing = missing
        self.stopped = stopped
        self.log = ("2026-09-30T12:00:00Z INFO started\n"
                    "2026-09-30T12:00:01Z INFO DATABASE_URL=postgresql://roamee:hunter2@postgres:5432/db\n"
                    "2026-09-30T12:00:02Z INFO authorization: Bearer abcdefghijklmnop\n")

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(args))
        name = args[-1]
        if args[0] == "inspect":
            if name in self.missing:
                return 1, "", f'Error: No such object: {name}'
            raw = {**RUNNING}
            if name in self.stopped:
                raw = {**RUNNING, "State": {"Status": "exited", "Running": False, "ExitCode": 1,
                                            "StartedAt": "2026-09-29T10:00:00Z",
                                            "FinishedAt": "2026-09-30T09:00:00Z"}}
            import json as _json
            return 0, _json.dumps([raw]), ""
        if args[0] == "logs":
            return 0, self.log, ""
        raise AssertionError(f"roamee-reader asked docker to {args[0]!r}, which it must never do")


class FakePsql:
    """psql: records the argument list and the environment, answers CSV."""

    def __init__(self, out: str = "count\n42\n", code: int = 0, err: str = "") -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.out, self.code, self.err = out, code, err
        self.raises: Exception | None = None

    def __call__(self, args: list[str], env: dict[str, str], timeout: float) -> tuple[int, str, str]:
        self.calls.append((list(args), dict(env)))
        if self.raises:
            raise self.raises
        return self.code, self.out, self.err

    @property
    def sql(self) -> str:
        args = self.calls[-1][0]
        return args[args.index("-c") + 1]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROAMEE_READER_DB_PASSWORD", "staging-reader-password")
    monkeypatch.setenv("ROAMEE_READER_DB_USER", "temper_ro")
    monkeypatch.setenv("ROAMEE_READER_DB_NAME", "trip_planner_staging")


class FakeGh:
    """`gh api`: records the argument list, answers GitHub's JSON."""

    CHECK_RUNS = {"check_runs": [
        {"name": "frontend", "status": "completed", "conclusion": "success",
         "head_sha": "08fbfbe97a2098911aaa484329963ab441cb2679", "started_at": "2026-09-30T12:00:00Z"},
        {"name": "backend", "status": "completed", "conclusion": "failure",
         "head_sha": "08fbfbe97a2098911aaa484329963ab441cb2679", "started_at": "2026-09-30T12:00:00Z"},
    ]}

    def __init__(self, out: str | None = None, code: int = 0, err: str = "") -> None:
        self.calls: list[list[str]] = []
        self.out = json.dumps(self.CHECK_RUNS) if out is None else out
        self.code, self.err = code, err
        self.raises: Exception | None = None

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(args))
        if self.raises:
            raise self.raises
        return self.code, self.out, self.err


def reader(docker: Any = None, psql: Any = None, gh: Any = None) -> Any:
    return reader_module.Reader(docker=docker or FakeDocker(), psql=psql or FakePsql(),
                                gh=gh or FakeGh())


# -- the stack ---------------------------------------------------------------


def test_stack_says_what_is_up_and_from_where() -> None:
    docker = FakeDocker()
    found = reader(docker).stack()
    assert found["up"] is True
    assert [c["container"] for c in found["containers"]] == list(CONTAINERS)
    assert found["containers"][0]["build"] == "abc1234"
    assert found["containers"][0]["health"] == "healthy"
    assert found["containers"][0]["restarts"] == 2
    assert found["containers"][0]["up_for"]
    assert found["looked_at"] and "docker inspect" in found["source"]
    assert all(call[0] == "inspect" for call in docker.calls)


def test_stack_never_returns_the_environment_the_command_or_the_mounts() -> None:
    found = reader().stack()
    text = str(found)
    for secret in ("hunter2", "sk-live-0123456789abcdefghij", "DATABASE_URL", "uvicorn",
                   "entrypoint.sh", "/home/shinelay/roamee/.env"):
        assert secret not in text, f"{secret} came back out of docker inspect"
    assert set(found["containers"][0]) == {
        "container", "service", "project", "state", "health", "image", "image_id", "build",
        "started_at", "up_for", "restarts", "ports"}


def test_stack_says_plainly_when_one_is_missing_or_stopped() -> None:
    found = reader(FakeDocker(missing=(CONTAINERS[0],), stopped=(CONTAINERS[1],))).stack()
    assert found["up"] is False
    assert found["containers"][0]["state"] == "not there"
    assert found["containers"][1]["state"] == "exited"
    assert found["containers"][1]["exit_code"] == 1


def test_logs_only_for_roamees_containers() -> None:
    docker = FakeDocker()
    with pytest.raises(Refused) as refused:
        reader(docker).logs("temper-ai-server-1")
    assert "roamee" in str(refused.value)
    assert docker.calls == [], "it asked docker about a container that is not roamee's"


@pytest.mark.parametrize("container", ["temper-ai-postgres-1", "rollcall-prod", "", "../../etc", "all"])
def test_logs_refuse_every_other_container(container: str) -> None:
    with pytest.raises(Refused):
        reader().logs(container)


def test_logs_blank_out_secrets_and_cap_the_lines() -> None:
    docker = FakeDocker()
    found = reader(docker).logs(CONTAINERS[1], lines=9_999)
    assert "hunter2" not in found["log"]
    assert "abcdefghijklmnop" not in found["log"]
    assert BLANK in found["log"]
    assert found["lines"] == reader_module.LOG_LINES_MAX
    assert docker.calls[-1][:4] == ["logs", "--tail", str(reader_module.LOG_LINES_MAX), "--timestamps"]


def test_long_logs_are_cut_off() -> None:
    docker = FakeDocker()
    docker.log = "x" * 50_000
    found = reader(docker).logs(CONTAINERS[0])
    assert len(found["log"]) < 50_000
    assert "more characters" in found["log"]


# -- the database ------------------------------------------------------------


def test_read_runs_one_capped_query_as_the_read_only_login(env: None) -> None:
    psql = FakePsql(out="count\n42\n")
    found = reader(psql=psql).read("select count(*) from trips")
    assert found["columns"] == ["count"]
    assert found["rows"] == [["42"]]
    args, environment = psql.calls[-1]
    assert "select count(*) from trips" in psql.sql
    assert f"limit {reader_module.ROW_CAP + 1}" in psql.sql
    assert environment["PGPASSWORD"] == "staging-reader-password"
    assert "default_transaction_read_only=on" in environment["PGOPTIONS"]
    assert f"statement_timeout={reader_module.STATEMENT_TIMEOUT_MS}" in environment["PGOPTIONS"]
    assert "-U" in args and args[args.index("-U") + 1] == "temper_ro"
    assert "--csv" in args and "-w" in args


@pytest.mark.parametrize("sql", [
    "insert into trips (name) values ('x')",
    "update trips set name = 'x'",
    "delete from trips",
    "drop table trips",
    "truncate trips",
    "alter table trips add column x int",
    "create table x (a int)",
    "grant select on trips to public",
    "copy trips to '/tmp/out.csv'",
    "set role postgres",
    "select 1; drop table trips",
    "select pg_read_file('/app/.env')",
    "select * from dblink('host=other', 'select 1') as t(a int)",
    "with x as (delete from trips returning *) select * from x",
    "\\! cat /app/.env",
    "select lo_import('/app/.env')",
    "",
])
def test_a_write_or_a_trick_never_reaches_the_database(sql: str, env: None) -> None:
    psql = FakePsql()
    with pytest.raises(Refused):
        reader(psql=psql).read(sql)
    assert psql.calls == [], f"{sql!r} was sent to staging's database"


@pytest.mark.parametrize("sql", [
    "select count(*) from trips",
    "SELECT status, count(*) FROM trips GROUP BY 1 ORDER BY 2 DESC",
    "with recent as (select * from trips order by created_at desc limit 5) select count(*) from recent",
])
def test_a_plain_read_is_allowed(sql: str) -> None:
    assert reader_module.plain_read(sql)


def test_the_row_cap_is_said_out_loud(env: None) -> None:
    rows = "\n".join(f"{i}" for i in range(reader_module.ROW_CAP + 1))
    found = reader(psql=FakePsql(out=f"id\n{rows}\n")).read("select id from trips")
    assert found["row_count"] == reader_module.ROW_CAP
    assert found["truncated"] is True


def test_a_slow_query_is_stopped_and_said_so(env: None) -> None:
    psql = FakePsql(code=1, err="ERROR:  canceling statement due to statement timeout")
    with pytest.raises(Refused) as refused:
        reader(psql=psql).read("select count(*) from trips")
    assert "longer than 5 seconds" in str(refused.value)


def test_psql_taking_too_long_is_stopped_too(env: None) -> None:
    psql = FakePsql()
    psql.raises = subprocess.TimeoutExpired(cmd="psql", timeout=10)
    with pytest.raises(Refused) as refused:
        reader(psql=psql).read("select count(*) from trips")
    assert "longer than" in str(refused.value)


def test_a_refused_write_from_postgres_itself_is_passed_on_plainly(env: None) -> None:
    psql = FakePsql(code=1, err="ERROR:  cannot execute INSERT in a read-only transaction")
    with pytest.raises(Refused) as refused:
        reader(psql=psql).read("select * from trips")
    assert "would not let this login" in str(refused.value)


def test_no_password_means_no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROAMEE_READER_DB_PASSWORD", raising=False)
    monkeypatch.setattr(reader_module, "ENV_FILE", Path("/nonexistent/.env"))
    psql = FakePsql()
    with pytest.raises(Refused) as refused:
        reader(psql=psql).read("select 1")
    assert "read-only login" in str(refused.value)
    assert psql.calls == []


def test_a_column_that_sounds_like_a_secret_is_blanked(env: None) -> None:
    psql = FakePsql(out="email,password_hash,api_key\nsomeone@example.com,$2b$12$abcd,sk-live-abcdefghijkl\n")
    found = reader(psql=psql).read("select email, password_hash, api_key from users")
    assert found["rows"] == [["someone@example.com", BLANK, BLANK]]
    assert found["hidden_columns"] == ["password_hash", "api_key"]


def test_a_secret_in_a_cell_is_blanked_even_when_the_column_sounds_fine(env: None) -> None:
    psql = FakePsql(out="note\nconnect with postgresql://roamee:hunter2@db:5432/x\n")
    found = reader(psql=psql).read("select note from notes")
    assert "hunter2" not in str(found["rows"])
    assert BLANK in found["rows"][0][0]


def test_tables_and_columns_are_built_here_not_taken_from_the_caller(env: None) -> None:
    psql = FakePsql(out="table_name,rows_estimate,size\ntrips,120,64 kB\n")
    found = reader(psql=psql).tables()
    assert found["rows"] == [["trips", "120", "64 kB"]]
    assert "pg_class" in psql.sql and "public" in psql.sql

    psql = FakePsql(out="column_name,data_type,is_nullable,column_default\nid,integer,NO,\n")
    found = reader(psql=psql).columns("trips")
    assert found["table"] == "trips"
    assert "information_schema.columns" in psql.sql and "'trips'" in psql.sql


@pytest.mark.parametrize("table", ["trips; drop table users", "pg_shadow'", "../etc/passwd", "a" * 100, ""])
def test_a_table_name_that_is_not_a_name_is_refused(table: str, env: None) -> None:
    psql = FakePsql()
    with pytest.raises(Refused):
        reader(psql=psql).columns(table)
    assert psql.calls == []


def test_a_table_that_is_not_there_says_so(env: None) -> None:
    psql = FakePsql(out="column_name,data_type,is_nullable,column_default\n")
    with pytest.raises(Refused) as refused:
        reader(psql=psql).columns("nosuchtable")
    assert "no table called" in str(refused.value)


def test_the_database_is_only_ever_roamees_staging_one(env: None) -> None:
    psql = FakePsql()
    docker = FakeDocker(missing=(reader_module.POSTGRES,))
    with pytest.raises(Refused) as refused:
        reader(docker, psql).read("select 1")
    assert reader_module.POSTGRES in str(refused.value)
    assert psql.calls == []


# -- the door ----------------------------------------------------------------


def test_only_four_questions_are_answered(env: None) -> None:
    one = reader()
    assert one.handle("GET", "/health", {}, {})[0] == 200
    assert one.handle("GET", "/stack", {}, {})[0] == 200
    assert one.handle("GET", "/logs", {"container": [CONTAINERS[0]]}, {})[0] == 200
    assert one.handle("POST", "/sql", {}, {"action": "tables"})[0] == 200
    for method, path, body in [("GET", "/env", {}), ("POST", "/exec", {"cmd": "ls"}),
                               ("DELETE", "/stack", {}), ("GET", "/secrets", {}),
                               ("POST", "/stack", {"action": "restart"}), ("GET", "/", {})]:
        status, payload = one.handle(method, path, {}, body)
        assert status in (403, 404, 500), f"{method} {path} was answered"
        assert "error" in payload


def test_a_refusal_comes_back_as_words_not_a_traceback(env: None) -> None:
    status, payload = reader().handle("POST", "/sql", {}, {"action": "read", "sql": "drop table trips"})
    assert status == 403
    assert "SELECT" in payload["error"]
    assert "Traceback" not in payload["error"]

    status, payload = reader().handle(
        "POST", "/sql", {}, {"action": "read", "sql": "select * from trips where id in (delete from users)"})
    assert status == 403
    assert "DELETE" in payload["error"]


def test_an_unknown_database_action_is_refused(env: None) -> None:
    status, payload = reader().handle("POST", "/sql", {}, {"action": "write", "sql": "select 1"})
    assert status == 403
    assert "'write'" in payload["error"]


# -- the checks --------------------------------------------------------------


def test_the_checks_are_one_get_about_one_repository() -> None:
    gh = FakeGh()
    status, payload = reader(gh=gh).handle("GET", "/checks", {"branch": ["staging"]}, {})
    assert status == 200
    assert gh.calls == [["api", "--method", "GET",
                        "repos/shine2lay/roamee/commits/staging/check-runs", "-F", "per_page=100"]]
    assert payload["total"] == 2 and payload["failed"] == 1
    assert payload["commit"] == "08fbfbe9" and payload["branch"] == "staging"
    assert [c["check"] for c in payload["checks"]] == ["backend", "frontend"], "a failing check first"
    assert "looked_at" in payload and "GitHub check runs" in payload["source"]


def test_without_a_branch_it_asks_about_staging() -> None:
    gh = FakeGh()
    reader(gh=gh).handle("GET", "/checks", {}, {})
    assert "commits/staging/check-runs" in gh.calls[0][3]


@pytest.mark.parametrize("branch", [
    "x; rm -rf /",            # a command
    "../../../etc/passwd",    # somewhere else in the API
    "staging --method POST",  # another kind of call
    "a" * 200,                # longer than any branch name
    "",                       # nothing at all is 'staging', never an empty path
])
def test_a_branch_that_is_not_a_branch_never_reaches_github(branch: str) -> None:
    gh = FakeGh()
    status, payload = reader(gh=gh).handle("GET", "/checks", {"branch": [branch]}, {})
    if branch == "":
        assert status == 200 and "commits/staging/check-runs" in gh.calls[0][3]
        return
    assert status == 403 and "does not look like a branch name" in payload["error"]
    assert gh.calls == [], "gh was never run"


def test_a_repository_that_is_not_roamee_cannot_be_asked_for() -> None:
    """There is no parameter for it: the repository is in this file."""
    gh = FakeGh()
    reader(gh=gh).handle("GET", "/checks", {"branch": ["staging"], "repo": ["shine2lay/rollcall"]}, {})
    assert all("shine2lay/roamee/" in part for call in gh.calls for part in call if part.startswith("repos/"))
    assert not any("rollcall" in part for call in gh.calls for part in call)


def test_github_saying_no_is_passed_on_in_words() -> None:
    gh = FakeGh(out="", code=1, err="gh: Not Found (HTTP 404)")
    status, payload = reader(gh=gh).handle("GET", "/checks", {"branch": ["nope"]}, {})
    assert status == 403 and "no branch nope" in payload["error"]


def test_a_box_without_gh_says_so_instead_of_breaking() -> None:
    gh = FakeGh()
    gh.raises = FileNotFoundError(2, "No such file or directory", "gh")
    status, payload = reader(gh=gh).handle("GET", "/checks", {}, {})
    assert status == 403 and "no gh" in payload["error"]


def test_gh_taking_too_long_is_said_plainly() -> None:
    gh = FakeGh()
    gh.raises = subprocess.TimeoutExpired(cmd="gh", timeout=20)
    status, payload = reader(gh=gh).handle("GET", "/checks", {}, {})
    assert status == 403 and "too long" in payload["error"]


def test_a_check_run_cannot_carry_a_secret_out() -> None:
    gh = FakeGh(out=json.dumps({"check_runs": [
        {"name": "deploy (DATABASE_URL=postgresql://u:hunter2@db/x)", "status": "completed",
         "conclusion": "failure", "head_sha": "abc1234def"}]}))
    _status, payload = reader(gh=gh).handle("GET", "/checks", {}, {})
    assert "hunter2" not in json.dumps(payload)


# -- blanking ----------------------------------------------------------------


@pytest.mark.parametrize("text,gone", [
    ("postgresql://roamee:hunter2@db:5432/x", "hunter2"),
    ("OPENAI_API_KEY=sk-live-0123456789abcdefghij", "sk-live-0123456789abcdefghij"),
    ("authorization: Bearer abcdefghijklmnopqrst", "abcdefghijklmnopqrst"),
    ("token: xoxb-1234567890-abcdefghij", "xoxb-1234567890-abcdefghij"),
    ("LINEAR_KEY=lin_api_0123456789abcdef", "lin_api_0123456789abcdef"),
    ("password = 'swordfish'", "swordfish"),
])
def test_scrub_blanks_everything_shaped_like_a_key(text: str, gone: str) -> None:
    out = reader_module.scrub(text)
    assert gone not in out
    assert BLANK in out


def test_scrub_leaves_ordinary_text_alone() -> None:
    assert reader_module.scrub("12 trips, 3 of them planned") == "12 trips, 3 of them planned"
