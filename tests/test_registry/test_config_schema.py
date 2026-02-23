"""Tests for M9 schema fields on AgentConfigInner."""

from temper_ai.storage.schemas.agent_config import AgentConfig, AgentConfigInner


def _base_agent_dict(**overrides):
    """Build a minimal valid agent config dict."""
    base = {
        "name": "test-agent",
        "description": "A test agent",
        "type": "standard",
        "prompt": {"inline": "You are a test agent. {{ input }}"},
        "inference": {
            "provider": "ollama",
            "model": "llama3",
        },
        "error_handling": {
            "retry_strategy": "ExponentialBackoff",
            "max_retries": 3,
            "fallback": "GracefulDegradation",
            "escalate_to_human_after": 3,
        },
    }
    base.update(overrides)
    return base


class TestPersistentField:
    """Tests for the `persistent` field added in M9."""

    def test_persistent_defaults_to_false(self):
        cfg = AgentConfigInner(**_base_agent_dict())
        assert cfg.persistent is False

    def test_persistent_can_be_set_true(self):
        cfg = AgentConfigInner(**_base_agent_dict(persistent=True))
        assert cfg.persistent is True

    def test_persistent_false_explicit(self):
        cfg = AgentConfigInner(**_base_agent_dict(persistent=False))
        assert cfg.persistent is False


class TestAgentIdField:
    """Tests for the `agent_id` field added in M9."""

    def test_agent_id_defaults_to_none(self):
        cfg = AgentConfigInner(**_base_agent_dict())
        assert cfg.agent_id is None

    def test_agent_id_can_be_set(self):
        cfg = AgentConfigInner(**_base_agent_dict(agent_id="agent-abc-123"))
        assert cfg.agent_id == "agent-abc-123"


class TestCrossPollinationField:
    """Tests for lazy-validated `cross_pollination` field added in M9."""

    def test_cross_pollination_defaults_to_none(self):
        cfg = AgentConfigInner(**_base_agent_dict())
        assert cfg.cross_pollination is None

    def test_cross_pollination_none_explicit(self):
        cfg = AgentConfigInner(**_base_agent_dict(cross_pollination=None))
        assert cfg.cross_pollination is None

    def test_cross_pollination_dict_parsed_to_config(self):
        from temper_ai.memory._m9_schemas import CrossPollinationConfig

        cfg = AgentConfigInner(
            **_base_agent_dict(
                cross_pollination={
                    "enabled": True,
                    "publish_output": True,
                    "subscribe_to": ["agent-x"],
                }
            )
        )
        assert isinstance(cfg.cross_pollination, CrossPollinationConfig)
        assert cfg.cross_pollination.enabled is True
        assert cfg.cross_pollination.publish_output is True
        assert cfg.cross_pollination.subscribe_to == ["agent-x"]

    def test_cross_pollination_defaults_applied(self):
        from temper_ai.memory._m9_schemas import CrossPollinationConfig

        cfg = AgentConfigInner(**_base_agent_dict(cross_pollination={}))
        assert isinstance(cfg.cross_pollination, CrossPollinationConfig)
        assert cfg.cross_pollination.enabled is False
        assert cfg.cross_pollination.max_published_entries == 50

    def test_cross_pollination_already_typed_passes_through(self):
        from temper_ai.memory._m9_schemas import CrossPollinationConfig

        cp = CrossPollinationConfig(enabled=True)
        cfg = AgentConfigInner(**_base_agent_dict(cross_pollination=cp))
        assert cfg.cross_pollination is cp


class TestBackwardCompat:
    """Verify existing configs without M9 fields still validate."""

    def test_config_without_m9_fields_valid(self):
        cfg = AgentConfigInner(**_base_agent_dict())
        assert cfg.persistent is False
        assert cfg.agent_id is None
        assert cfg.cross_pollination is None

    def test_full_agent_config_wrapper(self):
        data = {"agent": _base_agent_dict()}
        cfg = AgentConfig(**data)
        assert cfg.agent.persistent is False

    def test_existing_plugin_config_unaffected(self):
        """Plugin config still works as before."""
        cfg = AgentConfigInner(
            **_base_agent_dict(
                type="crewai",
                plugin_config={"framework": "crewai", "source_path": "/some/crew.py"},
                prompt=None,
                inference=None,
            )
        )
        assert cfg.plugin_config is not None
        assert cfg.persistent is False
