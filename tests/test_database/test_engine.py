"""Tests for database engine factory."""

import os

import pytest
from sqlalchemy import exc, text
from sqlalchemy.engine import make_url

from temper_ai.database.engine import (
    create_app_engine,
    create_test_engine,
    get_database_url,
    with_psycopg2_driver,
)
from tests import pgtier

# A long bound value: SQLAlchemy's error text would show its start and its end.
MARKER = "HIDE-HEAD-" + "x" * 2000 + "-HIDE-TAIL"


def failed_statement_text(engine) -> str:
    """The error text of a statement that fails for a reason other than its value.

    The table doesn't exist, so the database's own message can't carry the
    marker; only SQLAlchemy's rendering of the bound parameters could.
    """
    with pytest.raises(exc.StatementError) as caught:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO no_such_table_hide_parameters (x) VALUES (:x)"), {"x": MARKER})
    return str(caught.value)


def assert_values_hidden(message: str) -> None:
    assert "HIDE-HEAD" not in message
    assert "HIDE-TAIL" not in message
    assert "hide_parameters=True" in message


def test_bare_postgres_urls_choose_our_driver_and_preserve_connection_fields():
    """Combined happy path: both spellings, both representations, real factories.

    Constructing an engine imports the actual DBAPI but makes no connection.
    """
    from temper_ai.runner.pi_lane import status_engine
    from tests.test_runner.pi_team.race_child import _engine

    suffix = "u:p%40ss@db.invalid:5455/temper_test?sslmode=require&application_name=probe"
    for scheme in ("postgresql", "postgres"):
        raw = f"{scheme}://{suffix}"
        parsed = make_url(raw)
        normalized = with_psycopg2_driver(parsed)
        assert normalized == parsed.set(drivername="postgresql+psycopg2")
        assert normalized.password == "p@ss"
        assert with_psycopg2_driver(raw) == f"postgresql+psycopg2://{suffix}"
        for factory in (create_app_engine, status_engine, _engine):
            engine = factory(raw)
            try:
                assert engine.url == normalized
                assert engine.dialect.driver == "psycopg2"
                if factory is create_app_engine:
                    assert engine.hide_parameters is True
            finally:
                engine.dispose()


@pytest.mark.parametrize("raw", [
    "postgresql+psycopg2://u:p@db.invalid/test",
    "postgresql+psycopg://u:p@db.invalid/test",
    "postgresql+asyncpg://u:p@db.invalid/test",
    "sqlite:///:memory:", "mysql+pymysql://u:p@db.invalid/test",
])
def test_explicit_drivers_and_other_databases_are_untouched(raw):
    assert with_psycopg2_driver(raw) is raw
    parsed = make_url(raw)
    assert with_psycopg2_driver(parsed) is parsed


class TestGetDatabaseUrl:
    def test_returns_env_var(self):
        os.environ["TEMPER_DATABASE_URL"] = "sqlite:///test.db"
        try:
            assert get_database_url() == "sqlite:///test.db"
        finally:
            del os.environ["TEMPER_DATABASE_URL"]

    def test_returns_default_when_unset(self):
        old = os.environ.pop("TEMPER_DATABASE_URL", None)
        try:
            url = get_database_url()
            assert "postgresql" in url
        finally:
            if old:
                os.environ["TEMPER_DATABASE_URL"] = old


class TestCreateAppEngine:
    def test_creates_sqlite_engine(self):
        engine = create_app_engine("sqlite:///:memory:")
        assert engine is not None
        assert "sqlite" in str(engine.url)

    def test_creates_sqlite_file_engine(self, tmp_path):
        db_path = tmp_path / "test.db"
        engine = create_app_engine(f"sqlite:///{db_path}")
        assert engine is not None


class TestCreateTestEngine:
    def test_creates_memory_engine(self):
        engine = create_test_engine()
        assert engine is not None
        assert "memory" in str(engine.url)

    def test_creates_custom_url_engine(self, tmp_path):
        db_path = tmp_path / "test.db"
        engine = create_test_engine(f"sqlite:///{db_path}")
        assert engine is not None


class TestErrorTextHidesBoundValues:
    """A failed statement's error text, which the server logs, never carries a run's inputs."""

    def test_sqlite_error_text_hides_bound_values(self):
        engine = create_test_engine()
        try:
            assert_values_hidden(failed_statement_text(engine))
        finally:
            engine.dispose()

    def test_postgres_error_text_hides_bound_values(self):
        url = pgtier.database_tier_url()
        if url is None:
            pytest.skip("the tier is off")
        engine = create_app_engine(url)
        try:
            assert_values_hidden(failed_statement_text(engine))
        finally:
            engine.dispose()
