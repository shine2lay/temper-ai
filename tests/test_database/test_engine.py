"""Tests for database engine factory."""

import os

import pytest
from sqlalchemy import exc, text

from temper_ai.database.engine import (
    create_app_engine,
    create_test_engine,
    get_database_url,
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
