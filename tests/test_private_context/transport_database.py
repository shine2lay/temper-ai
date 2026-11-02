"""C2 test dialect fixture; pgtier guards against any production database."""
from contextlib import contextmanager

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from temper_ai.api.guard_models import RunPrivateKey
from temper_ai.database.private_worker_schema import create_private_worker_key_table
from temper_ai.runner.models import WorkflowRun
from tests.pgtier import database_tier_url


@pytest.fixture
def transport_database(monkeypatch):
    from temper_ai import database

    url = database_tier_url()
    engine = create_engine(url) if url else create_engine("sqlite://", poolclass=StaticPool,
                                                          connect_args={"check_same_thread": False})
    WorkflowRun.__table__.create(engine, checkfirst=True)
    create_private_worker_key_table(engine)
    with engine.begin() as connection:
        connection.execute(RunPrivateKey.__table__.delete())
        connection.execute(WorkflowRun.__table__.delete())

    @contextmanager
    def sessions():
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(database, "get_session", sessions)
    # Modules that explicitly import get_session must share the caller transaction fixture.
    from temper_ai.api import private_workers
    monkeypatch.setattr(private_workers, "get_session", sessions)
    try:
        yield engine, sessions
    finally:
        engine.dispose()
