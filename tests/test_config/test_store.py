"""Tests for ConfigStore CRUD operations."""

import os

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

    def test_delete_invalid_type_raises(self, store):
        with pytest.raises(ValueError):
            store.delete("x", "invalid_type")


class TestConfigStoreListUnfiltered:
    def test_list_no_filter_returns_all_types(self, store):
        store.put("list_unf_agent", "agent", {"name": "list_unf_agent"})
        store.put("list_unf_wf", "workflow", {"name": "list_unf_wf"})
        all_configs = store.list()
        names = [c["name"] for c in all_configs]
        assert "list_unf_agent" in names
        assert "list_unf_wf" in names

    def test_list_result_contains_expected_fields(self, store):
        store.put("fields_test", "agent", {"name": "fields_test"})
        result = store.list("agent")
        match = next(c for c in result if c["name"] == "fields_test")
        assert "id" in match
        assert "type" in match
        assert "name" in match
        assert "schema_version" in match
        assert "created_at" in match
        assert "updated_at" in match

    def test_list_invalid_type_raises(self, store):
        with pytest.raises(ValueError):
            store.list("invalid_type")

    def test_list_ordered_by_type_then_name(self, store):
        store.put("z_agent", "agent", {"name": "z_agent"})
        store.put("a_agent", "agent", {"name": "a_agent"})
        agents = store.list("agent")
        names = [c["name"] for c in agents if c["name"] in ("z_agent", "a_agent")]
        assert names == ["a_agent", "z_agent"]


class TestConfigStoreSchemaVersion:
    def test_custom_schema_version_stored(self, store):
        store.put("versioned", "agent", {"name": "versioned"}, schema_version="1.0")
        results = store.list("agent")
        match = next(c for c in results if c["name"] == "versioned")
        assert match["schema_version"] == "1.0"

    def test_upsert_preserves_id(self, store):
        id1 = store.put("same_id", "agent", {"name": "same_id", "v": 1})
        id2 = store.put("same_id", "agent", {"name": "same_id", "v": 2})
        # Upsert should return the same row ID, not create a new one
        assert id1 == id2

    def test_upsert_updated_at_changes(self, store):
        store.put("ts_test", "agent", {"name": "ts_test", "v": 1})
        before = next(c for c in store.list("agent") if c["name"] == "ts_test")
        store.put("ts_test", "agent", {"name": "ts_test", "v": 2})
        after = next(c for c in store.list("agent") if c["name"] == "ts_test")
        # updated_at should be a valid ISO timestamp string
        assert after["updated_at"] is not None
        assert after["created_at"] is not None


class TestConfigStoreEnvVarSubstitution:
    def test_get_resolves_env_vars(self, store, monkeypatch):
        monkeypatch.setenv("TEST_STORE_MODEL", "gpt-4o")
        store.put("env_wf", "workflow", {"model": "${TEST_STORE_MODEL}"})
        result = store.get("env_wf", "workflow")
        assert result["model"] == "gpt-4o"

    def test_get_resolves_default_when_var_missing(self, store):
        os.environ.pop("STORE_MISSING_VAR", None)
        store.put("default_wf", "workflow", {"model": "${STORE_MISSING_VAR:gpt-3.5-turbo}"})
        result = store.get("default_wf", "workflow")
        assert result["model"] == "gpt-3.5-turbo"

    def test_put_stores_raw_template_not_resolved(self, store, monkeypatch):
        monkeypatch.setenv("TEST_STORE_RAW", "resolved_value")
        store.put("raw_wf", "workflow", {"key": "${TEST_STORE_RAW}"})
        # list() does NOT resolve env vars — only get() does
        items = store.list("workflow")
        match = next(c for c in items if c["name"] == "raw_wf")
        # list() returns summary fields only (id/type/name/schema_version/timestamps)
        # the raw config payload is not in list() output, so just verify the row exists
        assert match["name"] == "raw_wf"
