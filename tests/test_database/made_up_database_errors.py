"""Real database errors with a made-up marker in the failing row, for the tests of the
database-values safe text (docs/database-error-text.md).

Each comes from a temporary table on the test's own database (Postgres in the database
tier, SQLite otherwise), in one transaction that is then rolled back. On Postgres the
marker reaches the server's DETAIL and the statement; on SQLite, SQLAlchemy's statement
and parameters.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from temper_ai.database import get_database

MARKER = "zq7-made-up-marker"

JOBS = "CREATE TEMP TABLE jobs248 (id integer PRIMARY KEY, note text, name text NOT NULL)"
JOB_WITHOUT_NAME = "INSERT INTO jobs248 (id, note, name) VALUES (1, :note, NULL)"
CODES = "CREATE TEMP TABLE codes248 (id integer PRIMARY KEY, code text, CONSTRAINT uq_codes248_code UNIQUE (code))"
FIRST_CODE = "INSERT INTO codes248 (id, code) VALUES (1, :code)"
SAME_CODE = "INSERT INTO codes248 (id, code) VALUES (2, :code)"


def on_postgres() -> bool:
    return get_database().engine.dialect.name == "postgresql"


def database_error(setup: list[str], failing: str, **params: object) -> DBAPIError:
    """The error ``failing`` raises on the test's database after ``setup``."""
    with get_database().engine.connect() as conn:
        for statement in setup:
            conn.execute(text(statement), params)
        with pytest.raises(DBAPIError) as raised:
            conn.execute(text(failing), params)
        conn.rollback()
    return raised.value


def missing_name_error() -> DBAPIError:
    """A not-null failure whose row carries the marker. On Postgres the bound value reaches
    the server's DETAIL even with hide_parameters=True; on SQLite (which has no DETAIL) a
    literal in the statement reaches SQLAlchemy's [SQL: ...] line."""
    if on_postgres():
        return database_error([JOBS], JOB_WITHOUT_NAME, note=MARKER)
    return database_error([JOBS], f"INSERT INTO jobs248 (id, note, name) VALUES (1, '{MARKER}', NULL)")
