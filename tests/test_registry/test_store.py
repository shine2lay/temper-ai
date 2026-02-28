"""Tests for temper_ai.registry.store using in-memory SQLite."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel

from temper_ai.registry._schemas import AgentRegistryEntry
from temper_ai.registry.constants import (
    STATUS_ACTIVE,
    STATUS_INACTIVE,
    STATUS_REGISTERED,
)
from temper_ai.registry.store import AgentRegistryStore
from temper_ai.storage.database.engine import create_test_engine
from temper_ai.storage.database.models_registry import (
    AgentRegistryDB,  # noqa: F401 — registers table
)


def _make_entry(name: str = "test-agent", **kwargs) -> AgentRegistryEntry:
    defaults = {
        "id": f"id-{name}",
        "name": name,
        "registered_at": datetime.now(UTC),
        "config_snapshot": {"name": name},
    }
    defaults.update(kwargs)
    return AgentRegistryEntry(**defaults)


def _make_store() -> AgentRegistryStore:
    """Create an in-memory SQLite store for testing."""
    engine = create_test_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    @contextmanager
    def session_factory() -> Generator[Session, None, None]:
        session = Session(engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return AgentRegistryStore(session_factory=session_factory)


class TestAgentRegistryStoreRegister:
    def test_register_returns_id(self):
        store = _make_store()
        entry = _make_entry()
        returned_id = store.register(entry)
        assert returned_id == entry.id

    def test_register_then_get(self):
        store = _make_store()
        entry = _make_entry(name="alpha")
        store.register(entry)
        found = store.get("alpha")
        assert found is not None
        assert found.name == "alpha"

    def test_registered_status(self):
        store = _make_store()
        store.register(_make_entry())
        found = store.get("test-agent")
        assert found.status == STATUS_REGISTERED


class TestAgentRegistryStoreGet:
    def test_get_missing_returns_none(self):
        store = _make_store()
        assert store.get("nonexistent") is None

    def test_get_by_id(self):
        store = _make_store()
        entry = _make_entry(id="myid123")
        store.register(entry)
        found = store.get_by_id("myid123")
        assert found is not None
        assert found.id == "myid123"

    def test_get_by_id_missing_returns_none(self):
        store = _make_store()
        assert store.get_by_id("does-not-exist") is None


class TestAgentRegistryStoreListAll:
    def test_list_all_empty(self):
        store = _make_store()
        assert store.list_all() == []

    def test_list_all_returns_all(self):
        store = _make_store()
        store.register(_make_entry(name="a", id="id-a"))
        store.register(_make_entry(name="b", id="id-b"))
        results = store.list_all()
        assert len(results) == 2

    def test_list_all_status_filter(self):
        store = _make_store()
        store.register(_make_entry(name="a", id="id-a"))
        store.register(_make_entry(name="b", id="id-b"))
        store.unregister("b")
        registered = store.list_all(status_filter=STATUS_REGISTERED)
        assert len(registered) == 1
        assert registered[0].name == "a"

    def test_list_all_invalid_status_raises(self):
        store = _make_store()
        with pytest.raises(ValueError, match="Invalid status_filter"):
            store.list_all(status_filter="invalid_status")


class TestAgentRegistryStoreUnregister:
    def test_unregister_sets_inactive(self):
        store = _make_store()
        store.register(_make_entry())
        result = store.unregister("test-agent")
        assert result is True
        found = store.get("test-agent")
        assert found.status == STATUS_INACTIVE

    def test_unregister_missing_returns_false(self):
        store = _make_store()
        result = store.unregister("does-not-exist")
        assert result is False


class TestAgentRegistryStoreUpdateLastActive:
    def test_increments_invocations(self):
        store = _make_store()
        store.register(_make_entry())
        store.update_last_active("test-agent")
        found = store.get("test-agent")
        assert found.total_invocations == 1

    def test_updates_last_active_at(self):
        store = _make_store()
        store.register(_make_entry())
        store.update_last_active("test-agent")
        found = store.get("test-agent")
        assert found.last_active_at is not None

    def test_missing_agent_no_error(self):
        store = _make_store()
        result = store.update_last_active("ghost-agent")  # Should not raise
        assert result is None


class TestAgentRegistryStoreUpdateStatus:
    def test_update_status_to_active(self):
        store = _make_store()
        store.register(_make_entry())
        store.update_status("test-agent", STATUS_ACTIVE)
        found = store.get("test-agent")
        assert found.status == STATUS_ACTIVE

    def test_invalid_status_raises(self):
        store = _make_store()
        store.register(_make_entry())
        with pytest.raises(ValueError, match="Invalid status"):
            store.update_status("test-agent", "bogus")

    def test_missing_agent_no_error(self):
        store = _make_store()
        result = store.update_status("ghost-agent", STATUS_ACTIVE)  # Should not raise
        assert result is None


class TestSessionFallback:
    """Test store._session() fallback when no session_factory provided."""

    def test_fallback_to_get_session(self):
        store = AgentRegistryStore(session_factory=None)
        mock_session = MagicMock()

        @contextmanager
        def _fake_get_session() -> Generator[MagicMock, None, None]:
            yield mock_session

        with patch(
            "temper_ai.storage.database.manager.get_session",
            side_effect=_fake_get_session,
        ):
            with store._session() as session:
                assert session is mock_session
