"""Database errors' row values stay out of log lines; the code that caught them keeps them.

The safe text (temper_ai/shared/database_error_text.py) and the log filter that
applies it (temper_ai/shared/database_values_log_filter.py); docs/database-error-text.md.
Every database error here is a real one, with a made-up marker in the failing row
(tests/test_database/made_up_database_errors.py).
"""

from __future__ import annotations

import io
import logging
import pickle
import threading
from dataclasses import dataclass

import psycopg2
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    PendingRollbackError,
    StatementError,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from temper_ai.database import get_database
from temper_ai.shared import database_values_log_filter
from temper_ai.shared.database_error_text import (
    WITHHELD,
    text_without_database_values,
    withhold_database_values,
)
from temper_ai.shared.database_values_log_filter import (
    DatabaseValuesLogFilter,
    install_database_values_log_filter,
)
from tests.test_database.made_up_database_errors import (
    CODES,
    FIRST_CODE,
    JOBS,
    MARKER,
    SAME_CODE,
    database_error,
    missing_name_error,
    on_postgres,
)

# The format temper_ai/server.py gives the root logger's handler.
SERVER_FORMAT = "%(levelname)s %(name)s: %(message)s"


def postgres_only() -> None:
    if not on_postgres():
        pytest.skip("the server's DETAIL, SQLSTATE and names are Postgres's; SQLite's errors are the other tests'")


def _every_handler() -> list[logging.Handler]:
    loggers = [logging.getLogger()] + [
        logger for logger in logging.Logger.manager.loggerDict.values() if isinstance(logger, logging.Logger)
    ]
    return [handler for logger in loggers for handler in logger.handlers]


@dataclass
class CapturedLog:
    log: logging.Logger
    stream: io.StringIO

    def output(self) -> str:
        return self.stream.getvalue()


@pytest.fixture
def server_log():
    """A logger whose handler is set up as the server's root handler (its format, a
    stream), with the filter installed as the server installs it. The installer reaches
    the test process's own handlers too, so every handler's filters are put back after."""
    kept = [(handler, list(handler.filters)) for handler in _every_handler()]
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(SERVER_FORMAT))
    log = logging.getLogger("tests.database_error_text")
    log.handlers = [handler]
    log.propagate = False
    log.setLevel(logging.DEBUG)
    install_database_values_log_filter()
    yield CapturedLog(log, stream)
    log.handlers = []
    for each, filters in kept:
        each.filters = filters


# -- the whole feature, as the server logs an error --------------------------------


def test_a_logged_database_error_shows_its_names_and_not_its_row(server_log):
    """A not-null failure whose row carries the marker, logged as the server logs it: with
    its traceback (the SQLAlchemy error and the driver's error it was raised from) and as a
    message argument. The line keeps what says what went wrong (SQLSTATE, the table and
    column) and loses the row, the statement and the parameters. The error itself is left
    as it was: code inside temper still reads the whole of it."""
    err = missing_name_error()
    own_text = str(err)
    assert MARKER in own_text

    server_log.log.error("could not store the job: %s", err, exc_info=err)

    shown = server_log.output()
    assert MARKER not in shown
    assert "[SQL:" not in shown and "[parameters:" not in shown
    assert shown.startswith("ERROR tests.database_error_text: could not store the job: (")
    assert "Traceback (most recent call last)" in shown
    assert "The above exception was the direct cause of the following exception" in shown
    if on_postgres():
        message = 'null value in column "name" of relation "jobs248" violates not-null constraint'
        assert f"\npsycopg2.errors.NotNullViolation: {message} (SQLSTATE 23502," in shown
        assert f"\nsqlalchemy.exc.IntegrityError: (psycopg2.errors.NotNullViolation) {message}" in shown
        assert "table=jobs248, column=name)" in shown
    else:
        assert "\nsqlite3.IntegrityError: NOT NULL constraint failed: jobs248.name" in shown
        assert "\nsqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) NOT NULL constraint failed: jobs248.name" in shown
    assert str(err) == own_text


# -- the edges ----------------------------------------------------------------------


def test_a_unique_violation_shows_its_constraint_and_not_its_key(server_log):
    err = database_error([CODES, FIRST_CODE], SAME_CODE, code=MARKER)

    server_log.log.warning("could not add the code: %s", err)

    shown = server_log.output()
    assert MARKER not in shown
    if on_postgres():
        assert 'duplicate key value violates unique constraint "uq_codes248_code"' in shown
        assert "SQLSTATE 23505" in shown and "constraint=uq_codes248_code" in shown
    else:
        assert "(sqlite3.IntegrityError) UNIQUE constraint failed: codes248.code" in shown


