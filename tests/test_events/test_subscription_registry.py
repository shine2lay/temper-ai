"""Tests for events/subscription_registry.py."""

import uuid
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

    def test_unregister_without_session_returns_false(self):
        reg = SubscriptionRegistry(session_factory=None)
        result = reg.unregister(str(uuid.uuid4()))
        assert result is False

    def test_get_for_event_returns_empty(self):
        reg = SubscriptionRegistry(session_factory=None)
        result = reg.get_for_event("workflow.completed")
        assert result == []

    def test_load_active_returns_empty(self):
        reg = SubscriptionRegistry(session_factory=None)
        result = reg.load_active()
        assert result == []

    def test_get_by_id_returns_none(self):
        reg = SubscriptionRegistry(session_factory=None)
        result = reg.get_by_id(str(uuid.uuid4()))
        assert result is None


class TestSubscriptionRegistryWithDB:
    def test_register_persists_subscription(self, registry, session_factory):
        sub_id = registry.register(
            agent_id="agent-1",
            event_type="workflow.completed",
        )
        assert isinstance(sub_id, str)

        subs = registry.load_active()
        ids = [s.id for s in subs]
        assert sub_id in ids

    def test_register_with_all_fields(self, registry):
        sub_id = registry.register(
            agent_id="agent-2",
            event_type="stage.failed",
            handler_ref="mymod.handler",
            workflow_to_trigger="wf.yaml",
            source_workflow_filter="wf-1",
            payload_filter={"k": "v"},
        )
        sub = registry.get_by_id(sub_id)
        assert sub is not None
        assert sub.handler_ref == "mymod.handler"
        assert sub.workflow_to_trigger == "wf.yaml"
        assert sub.source_workflow_filter == "wf-1"
        assert sub.payload_filter == {"k": "v"}

    def test_unregister_deactivates(self, registry):
        sub_id = registry.register(agent_id="a", event_type="agent.completed")
        result = registry.unregister(sub_id)
        assert result is True

        sub = registry.get_by_id(sub_id)
        assert sub.active is False

    def test_unregister_nonexistent_returns_false(self, registry):
        result = registry.unregister(str(uuid.uuid4()))
        assert result is False

    def test_get_for_event_returns_matching(self, registry):
        registry.register(agent_id="a", event_type="workflow.completed")
        registry.register(agent_id="b", event_type="stage.completed")

        results = registry.get_for_event("workflow.completed")
        assert len(results) >= 1
        assert all(s.event_type == "workflow.completed" for s in results)

    def test_get_for_event_excludes_inactive(self, registry):
        sub_id = registry.register(agent_id="a", event_type="workflow.started")
        registry.unregister(sub_id)

        results = registry.get_for_event("workflow.started")
        assert all(s.id != sub_id for s in results)

    def test_load_active_returns_all_active(self, registry):
        id1 = registry.register(agent_id="a", event_type="evt1")
        id2 = registry.register(agent_id="b", event_type="evt2")
        registry.unregister(id1)

        active = registry.load_active()
        active_ids = [s.id for s in active]
        assert id1 not in active_ids
        assert id2 in active_ids

    def test_get_by_id_returns_subscription(self, registry):
        sub_id = registry.register(agent_id="x", event_type="custom")
        sub = registry.get_by_id(sub_id)
        assert sub is not None
        assert sub.id == sub_id
        assert sub.event_type == "custom"
