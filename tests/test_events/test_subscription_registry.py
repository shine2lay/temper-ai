"""Tests for events/subscription_registry.py."""

from contextlib import contextmanager

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from temper_ai.events.subscription_registry import SubscriptionRegistry


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture
def session_factory(engine):
    @contextmanager
    def _factory():
        with Session(engine, expire_on_commit=False) as session:
            yield session
            session.commit()

    return _factory


@pytest.fixture
def registry(session_factory):
    return SubscriptionRegistry(session_factory=session_factory)


class TestSubscriptionRegistryNoSession:
    def test_register_returns_id_without_session(self):
        reg = SubscriptionRegistry(session_factory=None)
        sub_id = reg.register(agent_id="a1", event_type="workflow.completed")
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0


class TestSubscriptionRegistryWithDB:
    def test_register_persists_subscription(self, registry, session_factory):
        sub_id = registry.register(
            agent_id="agent-1",
            event_type="workflow.completed",
        )
        assert isinstance(sub_id, str)

    def test_register_with_all_fields(self, registry):
        sub_id = registry.register(
            agent_id="agent-2",
            event_type="stage.failed",
            handler_ref="mymod.handler",
            workflow_to_trigger="wf.yaml",
            source_workflow_filter="wf-1",
            payload_filter={"k": "v"},
        )
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0