def test_a_foreign_key_violation_shows_its_constraint_and_not_its_key(server_log):
    postgres_only()
    err = database_error(
        [
            "CREATE TEMP TABLE owners248 (id text PRIMARY KEY)",
            "CREATE TEMP TABLE pets248 (id integer PRIMARY KEY, "
            "owner text CONSTRAINT fk_pets248_owner REFERENCES owners248 (id))",
        ],
        "INSERT INTO pets248 (id, owner) VALUES (1, :owner)",
        owner=MARKER,
    )
    assert MARKER in err.orig.diag.message_detail

    server_log.log.error("could not add the pet", exc_info=err)

    shown = server_log.output()
    assert MARKER not in shown
    assert 'insert or update on table "pets248" violates foreign key constraint "fk_pets248_owner"' in shown
    assert "SQLSTATE 23503" in shown and "table=pets248" in shown and "constraint=fk_pets248_owner" in shown


def test_a_data_exception_withholds_the_value_its_message_quotes(server_log):
    """22P02's own message, not only its DETAIL, quotes the input it could not read."""
    postgres_only()
    err = database_error([], "SELECT CAST(:v AS integer)", v=MARKER)
    assert MARKER in err.orig.diag.message_primary

    server_log.log.error("%s", err, exc_info=err)

    shown = server_log.output()
    assert MARKER not in shown
    assert f'invalid input syntax for type integer: "{WITHHELD}" (SQLSTATE 22P02)' in shown


def test_bytes_the_server_could_not_read_are_withheld():
    postgres_only()
    err = database_error([], "SELECT convert_from(:b, 'UTF8')", b=MARKER.encode() + b"\xff")
    assert "0xff" in err.orig.diag.message_primary

    rendered = text_without_database_values(err)

    assert "0xff" not in rendered and MARKER.encode().hex() not in rendered
    assert rendered.startswith("(psycopg2.errors.CharacterNotInRepertoire) invalid byte sequence for encoding")
    assert rendered.endswith(f": {WITHHELD} (SQLSTATE 22021)")


def test_an_error_raised_from_a_database_error_has_its_whole_chain_rendered(server_log):
    """The wrapper's own text quotes the database error; its traceback shows the SQLAlchemy
    error and the driver's error under it. All three are rendered."""
    err = missing_name_error()
    try:
        try:
            raise err
        except IntegrityError as caught:
            raise RuntimeError(f"storing the job failed: {caught}") from caught
    except RuntimeError as wrapper:
        server_log.log.error("job store", exc_info=wrapper)

    shown = server_log.output()
    assert MARKER not in shown
    assert shown.count("The above exception was the direct cause of the following exception") == 2
    assert "\nRuntimeError: storing the job failed: (" in shown
    assert "\nsqlalchemy.exc.IntegrityError: (" in shown
    driver = "psycopg2.errors.NotNullViolation: null value" if on_postgres() else "sqlite3.IntegrityError: NOT NULL"
    assert f"\n{driver}" in shown


def test_an_error_raised_while_handling_a_database_error_has_it_rendered(server_log):
    err = missing_name_error()
    try:
        try:
            raise err
        except IntegrityError:
            raise KeyError("the job's owner")  # noqa: B904 - the context is the point
    except KeyError as later:
        server_log.log.error("lookup failed", exc_info=later)

    shown = server_log.output()
    assert MARKER not in shown
    assert "During handling of the above exception, another exception occurred" in shown


def test_a_message_that_quotes_a_suppressed_database_error_is_rendered(server_log):
    """``raise ... from None`` hides the database error from the traceback, not from the
    wrapper's own text."""
    err = missing_name_error()
    try:
        try:
            raise err
        except IntegrityError as caught:
            raise RuntimeError(f"storing the job failed: {caught}") from None
    except RuntimeError as wrapper:
        server_log.log.error("%s", wrapper)

    shown = server_log.output()
    assert MARKER not in shown
    assert "storing the job failed: (" in shown


def test_an_exception_group_has_its_members_rendered(server_log):
    err = missing_name_error()
    group = ExceptionGroup("two stores failed", [err, ValueError("unrelated")])

    server_log.log.error("stores", exc_info=group)

    shown = server_log.output()
    assert MARKER not in shown
    assert "two stores failed (2 sub-exceptions)" in shown and "ValueError: unrelated" in shown


