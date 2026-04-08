"""Tests for database engine factory."""

import os

import pytest

from temper_ai.database.engine import create_app_engine, create_test_engine, get_database_url


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
