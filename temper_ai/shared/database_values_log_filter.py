"""A logging filter that keeps database values out of log lines.

Logging prints an exception's own text and its traceback, and on Postgres a
database error's text carries row values (shared/database_error_text.py). The
filter gives every record that carries a database error the safe text instead,
before a handler formats it:

* ``record.msg``, when the message is the exception itself;
* exceptions among ``record.args`` (tuple items, mapping values), in new args;
* the traceback of ``record.exc_info``, the whole chain, through ``record.exc_text``.

The exception objects are left as they are. A record the filter cannot render
loses its message and traceback rather than letting them through.

``install_database_values_log_filter`` puts the filter on every handler that
exists when it is called; each process calls it once its logging is set up
(temper_ai/server.py, temper_ai/cli/main.py). See docs/database-error-text.md.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TypeGuard

from temper_ai.shared.database_error_text import (
    carries_database_error,
    text_without_database_values,
    withhold_database_values,
)

# Formats a traceback the way logging.Formatter does when a handler has no formatter of its own.
_TRACEBACK = logging.Formatter()


class DatabaseValuesLogFilter(logging.Filter):
    """Gives a log record's database errors their safe text; passes every record on."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            _withhold_database_values(record)
        except Exception as failure:  # noqa: BLE001 - a log call must neither raise nor leak
            record.msg = f"log line withheld: its database error could not be rendered ({type(failure).__name__})"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def install_database_values_log_filter() -> None:
    """Put the filter on every handler that exists now: the root logger's and each named logger's.

    Call it once logging is set up: a handler added later does not get it, and
    ``logging.basicConfig(force=True)`` replaces the root's handlers (call it
    again after that). A handler that has the filter is not given a second one.
    """
    loggers = [logging.getLogger()] + [
        logger for logger in logging.Logger.manager.loggerDict.values() if isinstance(logger, logging.Logger)
    ]
    for logger in loggers:
        for handler in logger.handlers:
            if not any(isinstance(existing, DatabaseValuesLogFilter) for existing in handler.filters):
                handler.addFilter(DatabaseValuesLogFilter())


def _withhold_database_values(record: logging.LogRecord) -> None:
    if isinstance(record.msg, BaseException) and carries_database_error(record.msg):
        record.msg = text_without_database_values(record.msg)
    args = record.args
    if isinstance(args, tuple) and any(_carries(arg) for arg in args):
        record.args = tuple(_rendered(arg) for arg in args)
    elif isinstance(args, Mapping) and any(_carries(value) for value in args.values()):
        record.args = {key: _rendered(value) for key, value in args.items()}
    exc_info = record.exc_info
    exc = exc_info[1] if isinstance(exc_info, tuple) and len(exc_info) == 3 else None
    if isinstance(exc, BaseException) and carries_database_error(exc):
        # A handler before this one may have formatted it already (and another filter,
        # pi_agent/token_scan.py's, may have withheld from that text): keep its text.
        text = record.exc_text or _TRACEBACK.formatException(exc_info)  # type: ignore[arg-type]
        record.exc_text = withhold_database_values(text, exc)


def _carries(value: object) -> TypeGuard[BaseException]:
    return isinstance(value, BaseException) and carries_database_error(value)


def _rendered(value: object) -> object:
    return text_without_database_values(value) if _carries(value) else value