def test_a_chain_that_loops_back_on_itself_is_rendered_once():
    err = missing_name_error()
    first, second = RuntimeError("first"), RuntimeError(f"second: {err}")
    first.__context__, second.__context__, second.__cause__ = second, first, err
    rendered: list[str] = []

    worker = threading.Thread(target=lambda: rendered.append(text_without_database_values(second)), daemon=True)
    worker.start()
    worker.join(10)

    assert len(rendered) == 1
    assert MARKER not in rendered[0] and rendered[0].startswith("second: (")


def test_a_copied_sqlalchemy_error_still_has_its_driver_error_rendered():
    """A copy across a process boundary (pickle) keeps ``orig`` but loses ``__cause__``."""
    copy = pickle.loads(pickle.dumps(missing_name_error()))
    assert copy.__cause__ is None and copy.orig is not None

    shown = withhold_database_values(f"lost a job: {copy.orig}", copy)

    assert MARKER not in shown and shown.startswith("lost a job: ")


def test_a_database_error_quoted_inside_another_object_is_rendered():
    """A container's text shows the error's text escaped, as repr does (``\\n``)."""
    err = missing_name_error()
    wrapper = ValueError(f"store refused these: {[str(err)]}")
    wrapper.__cause__ = err

    rendered = text_without_database_values(wrapper)

    assert MARKER not in rendered
    assert rendered.startswith("store refused these: [")


def test_the_servers_detail_quoted_on_its_own_is_withheld():
    postgres_only()
    err = missing_name_error()
    detail = err.orig.diag.message_detail
    assert MARKER in detail
    wrapper = RuntimeError(f"the row: {detail}")
    wrapper.__cause__ = err

    assert text_without_database_values(wrapper) == f"the row: {WITHHELD}"


def test_the_drivers_own_error_gets_the_safe_text():
    """Code that talks to psycopg2 directly gets the driver's error without SQLAlchemy's."""
    postgres_only()
    raw = get_database().engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute(JOBS)
        with pytest.raises(psycopg2.Error) as raised:
            cursor.execute("INSERT INTO jobs248 (id, note, name) VALUES (1, %s, NULL)", (MARKER,))
    finally:
        raw.rollback()
        raw.close()
    assert MARKER in str(raised.value)

    rendered = text_without_database_values(raised.value)

    assert MARKER not in rendered
    assert rendered.startswith('null value in column "name" of relation "jobs248" violates not-null constraint')
    assert "(SQLSTATE 23502, schema=pg_temp" in rendered and "table=jobs248, column=name)" in rendered


def test_a_driver_error_that_never_reached_the_server_keeps_only_its_first_line():
    """A psycopg2 error made on the client has no server fields to go by."""
    err = psycopg2.errors.UniqueViolation(f'duplicate key value "{MARKER}"\nDETAIL:  Key (code)=({MARKER}) already exists.')

    assert text_without_database_values(err) == f'duplicate key value "{WITHHELD}"'


def test_a_sqlite_error_keeps_its_message_and_withholds_what_it_quotes(server_log):
    """SQLite names tables and columns, not values; a syntax error quotes the token it
    stopped at, which can be a literal."""
    sqlite = create_engine("sqlite://")
    try:
        with sqlite.connect() as conn:
            conn.execute(text(CODES))
            conn.execute(text(FIRST_CODE), {"code": MARKER})
            with pytest.raises(IntegrityError) as unique:
                conn.execute(text(SAME_CODE), {"code": MARKER})
            with pytest.raises(DBAPIError) as syntax:
                conn.execute(text(f"SELECT id FROM codes248 WHERE code = '{MARKER}' '{MARKER}'"))
    finally:
        sqlite.dispose()

    assert text_without_database_values(unique.value) == "(sqlite3.IntegrityError) UNIQUE constraint failed: codes248.code"
    assert text_without_database_values(syntax.value) == f'(sqlite3.OperationalError) near "{WITHHELD}": syntax error'
    server_log.log.error("could not read it", exc_info=syntax.value)
    assert MARKER not in server_log.output()


class OtherDriverError(Exception):
    """An error of a driver the safe text knows nothing about."""


def test_an_unknown_drivers_error_keeps_its_first_line_with_quotes_withheld():
    err = DBAPIError("SELECT :v", {"v": MARKER}, OtherDriverError(f'bad value "{MARKER}"\nrow: ({MARKER})'))

    rendered = text_without_database_values(err)

    assert rendered == f'({OtherDriverError.__module__}.OtherDriverError) bad value "{WITHHELD}"'


