"""Shared test fixtures."""

import pytest

from temper_ai.database import init_database, reset_database


@pytest.fixture(autouse=True)
def _test_db():
    """Initialize an in-memory SQLite database for each test."""
    reset_database()
    init_database("sqlite:///:memory:")
    yield
    reset_database()
