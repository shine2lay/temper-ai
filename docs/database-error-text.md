# Database errors: what leaves temper

On Postgres, a database error's text carries row values. The server's DETAIL
holds the whole failing row for not-null and check failures
(`Failing row contains (...)`, which on a run or hold row includes its inputs)
and the key values for unique and foreign-key failures (`Key (col)=(value)`).
SQLAlchemy's text adds the failing statement and its parameters. A data
exception's primary message quotes the input it could not read
(`invalid input syntax for type integer: "..."`). Log lines and error replies
outlive the rows, so none of this leaves temper. Code inside temper still gets
the whole exception: nothing here changes an exception object.

## The safe text

`temper_ai/shared/database_error_text.py` gives a database error's safe text:

- the driver's exception class and the SQLSTATE;
- the schema, table, column, datatype and constraint names the server reports;
- the server's primary message, with every double-quoted span that is not one
  of those names, and every byte sequence shown in hex, replaced by `<withheld>`.

For example, a not-null failure reads
`(psycopg2.errors.NotNullViolation) null value in column "name" of relation "jobs" violates not-null constraint (SQLSTATE 23502, schema=public, table=jobs, column=name)`.

Never included: DETAIL, HINT, CONTEXT, the internal query, the statement or
its parameters. Another driver's error (SQLite's) keeps its message's first
line, with quoted spans withheld: SQLite names tables and columns, not values,
but a syntax error quotes the token it stopped at, which can be a literal. SQLAlchemy's
"rolled back due to a previous exception" error quotes that earlier error's
whole text; only its first line is kept, quoted spans withheld. Any other
exception keeps its own text, except where it quotes a database error from its
chain (`raise X(f"...: {exc}") from exc`): that part gets the safe text too.

## Where it applies

- **Log lines.** `temper_ai/shared/database_values_log_filter.py` puts one
  filter on every log handler: the server's root and uvicorn handlers
  (`temper_ai/server.py`), and the CLI's (`temper_ai/cli/main.py`, after each
  `logging.basicConfig`, watch-queue's `force=True` one included). That covers
  the server, the worker and pi-worker (watch-queue) and every run box
  (run-workflow). The filter renders an exception given as the message, an
  exception among the arguments (tuple items, mapping values) and the whole
  traceback chain of `exc_info`.
- **HTTP error replies.** Every `HTTPException` reply goes through
  `temper_ai/api/http_error_reply.py`, which withholds a database error's values
  from the detail when the error it was raised from (its cause or context) is
  one. Team refusals and MCP tool errors (`temper_ai/mcp/server.py`) do the same.
- **Slack, Telegram and other text sent out.** Run commands' error replies
  (`integrations/slack/ops.py`), the integrations' `last_error` shown on their
  status pages, inbox outcomes of GitHub and Linear deliveries
  (`api/hooks.py`), trigger decisions (`triggers/scheduler.py`) and the other
  sites that turn a caught error into text use the same safe text.

Not changed: errors temper stores in its own database (a run's or node's
`error`, an inbox event's or notify copy's failure detail, a trigger fire's
detail) keep the whole text, because they stay in temper's database.

## The database's own log

Postgres logs each error with its DETAIL, and the failing statement, which
carries literal values (psycopg2 writes the values into the SQL text). Two
settings stop that:

- `log_error_verbosity = terse` leaves out DETAIL, HINT and CONTEXT;
- `log_min_error_statement = panic` stops logging the statement of a failing one.

They are set in `docker-compose.yml` (the postgres service's `-c` flags), so a
recreated container keeps them, and were applied to the running database
without a restart:

```sh
docker exec temper-ai-postgres-1 psql -U temper_ai -d temper_ai -c "ALTER SYSTEM SET log_error_verbosity = 'terse'"
docker exec temper-ai-postgres-1 psql -U temper_ai -d temper_ai -c "ALTER SYSTEM SET log_min_error_statement = 'panic'"
docker exec temper-ai-postgres-1 psql -U temper_ai -d temper_ai -c "SELECT pg_reload_conf()"
```

Check with `SHOW log_error_verbosity` (terse) and `SHOW log_min_error_statement`
(panic).

**Undo.** Live: `ALTER SYSTEM RESET log_error_verbosity`,
`ALTER SYSTEM RESET log_min_error_statement`, then `SELECT pg_reload_conf()`.
Once the container has been recreated with the `-c` flags, those flags win over
`ALTER SYSTEM`: take them out of `docker-compose.yml` and recreate the container.

What stays: a data exception's primary message can still quote the value it
could not read in the database's log (`invalid input syntax ...: "..."`). Log
lines already written before the settings applied stay where they are until
the log rotates.