def test_sqlalchemys_own_statement_errors_drop_the_statement_and_parameters():
    """No driver error: SQLAlchemy's words, first line. A bind parameter's own failure is
    temper's error, left as it is (its traceback shows it anyway), without the statement."""
    no_driver = StatementError("could not run it", f"SELECT '{MARKER}'", {"v": MARKER}, None)
    bind = StatementError("(builtins.TypeError) not a date", "INSERT INTO t VALUES (:v)", {"v": MARKER},
                          TypeError('"when" is not a date'))
    assert MARKER in str(no_driver) and MARKER in str(bind)

    assert text_without_database_values(no_driver) == "could not run it"
    assert text_without_database_values(bind) == '(builtins.TypeError) "when" is not a date'


class _Base(DeclarativeBase):
    pass


class _Code(_Base):
    """A temporary table of its own: the session's flush is what fails."""

    __tablename__ = "orm_codes248"
    __table_args__ = {"prefixes": ["TEMPORARY"]}
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)


def test_a_session_used_after_a_failed_flush_quotes_only_the_first_line(server_log):
    """SQLAlchemy's 'rolled back due to a previous exception' quotes that whole earlier
    error, and keeps no link to it."""
    with get_database().engine.connect() as conn:
        _Base.metadata.create_all(conn)
        with Session(bind=conn) as session:
            session.add(_Code(id=1, code=MARKER))
            session.flush()
            session.add(_Code(id=2, code=MARKER))
            with pytest.raises(IntegrityError):
                session.flush()
            with pytest.raises(PendingRollbackError) as raised:
                session.execute(select(_Code))
        conn.rollback()
    err = raised.value
    assert (MARKER if on_postgres() else "[SQL:") in str(err) and err.__cause__ is None

    server_log.log.error("the session is gone: %s", err, exc_info=err)

    shown = server_log.output()
    assert MARKER not in shown and "[SQL:" not in shown
    assert "Original exception was: (" in shown


def test_an_exception_whose_text_cannot_be_read_still_gets_a_line():
    class UnreadableError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("no text")

    assert text_without_database_values(UnreadableError()) == "<UnreadableError: its text could not be read>"


# -- the filter ---------------------------------------------------------------------


def test_a_database_error_given_as_the_message_is_rendered(server_log):
    err = missing_name_error()

    server_log.log.error(err)

    shown = server_log.output()
    assert MARKER not in shown
    assert shown.startswith("ERROR tests.database_error_text: (")


def test_a_database_error_among_mapping_arguments_is_rendered(server_log):
    err = missing_name_error()

    server_log.log.error("%(what)s failed: %(err)s", {"what": "the job", "err": err})

    shown = server_log.output()
    assert MARKER not in shown
    assert "the job failed: (" in shown


def test_a_record_without_a_database_error_is_left_as_it_is(server_log):
    plain = ValueError(f"bad value {MARKER}")
    args = ("the job", plain)
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "%s: %s", args, (ValueError, plain, None))

    assert DatabaseValuesLogFilter().filter(record) is True

    assert record.msg == "%s: %s" and record.args is args and record.exc_text is None
    server_log.log.error("%s", plain, exc_info=plain)
    assert server_log.output().count(MARKER) == 2


def test_a_traceback_an_earlier_handler_wrote_keeps_its_edits():
    """Another filter (pi_agent/token_scan.py's) may have edited the traceback already."""
    err = missing_name_error()
    exc_info = (type(err), err, err.__traceback__)
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", (), exc_info)
    record.exc_text = "EARLIER EDIT\n" + logging.Formatter().formatException(exc_info)
    assert MARKER in record.exc_text

    DatabaseValuesLogFilter().filter(record)

    assert record.exc_text.startswith("EARLIER EDIT\nTraceback")
    assert MARKER not in record.exc_text


def test_a_record_the_filter_cannot_render_is_withheld_whole(server_log, monkeypatch):
    def broken(_exc: BaseException) -> str:
        raise RuntimeError("cannot render")

    monkeypatch.setattr(database_values_log_filter, "text_without_database_values", broken)
    err = missing_name_error()

    server_log.log.error("could not store the job: %s", err, exc_info=err)

    shown = server_log.output()
    assert MARKER not in shown
    assert shown == (
        "ERROR tests.database_error_text: log line withheld: its database error could not be rendered (RuntimeError)\n"
    )


def test_the_installer_puts_one_filter_on_each_handler(server_log):
    """On every handler of every logger, once however often it is called."""
    log = logging.getLogger("tests.database_error_text.two_handlers")
    first, second = logging.StreamHandler(io.StringIO()), logging.StreamHandler(io.StringIO())
    log.handlers = [first, second]
    try:
        install_database_values_log_filter()
        install_database_values_log_filter()

        for handler in (first, second, *server_log.log.handlers):
            assert sum(isinstance(each, DatabaseValuesLogFilter) for each in handler.filters) == 1
    finally:
        log.handlers = []
