"""Tests for ConfigStore CRUD operations."""

import pytest

from temper_ai.config import ConfigStore
from temper_ai.config.helpers import ConfigNotFoundError


@pytest.fixture
def store():
    return ConfigStore()


class TestConfigStorePut:
    def test_put_new_config(self, store):
        config_id = store.put("test_agent", "agent", {"name": "test_agent", "type": "llm"})
        assert config_id is not None

    def test_put_and_get(self, store):
        store.put("my_wf", "workflow", {"name": "my_wf", "nodes": []})
        result = store.get("my_wf", "workflow")
        assert result["name"] == "my_wf"

    def test_put_update_existing(self, store):
        store.put("updatable", "agent", {"name": "updatable", "version": 1})
        store.put("updatable", "agent", {"name": "updatable", "version": 2})
        result = store.get("updatable", "agent")
        assert result["version"] == 2

    def test_put_invalid_type(self, store):
        with pytest.raises(ValueError):
            store.put("x", "invalid_type", {"name": "x"})


class TestConfigStoreGet:
    def test_get_not_found(self, store):
        with pytest.raises(ConfigNotFoundError):
            store.get("nonexistent_xyz_123", "agent")

    def test_get_invalid_type(self, store):
        with pytest.raises(ValueError):
            store.get("x", "invalid_type")


class TestConfigStoreList:
    def test_list_returns_list(self, store):
        result = store.list("agent")
        assert isinstance(result, list)

    def test_list_with_type_filter(self, store):
        store.put("list_test_a", "agent", {"name": "list_test_a"})
        store.put("list_test_w", "workflow", {"name": "list_test_w"})
        agents = store.list("agent")
        workflows = store.list("workflow")
        agent_names = [c["name"] for c in agents]
        workflow_names = [c["name"] for c in workflows]
        assert "list_test_a" in agent_names
        assert "list_test_w" in workflow_names
        assert "list_test_w" not in agent_names


class TestConfigStoreDelete:
    def test_delete_existing(self, store):
        store.put("deleteme", "agent", {"name": "deleteme"})
        result = store.delete("deleteme", "agent")
        assert result is True

    def test_delete_nonexistent(self, store):
        result = store.delete("never_existed_xyz", "agent")
        assert result is False

    def test_delete_then_get_raises(self, store):
        store.put("gone", "agent", {"name": "gone"})
        store.delete("gone", "agent")
        with pytest.raises(ConfigNotFoundError):
            store.get("gone", "agent")
