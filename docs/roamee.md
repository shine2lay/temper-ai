# Asking about roamee

A question about roamee in Slack is answered by the `roamee_answer`
workflow, not by `repo_answer`. Roamee is the one repository temper is asked
about where the question is often not about code at all — *is staging up?
what's running on it? how many trips are there? what's open?* — so its
answerer can look at four things instead of one.

All four are read-only. Nothing behind this door can change a repository, a
container, a row, a pull request or an issue, and no tool here takes a shell
command, a path to run, or anything else free-form. Secrets are never
printed, however the question is put.

```
/temper ask is roamee staging up and what's running on it?
@temper how many trips are in staging, by status?
```

## What it can see

| Where | Tool | What it can be asked |
|---|---|---|
| The code | `Read` `Grep` `Glob` | The read-only copy of roamee at `staging`, kept fresh by the same `repo_copies` step `repo_answer` uses (refetched at most every 10 minutes). Capability notes (`.temper/`) first, then the code. |
| The running stack | `RoameeStack` | `status`: the three staging containers — running or not, health check, image and build, when it started and for how long, restarts, published ports. `logs` with `container=`: the tail of one of those containers' log (200 lines and 8,000 characters at most, secrets blanked). |
| The data | `RoameeData` | `tables`: every table with a row estimate and its size. `columns` with `table=`: one table's shape. `read` with `sql=`: one plain `SELECT`, 50 rows and 5 seconds at most, as a small table. |
| The work | `RoameeWork` | `pulls` (open pull requests), `commits` (recent, with author and date), `checks` (how the checks went on the branch's latest commit, failing ones first — through roamee-reader's `gh`, see below), `issues` (open Linear issues in team ROA). |

Every tool's answer begins with where it looked and when, and the answer ends
with a `Read:` line naming those sources: `roamee staging a1b2c3d`,
`roamee-staging-backend-1 at 14:02 UTC`, `staging's database at 14:02 UTC`,
`GitHub shine2lay/roamee`, `Linear ROA`. A fact without a source is a bug.

A question it cannot answer gets "I couldn't find that" and what was looked
at — never a guess, and never a number that didn't come from a tool.

## What it refuses

- **Anything that is not roamee.** The three container names and the one
  database are written into the service that does the looking:
  `roamee-staging-frontend-1`, `roamee-staging-backend-1`,
  `roamee-staging-postgres-1`. Another container, another database, another
  project is refused by name, so this door cannot be turned on temper's own
  stack or rollcall's.
