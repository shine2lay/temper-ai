"""Tests for temper_ai.storage.database.engine.

Tests engine creation helpers and configuration with mocked SQLAlchemy.
Avoids real database connections.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

from temper_ai.storage.database.engine import (
    DEFAULT_DATABASE_URL,
    PG_POOL_OVERFLOW_MULTIPLIER,
    TEMPER_DATABASE_URL_ENV,
    create_app_engine,
    create_test_engine,
    get_database_url,
)


class TestGetDatabaseUrl:
    """Tests for get_database_url()."""

    def test_returns_default_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv(TEMPER_DATABASE_URL_ENV, raising=False)
        result = get_database_url()
        assert result == DEFAULT_DATABASE_URL

    def test_returns_env_value_when_set(self, monkeypatch):
        custom_url = "postgresql://user:pass@host:5432/mydb"
        monkeypatch.setenv(TEMPER_DATABASE_URL_ENV, custom_url)
        result = get_database_url()
        assert result == custom_url

    def test_default_url_is_postgresql(self):
        assert DEFAULT_DATABASE_URL.startswith("postgresql://")

    def test_env_var_name_constant(self):
        assert TEMPER_DATABASE_URL_ENV == "TEMPER_DATABASE_URL"


class TestCreateAppEnginePg:
    """Tests for create_app_engine() with PostgreSQL URLs."""

    @patch("temper_ai.storage.database.engine.create_engine")
    def test_pg_engine_created_with_queue_pool(self, mock_create_engine, monkeypatch):
        monkeypatch.delenv(TEMPER_DATABASE_URL_ENV, raising=False)
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        result = create_app_engine("postgresql://u:p@localhost/db")

        mock_create_engine.assert_called_once()
        call_kwargs = mock_create_engine.call_args.kwargs
        assert call_kwargs["poolclass"] is QueuePool
        assert result is mock_engine

    @patch("temper_ai.storage.database.engine.create_engine")
    def test_pg_engine_uses_pool_pre_ping(self, mock_create_engine):
        mock_create_engine.return_value = MagicMock()

        create_app_engine("postgresql://u:p@localhost/db")

        call_kwargs = mock_create_engine.call_args.kwargs
        assert call_kwargs["pool_pre_ping"] is True

    @patch("temper_ai.storage.database.engine.create_engine")
    def test_pg_max_overflow_is_pool_size_times_multiplier(self, mock_create_engine):
        mock_create_engine.return_value = MagicMock()
        pool_size = 5

        create_app_engine("postgresql://u:p@localhost/db", pool_size=pool_size)

        call_kwargs = mock_create_engine.call_args.kwargs
        assert call_kwargs["max_overflow"] == pool_size * PG_POOL_OVERFLOW_MULTIPLIER
        assert call_kwargs["pool_size"] == pool_size

    @patch("temper_ai.storage.database.engine.create_engine")
    def test_pg_uses_url_from_env_when_none_given(
        self, mock_create_engine, monkeypatch
    ):
        pg_url = "postgresql://env:pass@host/dbenv"
        monkeypatch.setenv(TEMPER_DATABASE_URL_ENV, pg_url)
        mock_create_engine.return_value = MagicMock()

        create_app_engine()

        call_args = mock_create_engine.call_args
        assert call_args.args[0] == pg_url


class TestCreateAppEngineSqlite:
    """Tests for create_app_engine() with SQLite URLs (test mode only)."""

    def test_sqlite_in_test_env_succeeds(self):
        """SQLite is allowed when pytest is in sys.modules (which it is during tests)."""
        engine = create_app_engine("sqlite:///:memory:")
        assert engine is not None
        engine.dispose()

    def test_sqlite_raises_outside_pytest(self, monkeypatch):
        """SQLite must be rejected outside test environments."""
        import sys

        saved = sys.modules.pop("pytest", None)
        try:
            with pytest.raises(ValueError, match="SQLite is not supported"):
                create_app_engine("sqlite:///:memory:")
        finally:
            if saved is not None:
                sys.modules["pytest"] = saved

    def test_memory_sqlite_uses_static_pool(self):
        engine = create_app_engine("sqlite:///:memory:")
        assert isinstance(engine.pool, StaticPool)
        engine.dispose()

    def test_file_sqlite_uses_null_pool(self, tmp_path):
        db_path = tmp_path / "test.db"
        engine = create_app_engine(f"sqlite:///{db_path}")
        assert isinstance(engine.pool, NullPool)
        engine.dispose()


class TestCreateTestEngine:
    """Tests for create_test_engine()."""

    def test_returns_engine(self):
        engine = create_test_engine()
        assert engine is not None
        engine.dispose()

    def test_default_is_in_memory(self):
        engine = create_test_engine()
        assert isinstance(engine.pool, StaticPool)
        engine.dispose()

    def test_custom_url_accepted(self, tmp_path):
        db_path = tmp_path / "custom.db"
        engine = create_test_engine(f"sqlite:///{db_path}")
        assert engine is not None
        engine.dispose()


class TestPoolOverflowMultiplier:
    """Test module-level configuration constant."""

    def test_pg_pool_overflow_multiplier_is_positive(self):
        assert PG_POOL_OVERFLOW_MULTIPLIER > 0

    def test_pg_pool_overflow_multiplier_value(self):
        assert PG_POOL_OVERFLOW_MULTIPLIER == 2
