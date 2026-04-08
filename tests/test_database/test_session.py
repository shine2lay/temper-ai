"""Tests for database session management."""

import pytest

from temper_ai.database.session import (
    init_database, get_database, get_session, reset_database,
)


class TestDatabaseInit:
    def setup_method(self):
        reset_database()

    def teardown_method(self):
        reset_database()

    def test_init_database_returns_manager(self):
        mgr = init_database("sqlite:///:memory:")
        assert mgr is not None

    def test_get_database_after_init(self):
        init_database("sqlite:///:memory:")
        mgr = get_database()
        assert mgr is not None

    def test_get_database_before_init_raises(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_database()

    def test_get_session_works(self):
        from sqlalchemy import text
        init_database("sqlite:///:memory:")
        with get_session() as session:
            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1

    def test_idempotent_init(self):
        mgr1 = init_database("sqlite:///:memory:")
        mgr2 = init_database("sqlite:///:memory:")
        assert mgr1 is mgr2