- **Anything that writes.** A read takes a single `SELECT` or `WITH … SELECT`
  and nothing else: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`,
  `TRUNCATE`, `GRANT`, `COPY`, `SET`, `CALL`, a second statement after a `;`,
  or a call to `pg_read_file`, `lo_import` or `dblink` is refused before
  anything is sent. The containers are only ever inspected (`docker inspect`,
  `docker logs`) — never started, stopped, restarted or executed in; there is
  no endpoint on the other side that would.
- **Secrets.** A container's answer is built from an allowlist of fields, so
  `Env`, `Cmd`, `Entrypoint` and `Mounts` are never even read out of
  `docker inspect`. Logs, error messages and every cell of a result go
  through the same blanking: a password, a token, a key, a bearer header or a
  connection string comes back `[hidden]`, and a column whose *name* sounds
  like a secret (`password`, `token`, `api_key`, `session_id`, `hash`, …) is
  blanked whatever it holds. The answerer is told the same, and has no way to
  reach `.env`.
- **A query that is too big or too slow.** 50 rows (300 for the table and
  column lists), 4,000 characters of SQL, and a 5-second statement timeout:
  a longer query is stopped by Postgres and the answer says so.

## Two locks on the database

The connection is `temper_ro`, a Postgres login made for this and nothing
else: `CONNECT`, `USAGE` and `SELECT`, with `DEFAULT PRIVILEGES` so it keeps
only `SELECT` on tables made later, and none of `pg_read_server_files`,
`pg_write_server_files` or `pg_execute_server_program`. Its password sits
with temper's other keys in `~/temper-ai/.env`
(`ROAMEE_READER_DB_PASSWORD`; `ROAMEE_READER_DB_USER` and
`ROAMEE_READER_DB_NAME` override the defaults). Nothing else is read out of
that file.

The check in `plain_read()` is the second lock: it refuses anything but one
plain read before a statement is sent, and the session that does run has
`default_transaction_read_only=on`, `statement_timeout=5s`,
`idle_in_transaction_session_timeout=10s`, a `LIMIT` wrapped around the
query, and a `ROLLBACK` at the end. Either lock alone would be a single point
of failure; both would have to fail for a write to happen.

Without the password the tool says the database isn't set up for reading and
stops. It never falls back to another connection string, and temper's own
`DATABASE_URL` is not used.

## How it is wired

- `configs/workflows/roamee_answer.yaml` — two steps: `code` (the shared
  `repo_copies` script, `only: roamee`) then `answer`.
- `configs/agents/roamee_answer.yaml` — Sonnet, medium effort, 20 steps,
  7 minutes, the tools above.
- `temper_ai/tools/roamee.py` — `RoameeStack`, `RoameeData`, `RoameeWork`.
  Each one's behaviour is in the class, not in a config: a `config:` on a
  tool in an agent file never reaches the run.
- `scripts/roamee_reader.py` — **roamee-reader**, the one door between a run
  and the stack, and where the fence lives.
- `temper_ai/integrations/slack/answer.py` — `workflow_for()` picks between
  `repo_answer` and `roamee_answer`, the same way from `/temper ask` and from
  plain words: roamee's answerer when the asker may only ask about roamee
  (the `roamee` role), or when the question names roamee and no other
  repository. A question naming two repositories, or none, stays with
  `repo_answer`, which can look in all three.

A run happens inside its own container, with no docker socket and no route to
roamee's network, so `RoameeStack` and `RoameeData` ask roamee-reader
instead. It runs on the host as the owner (a user systemd service) and
listens on a unix socket at `~/.temper/roamee-reader/reader.sock`; temper's
server and worker have that folder mounted read-only at `/app/roamee-reader`
(docker-compose.yml, `ROAMEE_READER_DIR`), and a run inherits the mount, so
it can speak to the socket and can neither move nor delete it. Nothing is
published on any port. It answers exactly five things — `GET /health`,
`GET /stack`, `GET /logs`, `GET /checks`, `POST /sql` — and refuses
everything else.

`RoameeWork` reads GitHub and Linear from inside the run, through temper's
own app credentials — except `checks`. Temper's installation token carries
contents, issues and pull requests only (`integrations/github/app.py`,
`PERMISSIONS`), so GitHub answers 403 for check runs; widening that token
would widen it for every repository temper touches. So the one question goes
to roamee-reader, which runs the box's own `gh` with an argument list it
builds itself: one repository (`shine2lay/roamee`, written in the file, not
taken from the caller), one branch whose name has to look like a branch name,
and `--method GET`.

```bash
mkdir -p ~/.temper/roamee-reader          # before the containers mount it
cp scripts/systemd/roamee-reader.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now roamee-reader
python3 scripts/roamee_reader.py --check      # prints what it can see, then stops
```

The read-only login it uses is made once, in staging's own postgres:

```sql
create role temper_ro login password '…';          -- the password goes in ~/temper-ai/.env
grant connect on database trip_planner_staging to temper_ro;
grant usage on schema public to temper_ro;
revoke create on schema public from temper_ro;
grant select on all tables in schema public to temper_ro;
alter default privileges in schema public grant select on tables to temper_ro;
alter role temper_ro set default_transaction_read_only = on;
alter role temper_ro set statement_timeout = 5000;
```

`ROAMEE_READER_DB_PASSWORD` in `~/temper-ai/.env` is the only new key, and
only roamee-reader reads it: a run never sees it, and the service blanks
anything shaped like one out of every answer.

## What it costs

A code question costs what `/temper ask` costs, 3–25 cents; a stack or data
question is a tool call or two more, not a bigger model, so it lands in the
same range. The pick (plain words to @temper rather than `/temper ask`) adds
1–2 cents. `roamee_answer` runs post no notices: the answer is the message.

## Checking it

```bash
uv run pytest tests/test_tools/test_roamee.py tests/test_scripts/test_roamee_reader.py \
              tests/test_integrations/test_slack_answer.py
docker exec -w /app temper-ai-server-1 /app/.venv/bin/temper check
```

The tests drive the whole of roamee-reader with fakes for Docker and
Postgres, and the tools with a fake socket — nothing in them touches the live
stack, GitHub or Linear. Live, the four shapes of question are a code one,
`is staging up and what's running?`, `how many trips are there?` and one with
no answer; a question about another repository should be turned down in a
line.
