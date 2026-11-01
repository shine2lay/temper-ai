"""Every process temper runs puts the database-values filter on every log handler it has.

The server (uvicorn imports temper_ai.server after it set up its own handlers) and the
CLI's entry points: run-workflow (a run's box), watch-queue (the worker and the Pi
worker, whose force=True setup replaces the root's handler) and their --debug forms.
Each case runs the real entry point in a fresh interpreter, stops it where its command
would start, and logs a database error whose parameters carry a made-up marker. The
server also answers every HTTPException through api/http_error_reply.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

MARKER = "zq7-made-up-marker"

REPORT = textwrap.dedent(f"""
    import json, logging, sqlite3, sys
    from sqlalchemy.exc import DBAPIError
    from temper_ai.shared.database_values_log_filter import DatabaseValuesLogFilter

    def report(*log_through):
        handlers = {{}}
        loggers = [("", logging.getLogger())] + sorted(
            (name, each) for name, each in logging.Logger.manager.loggerDict.items()
            if isinstance(each, logging.Logger))
        for name, each in loggers:
            for handler in each.handlers:
                handlers.setdefault(name, []).append(
                    sum(isinstance(f, DatabaseValuesLogFilter) for f in handler.filters))
        err = DBAPIError("INSERT INTO jobs (note) VALUES (?)", ({MARKER!r},),
                         sqlite3.IntegrityError("NOT NULL constraint failed: jobs.name"))
        for name in log_through:
            logging.getLogger(name).error("could not store the job: %s", err, exc_info=err)
        sys.stdout.write("REPORT " + json.dumps(handlers) + "\\n")
        sys.stdout.flush()
        return 0
""")

SERVER = REPORT + textwrap.dedent("""
    import uvicorn
    from starlette.exceptions import HTTPException
    uvicorn.Config("temper_ai.server:app").load()
    from temper_ai.server import app
    answer = app.exception_handlers[HTTPException]
    sys.stdout.write(f"HTTP_ERRORS {answer.__module__}.{answer.__qualname__}\\n")
    sys.exit(report("temper_ai.server", "uvicorn.error"))
""")


def cli(module: str, command: str, *argv: str) -> str:
    """The CLI's main() for ``argv``, with ``command`` of ``module`` swapped for the report."""
    return REPORT + textwrap.dedent(f"""
        import {module} as entry
        entry.{command} = lambda args: report("temper_ai.cli.main")
        sys.argv = ["temper", *{list(argv)!r}]
        from temper_ai.cli.main import main
        main()
    """)


def run(script: str, tmp_path) -> tuple[dict[str, list[int]], str]:
    env = {key: value for key, value in os.environ.items()
           if key not in ("TEMPER_SERVER_URL", "TEMPER_UI_URL", "TEMPER_API_TOKEN")}
    done = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=90, check=False)
    code = done.returncode
    assert code == 0
    output = done.stdout + done.stderr
    reports = [line for line in done.stdout.splitlines() if line.startswith("REPORT ")]
    count = len(reports)
    assert count == 1
    return json.loads(reports[0].removeprefix("REPORT ")), output


RUN_WORKFLOW = ("temper_ai.cli.run_workflow", "cmd_run_workflow", "run-workflow", "--execution-id", "made-up")
WATCH_QUEUE = ("temper_ai.cli.watch_queue", "cmd_watch_queue", "watch-queue")


def test_the_servers_handlers_and_uvicorns_all_carry_the_filter(tmp_path):
    handlers, output = run(SERVER, tmp_path)

    # Every HTTPException is answered with database values withheld (api/http_error_reply.py).
    assert "HTTP_ERRORS temper_ai.api.http_error_reply.http_error_without_database_values\n" in output
    assert {"", "uvicorn", "uvicorn.access"} <= set(handlers)
    assert all(counts == [1] * len(counts) for counts in handlers.values()), handlers
    assert MARKER not in output
    assert output.count("could not store the job: (sqlite3.IntegrityError) NOT NULL constraint failed: jobs.name") == 2


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(RUN_WORKFLOW, id="run-workflow"),
        pytest.param((*RUN_WORKFLOW, "--debug"), id="run-workflow --debug"),
        pytest.param(WATCH_QUEUE, id="watch-queue"),
        pytest.param((*WATCH_QUEUE, "--debug"), id="watch-queue --debug"),
    ],
)
def test_the_clis_handlers_carry_the_filter(entry, tmp_path):
    module, command, *argv = entry

    handlers, output = run(cli(module, command, *argv), tmp_path)

    assert "" in handlers
    assert all(counts == [1] * len(counts) for counts in handlers.values()), handlers
    assert MARKER not in output
    assert "could not store the job: (sqlite3.IntegrityError) NOT NULL constraint failed: jobs.name" in output
