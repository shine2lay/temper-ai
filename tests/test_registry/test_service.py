"""Tests for temper_ai.registry.service."""

import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
import yaml
from sqlmodel import Session, SQLModel

from temper_ai.registry._schemas import MessageRequest
from temper_ai.registry.constants import STATUS_INACTIVE, STATUS_REGISTERED
from temper_ai.registry.service import AgentRegistryService
from temper_ai.registry.store import AgentRegistryStore
from temper_ai.storage.database.engine import create_test_engine
from temper_ai.storage.database.models_registry import AgentRegistryDB  # noqa: F401


def _make_store() -> AgentRegistryStore:
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


def _write_agent_yaml(data: dict) -> str:
    """Write a YAML agent config to a temp file and return path."""
    fh = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump(data, fh)
    fh.close()
    return fh.name


class TestAgentRegistryServiceRegisterAgent:
    def test_register_returns_entry(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        path = _write_agent_yaml({"name": "my-agent", "type": "standard"})
        try:
            entry = svc.register_agent(path)
            assert entry.name == "my-agent"
        finally:
            os.unlink(path)

    def test_register_persists_to_store(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        path = _write_agent_yaml({"name": "persist-agent"})
        try:
            svc.register_agent(path)
            found = store.get("persist-agent")
            assert found is not None
            assert found.name == "persist-agent"
        finally:
            os.unlink(path)

    def test_register_sets_memory_namespace(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        path = _write_agent_yaml({"name": "ns-agent"})
        try:
            entry = svc.register_agent(path)
            assert "ns-agent" in entry.memory_namespace
        finally:
            os.unlink(path)

    def test_register_with_metadata(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        path = _write_agent_yaml({"name": "meta-agent"})
        try:
            entry = svc.register_agent(path, metadata={"env": "staging"})
            assert entry.metadata_json == {"env": "staging"}
        finally:
            os.unlink(path)

    def test_register_no_name_raises(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        path = _write_agent_yaml({"type": "standard"})
        try:
            with pytest.raises(ValueError, match="must have a 'name' field"):
                svc.register_agent(path)
        finally:
            os.unlink(path)


class TestAgentRegistryServiceUnregister:
    def test_unregister_existing(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        path = _write_agent_yaml({"name": "remove-me"})
        try:
            svc.register_agent(path)
            result = svc.unregister_agent("remove-me")
            assert result is True
            found = store.get("remove-me")
            assert found.status == STATUS_INACTIVE
        finally:
            os.unlink(path)

    def test_unregister_missing(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        result = svc.unregister_agent("ghost")
        assert result is False


class TestAgentRegistryServiceListAgents:
    def test_list_empty(self):
        svc = AgentRegistryService(store=_make_store())
        assert svc.list_agents() == []

    def test_list_with_entries(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        for name in ("agent-1", "agent-2"):
            path = _write_agent_yaml({"name": name})
            try:
                svc.register_agent(path)
            finally:
                os.unlink(path)
        results = svc.list_agents()
        assert len(results) == 2

    def test_list_status_filter(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        path = _write_agent_yaml({"name": "filter-me"})
        try:
            svc.register_agent(path)
        finally:
            os.unlink(path)
        svc.unregister_agent("filter-me")
        registered = svc.list_agents(status=STATUS_REGISTERED)
        assert all(e.status == STATUS_REGISTERED for e in registered)


class TestAgentRegistryServiceGetAgent:
    def test_get_existing(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        path = _write_agent_yaml({"name": "findable"})
        try:
            svc.register_agent(path)
            found = svc.get_agent("findable")
            assert found is not None
            assert found.name == "findable"
        finally:
            os.unlink(path)

    def test_get_missing(self):
        svc = AgentRegistryService(store=_make_store())
        assert svc.get_agent("nonexistent") is None


class TestAgentRegistryServiceInvoke:
    def test_invoke_missing_agent_raises(self):
        svc = AgentRegistryService(store=_make_store())
        with pytest.raises(KeyError, match="not found in registry"):
            svc.invoke("ghost", MessageRequest(content="hello"))

    def test_invoke_calls_agent_run(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        path = _write_agent_yaml({"name": "runnable"})
        try:
            svc.register_agent(path)
        finally:
            os.unlink(path)

        mock_agent = MagicMock()
        mock_agent.run.return_value = "agent response"

        with patch.object(svc, "_load_agent", return_value=mock_agent):
            response = svc.invoke("runnable", MessageRequest(content="ping"))

        assert response.content == "agent response"
        assert response.agent_name == "runnable"
        assert response.execution_id != ""
        mock_agent.run.assert_called_once_with("ping")

    def test_invoke_updates_invocations(self):
        store = _make_store()
        svc = AgentRegistryService(store=store)
        path = _write_agent_yaml({"name": "counter"})
        try:
            svc.register_agent(path)
        finally:
            os.unlink(path)

        mock_agent = MagicMock()
        mock_agent.run.return_value = "ok"

        with patch.object(svc, "_load_agent", return_value=mock_agent):
            svc.invoke("counter", MessageRequest(content="hello"))

        found = store.get("counter")
        assert found.total_invocations == 1
