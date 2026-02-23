"""Shared database fixtures for testing."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel


@pytest.fixture
def db_session():
    """In-memory SQLite session for database tests."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def clean_db_session(db_session):
    """Session that's rolled back after test."""
    yield db_session
    db_session.rollback()


@pytest.fixture
def db_with_experiments(db_session):
    """Session with sample experiments preloaded."""
    from tests.test_experimentation.conftest import create_experiment

    exp1 = create_experiment(name="test_exp_1")
    exp2 = create_experiment(name="test_exp_2")
    db_session.add_all([exp1, exp2])
    db_session.commit()
    yield db_session
