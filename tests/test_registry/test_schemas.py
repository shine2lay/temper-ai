"""Tests for temper_ai.registry._schemas."""
from datetime import timezone
from datetime import datetime

import pytest

from temper_ai.registry._schemas import (
    AgentRegistryEntry,
    MessageRequest,
    MessageResponse,
    PersistenceConfig,
)
from temper_ai.registry.constants import STATUS_REGISTERED


class TestPersistenceConfig:
    def test_defaults(self):
        cfg = PersistenceConfig()
        assert cfg.enabled is True

    def test_disabled(self):
        cfg = PersistenceConfig(enabled=False)
        assert cfg.enabled is False


class TestAgentRegistryEntry:
    def _make_entry(self, **kwargs):
        defaults = dict(
            id="abc123",
            name="test-agent",
            registered_at=datetime.now(timezone.utc),
        )
        defaults.update(kwargs)
        return AgentRegistryEntry(**defaults)

    def test_required_fields(self):
        entry = self._make_entry()
        assert entry.id == "abc123"
        assert entry.name == "test-agent"

    def test_default_status(self):
        entry = self._make_entry()
        assert entry.status == STATUS_REGISTERED

    def test_default_invocations(self):
        entry = self._make_entry()
        assert entry.total_invocations == 0

    def test_default_version(self):
        entry = self._make_entry()
        assert entry.version == "1.0"

    def test_default_agent_type(self):
        entry = self._make_entry()
        assert entry.agent_type == "standard"

    def test_optional_fields_none_by_default(self):
        entry = self._make_entry()
        assert entry.config_path is None
        assert entry.last_active_at is None
        assert entry.metadata_json is None

    def test_config_snapshot_default_empty(self):
        entry = self._make_entry()
        assert entry.config_snapshot == {}

    def test_custom_values(self):
        now = datetime.now(timezone.utc)
        entry = self._make_entry(
            description="A test agent",
            version="2.0",
            agent_type="custom",
            config_path="/path/to/agent.yaml",
            config_snapshot={"name": "test-agent"},
            memory_namespace="persistent__test-agent",
            status="active",
            total_invocations=5,
            last_active_at=now,
            metadata_json={"env": "prod"},
        )
        assert entry.description == "A test agent"
        assert entry.version == "2.0"
        assert entry.agent_type == "custom"
        assert entry.config_path == "/path/to/agent.yaml"
        assert entry.config_snapshot == {"name": "test-agent"}
        assert entry.memory_namespace == "persistent__test-agent"
        assert entry.status == "active"
        assert entry.total_invocations == 5
        assert entry.last_active_at == now
        assert entry.metadata_json == {"env": "prod"}


class TestMessageRequest:
    def test_required_content(self):
        req = MessageRequest(content="Hello")
        assert req.content == "Hello"

    def test_optional_fields_none(self):
        req = MessageRequest(content="Hello")
        assert req.context is None
        assert req.max_tokens is None

    def test_full_request(self):
        req = MessageRequest(
            content="What is X?",
            context={"key": "val"},
            max_tokens=512,
        )
        assert req.context == {"key": "val"}
        assert req.max_tokens == 512


class TestMessageResponse:
    def test_required_fields(self):
        resp = MessageResponse(
            content="The answer",
            agent_name="my-agent",
            execution_id="exec001",
        )
        assert resp.content == "The answer"
        assert resp.agent_name == "my-agent"
        assert resp.execution_id == "exec001"
        assert resp.tokens_used is None

    def test_with_tokens(self):
        resp = MessageResponse(
            content="Result",
            agent_name="agent",
            execution_id="e1",
            tokens_used=128,
        )
        assert resp.tokens_used == 128
