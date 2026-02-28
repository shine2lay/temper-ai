"""Tests for temper_ai.storage.schemas.agent_config.

Covers all model classes: defaults, required fields, validators, and
constraint enforcement via ValidationError.
"""

import warnings

import pytest
from pydantic import ValidationError

from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ContextManagementConfig,
    ErrorHandlingConfig,
    GuardrailCheck,
    InferenceConfig,
    MemoryConfig,
    MeritTrackingConfig,
    MetadataConfig,
    ObservabilityConfig,
    OutputGuardrailsConfig,
    OutputSchemaConfig,
    PreCommand,
    PromptConfig,
    ReasoningConfig,
    RetryConfig,
    SafetyConfig,
    ToolReference,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_inference(provider="ollama") -> dict:
    base = {"provider": provider, "model": "my-model"}
    if provider in ("openai", "anthropic"):
        base["api_key_ref"] = "${env:MY_KEY}"
    if provider == "vllm":
        base["base_url"] = "http://localhost:8000"
    return base


def _valid_prompt() -> dict:
    return {"inline": "You are a helpful assistant."}


def _valid_error_handling() -> dict:
    return {"retry_strategy": "ExponentialBackoff", "fallback": "GracefulDegradation"}


def _minimal_agent_inner() -> dict:
    return {
        "name": "my-agent",
        "description": "A test agent",
        "prompt": _valid_prompt(),
        "inference": _valid_inference(),
        "error_handling": _valid_error_handling(),
    }


# ---------------------------------------------------------------------------
# InferenceConfig
# ---------------------------------------------------------------------------


class TestInferenceConfig:
    """Tests for InferenceConfig model."""

    def test_minimal_ollama(self):
        cfg = InferenceConfig(provider="ollama", model="llama3")
        assert cfg.provider == "ollama"
        assert cfg.model == "llama3"

    def test_defaults_applied(self):
        cfg = InferenceConfig(provider="ollama", model="llama3")
        assert cfg.temperature >= 0.0
        assert cfg.max_tokens > 0
        assert cfg.top_p >= 0.0
        assert cfg.timeout_seconds > 0
        assert cfg.max_retries >= 0

    def test_temperature_range(self):
        with pytest.raises(ValidationError):
            InferenceConfig(provider="ollama", model="m", temperature=-0.1)
        with pytest.raises(ValidationError):
            InferenceConfig(provider="ollama", model="m", temperature=2.1)

    def test_temperature_boundary_values(self):
        cfg = InferenceConfig(provider="ollama", model="m", temperature=0.0)
        assert cfg.temperature == 0.0
        cfg2 = InferenceConfig(provider="ollama", model="m", temperature=2.0)
        assert cfg2.temperature == 2.0

    def test_top_p_range(self):
        with pytest.raises(ValidationError):
            InferenceConfig(provider="ollama", model="m", top_p=-0.1)
        with pytest.raises(ValidationError):
            InferenceConfig(provider="ollama", model="m", top_p=1.1)

    def test_max_tokens_must_be_positive(self):
        with pytest.raises(ValidationError):
            InferenceConfig(provider="ollama", model="m", max_tokens=0)

    def test_openai_requires_api_key_ref(self):
        with pytest.raises(ValidationError, match="api_key_ref"):
            InferenceConfig(provider="openai", model="gpt-4")

    def test_openai_with_api_key_ref_succeeds(self):
        cfg = InferenceConfig(
            provider="openai", model="gpt-4", api_key_ref="${env:OPENAI_API_KEY}"
        )
        assert cfg.provider == "openai"

    def test_anthropic_requires_api_key_ref(self):
        with pytest.raises(ValidationError, match="api_key_ref"):
            InferenceConfig(provider="anthropic", model="claude-3")

    def test_vllm_requires_base_url(self):
        with pytest.raises(ValidationError, match="base_url"):
            InferenceConfig(provider="vllm", model="mistral")

    def test_vllm_with_base_url_succeeds(self):
        cfg = InferenceConfig(
            provider="vllm", model="mistral", base_url="http://localhost:8000"
        )
        assert cfg.base_url == "http://localhost:8000"

    def test_custom_provider_raises(self):
        with pytest.raises(ValidationError, match="custom.*not yet supported"):
            InferenceConfig(provider="custom", model="my-model")

    def test_deprecated_api_key_migrated_to_api_key_ref(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cfg = InferenceConfig(provider="ollama", model="m", api_key="raw-secret")
        assert cfg.api_key_ref == "raw-secret"
        assert cfg.api_key is None
        assert any(issubclass(warning.category, DeprecationWarning) for warning in w)

    def test_use_text_tool_schemas_default_false(self):
        cfg = InferenceConfig(provider="ollama", model="m")
        assert cfg.use_text_tool_schemas is False


# ---------------------------------------------------------------------------
# SafetyConfig
# ---------------------------------------------------------------------------


class TestSafetyConfig:
    """Tests for SafetyConfig model."""

    def test_defaults(self):
        cfg = SafetyConfig()
        assert cfg.mode == "execute"
        assert cfg.require_approval_for_tools == []
        assert cfg.risk_level == "medium"
        assert cfg.max_tool_calls_per_execution > 0
        assert cfg.max_execution_time_seconds > 0

    def test_valid_modes(self):
        for mode in ("execute", "dry_run", "require_approval"):
            cfg = SafetyConfig(mode=mode)
            assert cfg.mode == mode

    def test_invalid_mode_raises(self):
        with pytest.raises(ValidationError):
            SafetyConfig(mode="unknown_mode")

    def test_valid_risk_levels(self):
        for level in ("low", "medium", "high"):
            cfg = SafetyConfig(risk_level=level)
            assert cfg.risk_level == level

    def test_max_tool_calls_must_be_positive(self):
        with pytest.raises(ValidationError):
            SafetyConfig(max_tool_calls_per_execution=0)

    def test_require_approval_for_tools_list(self):
        cfg = SafetyConfig(require_approval_for_tools=["bash", "file_write"])
        assert "bash" in cfg.require_approval_for_tools


# ---------------------------------------------------------------------------
# MemoryConfig
# ---------------------------------------------------------------------------


class TestMemoryConfig:
    """Tests for MemoryConfig model."""

    def test_defaults_disabled(self):
        cfg = MemoryConfig()
        assert cfg.enabled is False
        assert cfg.type is None
        assert cfg.scope is None

    def test_enabled_requires_type_and_scope(self):
        with pytest.raises(ValidationError, match="type and scope must be specified"):
            MemoryConfig(enabled=True)

    def test_enabled_with_type_and_scope_succeeds(self):
        cfg = MemoryConfig(enabled=True, type="vector", scope="session")
        assert cfg.enabled is True

    def test_retrieval_k_must_be_positive(self):
        with pytest.raises(ValidationError):
            MemoryConfig(retrieval_k=0)

    def test_relevance_threshold_bounds(self):
        with pytest.raises(ValidationError):
            MemoryConfig(relevance_threshold=-0.1)
        with pytest.raises(ValidationError):
            MemoryConfig(relevance_threshold=1.1)

    def test_max_episodes_must_be_positive(self):
        with pytest.raises(ValidationError):
            MemoryConfig(max_episodes=0)

    def test_decay_factor_bounds(self):
        with pytest.raises(ValidationError):
            MemoryConfig(decay_factor=-0.1)
        with pytest.raises(ValidationError):
            MemoryConfig(decay_factor=1.1)

    def test_optional_namespace_fields(self):
        cfg = MemoryConfig(memory_namespace="ns1", shared_namespace="shared")
        assert cfg.memory_namespace == "ns1"
        assert cfg.shared_namespace == "shared"


# ---------------------------------------------------------------------------
# ReasoningConfig
# ---------------------------------------------------------------------------


class TestReasoningConfig:
    """Tests for ReasoningConfig model."""

    def test_defaults(self):
        cfg = ReasoningConfig()
        assert cfg.enabled is False
        assert cfg.planning_prompt is None
        assert cfg.inject_as == "context_section"
        assert cfg.max_planning_tokens == 1024

    def test_max_planning_tokens_must_be_positive(self):
        with pytest.raises(ValidationError):
            ReasoningConfig(max_planning_tokens=0)

    def test_temperature_bounds(self):
        with pytest.raises(ValidationError):
            ReasoningConfig(temperature=-0.1)
        with pytest.raises(ValidationError):
            ReasoningConfig(temperature=2.1)

    def test_temperature_none_allowed(self):
        cfg = ReasoningConfig(temperature=None)
        assert cfg.temperature is None


# ---------------------------------------------------------------------------
# ContextManagementConfig
# ---------------------------------------------------------------------------


class TestContextManagementConfig:
    """Tests for ContextManagementConfig model."""

    def test_defaults(self):
        cfg = ContextManagementConfig()
        assert cfg.enabled is False
        assert cfg.strategy == "truncate"
        assert cfg.reserved_output_tokens == 2048

    def test_reserved_output_tokens_must_be_positive(self):
        with pytest.raises(ValidationError):
            ContextManagementConfig(reserved_output_tokens=0)

    def test_valid_strategies(self):
        for strategy in ("truncate", "summarize", "sliding_window"):
            cfg = ContextManagementConfig(strategy=strategy)
            assert cfg.strategy == strategy


# ---------------------------------------------------------------------------
# OutputSchemaConfig
# ---------------------------------------------------------------------------


class TestOutputSchemaConfig:
    """Tests for OutputSchemaConfig model."""

    def test_defaults(self):
        cfg = OutputSchemaConfig()
        assert cfg.json_schema is None
        assert cfg.enforce_mode == "validate_only"
        assert cfg.max_retries == 2
        assert cfg.strict is False

    def test_max_retries_non_negative(self):
        with pytest.raises(ValidationError):
            OutputSchemaConfig(max_retries=-1)

    def test_json_schema_accepted(self):
        schema = {"type": "object", "properties": {"result": {"type": "string"}}}
        cfg = OutputSchemaConfig(json_schema=schema)
        assert cfg.json_schema == schema


# ---------------------------------------------------------------------------
# GuardrailCheck
# ---------------------------------------------------------------------------


class TestGuardrailCheck:
    """Tests for GuardrailCheck model."""

    def test_required_name(self):
        with pytest.raises(ValidationError):
            GuardrailCheck()

    def test_defaults(self):
        cfg = GuardrailCheck(name="my-check")
        assert cfg.type == "function"
        assert cfg.severity == "block"
        assert cfg.check_ref is None
        assert cfg.pattern is None

    def test_regex_type(self):
        cfg = GuardrailCheck(
            name="pii-check", type="regex", pattern=r"\d{3}-\d{2}-\d{4}"
        )
        assert cfg.type == "regex"
        assert cfg.pattern is not None


# ---------------------------------------------------------------------------
# OutputGuardrailsConfig
# ---------------------------------------------------------------------------


class TestOutputGuardrailsConfig:
    """Tests for OutputGuardrailsConfig model."""

    def test_defaults(self):
        cfg = OutputGuardrailsConfig()
        assert cfg.enabled is False
        assert cfg.checks == []
        assert cfg.max_retries == 2
        assert cfg.inject_feedback is True

    def test_checks_list(self):
        check = GuardrailCheck(name="check1")
        cfg = OutputGuardrailsConfig(enabled=True, checks=[check])
        assert len(cfg.checks) == 1

    def test_max_retries_non_negative(self):
        with pytest.raises(ValidationError):
            OutputGuardrailsConfig(max_retries=-1)


# ---------------------------------------------------------------------------
# RetryConfig
# ---------------------------------------------------------------------------


class TestRetryConfig:
    """Tests for RetryConfig model."""

    def test_defaults(self):
        cfg = RetryConfig()
        assert cfg.initial_delay_seconds > 0
        assert cfg.max_delay_seconds > 0
        assert cfg.exponential_base > 1.0

    def test_initial_delay_must_be_positive(self):
        with pytest.raises(ValidationError):
            RetryConfig(initial_delay_seconds=0)

    def test_max_delay_must_be_positive(self):
        with pytest.raises(ValidationError):
            RetryConfig(max_delay_seconds=0)

    def test_exponential_base_must_exceed_one(self):
        with pytest.raises(ValidationError):
            RetryConfig(exponential_base=1.0)


# ---------------------------------------------------------------------------
# ErrorHandlingConfig
# ---------------------------------------------------------------------------


class TestErrorHandlingConfig:
    """Tests for ErrorHandlingConfig model."""

    def test_defaults(self):
        cfg = ErrorHandlingConfig()
        assert cfg.retry_strategy == "ExponentialBackoff"
        assert cfg.fallback == "GracefulDegradation"
        assert cfg.max_retries >= 0

    def test_valid_retry_strategies(self):
        for strategy in ("ExponentialBackoff", "LinearBackoff", "FixedDelay"):
            cfg = ErrorHandlingConfig(retry_strategy=strategy)
            assert cfg.retry_strategy == strategy

    def test_invalid_retry_strategy_raises(self):
        with pytest.raises(ValidationError, match="Invalid retry_strategy"):
            ErrorHandlingConfig(retry_strategy="NotAStrategy")

    def test_valid_fallbacks(self):
        for fb in (
            "GracefulDegradation",
            "ReturnDefault",
            "RaiseError",
            "LogAndContinue",
        ):
            cfg = ErrorHandlingConfig(fallback=fb)
            assert cfg.fallback == fb

    def test_invalid_fallback_raises(self):
        with pytest.raises(ValidationError, match="Invalid fallback"):
            ErrorHandlingConfig(fallback="DoNothing")

    def test_escalate_to_human_after_must_be_positive(self):
        with pytest.raises(ValidationError):
            ErrorHandlingConfig(escalate_to_human_after=0)

    def test_nested_retry_config(self):
        cfg = ErrorHandlingConfig(retry_config=RetryConfig(initial_delay_seconds=5))
        assert cfg.retry_config.initial_delay_seconds == 5


# ---------------------------------------------------------------------------
# MeritTrackingConfig
# ---------------------------------------------------------------------------


class TestMeritTrackingConfig:
    """Tests for MeritTrackingConfig model."""

    def test_defaults(self):
        cfg = MeritTrackingConfig()
        assert cfg.enabled is True
        assert cfg.track_decision_outcomes is True
        assert cfg.decay_enabled is True
        assert cfg.domain_expertise == []

    def test_half_life_days_must_be_positive(self):
        with pytest.raises(ValidationError):
            MeritTrackingConfig(half_life_days=0)


# ---------------------------------------------------------------------------
# ObservabilityConfig
# ---------------------------------------------------------------------------


class TestObservabilityConfig:
    """Tests for ObservabilityConfig model."""

    def test_defaults(self):
        cfg = ObservabilityConfig()
        assert cfg.log_inputs is True
        assert cfg.log_outputs is True
        assert cfg.log_reasoning is True
        assert cfg.log_full_llm_responses is False
        assert cfg.track_latency is True
        assert cfg.track_token_usage is True


# ---------------------------------------------------------------------------
# PromptConfig
# ---------------------------------------------------------------------------


class TestPromptConfig:
    """Tests for PromptConfig model."""

    def test_inline_only(self):
        cfg = PromptConfig(inline="Say hello")
        assert cfg.inline == "Say hello"
        assert cfg.template is None

    def test_template_only(self):
        cfg = PromptConfig(template="/path/to/template.j2")
        assert cfg.template == "/path/to/template.j2"
        assert cfg.inline is None

    def test_neither_raises(self):
        with pytest.raises(ValidationError, match="Either template or inline"):
            PromptConfig()

    def test_both_raises(self):
        with pytest.raises(ValidationError, match="Only one of"):
            PromptConfig(template="/some/path.j2", inline="also inline")

    def test_variables_default_empty(self):
        cfg = PromptConfig(inline="hello")
        assert cfg.variables == {}

    def test_variables_passed_through(self):
        cfg = PromptConfig(inline="hello {name}", variables={"name": "world"})
        assert cfg.variables["name"] == "world"


# ---------------------------------------------------------------------------
# ToolReference
# ---------------------------------------------------------------------------


class TestToolReference:
    """Tests for ToolReference model."""

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ToolReference()

    def test_config_default_empty(self):
        ref = ToolReference(name="bash")
        assert ref.config == {}

    def test_config_accepted(self):
        ref = ToolReference(name="bash", config={"timeout": 30})
        assert ref.config["timeout"] == 30


# ---------------------------------------------------------------------------
# PreCommand
# ---------------------------------------------------------------------------


class TestPreCommand:
    """Tests for PreCommand model."""

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            PreCommand()

    def test_valid_command(self):
        cmd = PreCommand(name="fetch-data", command="curl http://example.com")
        assert cmd.name == "fetch-data"
        assert cmd.command == "curl http://example.com"

    def test_timeout_must_be_positive(self):
        with pytest.raises(ValidationError):
            PreCommand(name="bad", command="echo hi", timeout_seconds=0)

    def test_timeout_max_enforced(self):
        from temper_ai.shared.constants.agent_defaults import PRE_COMMAND_MAX_TIMEOUT

        with pytest.raises(ValidationError):
            PreCommand(
                name="bad",
                command="echo hi",
                timeout_seconds=PRE_COMMAND_MAX_TIMEOUT + 1,
            )


# ---------------------------------------------------------------------------
# MetadataConfig
# ---------------------------------------------------------------------------


class TestMetadataConfig:
    """Tests for MetadataConfig model."""

    def test_defaults(self):
        cfg = MetadataConfig()
        assert cfg.tags == []
        assert cfg.owner is None
        assert cfg.created is None
        assert cfg.last_modified is None
        assert cfg.documentation_url is None

    def test_tags_list(self):
        cfg = MetadataConfig(tags=["prod", "ml"])
        assert "prod" in cfg.tags


# ---------------------------------------------------------------------------
# AgentConfigInner
# ---------------------------------------------------------------------------


class TestAgentConfigInner:
    """Tests for AgentConfigInner model."""

    def test_minimal_standard_agent(self):
        cfg = AgentConfigInner(**_minimal_agent_inner())
        assert cfg.name == "my-agent"
        assert cfg.description == "A test agent"

    def test_required_name_missing(self):
        data = _minimal_agent_inner()
        del data["name"]
        with pytest.raises(ValidationError):
            AgentConfigInner(**data)

    def test_required_description_missing(self):
        data = _minimal_agent_inner()
        del data["description"]
        with pytest.raises(ValidationError):
            AgentConfigInner(**data)

    def test_required_error_handling_missing(self):
        data = _minimal_agent_inner()
        del data["error_handling"]
        with pytest.raises(ValidationError):
            AgentConfigInner(**data)

    def test_default_version(self):
        cfg = AgentConfigInner(**_minimal_agent_inner())
        assert cfg.version == "1.0"

    def test_default_type(self):
        cfg = AgentConfigInner(**_minimal_agent_inner())
        assert cfg.type == "standard"

    def test_script_type_requires_script_field(self):
        data = {
            "name": "script-agent",
            "description": "A script agent",
            "type": "script",
            "error_handling": _valid_error_handling(),
        }
        with pytest.raises(ValidationError, match="'script' field is required"):
            AgentConfigInner(**data)

    def test_script_type_with_script_succeeds(self):
        data = {
            "name": "script-agent",
            "description": "A script agent",
            "type": "script",
            "script": "echo hello",
            "error_handling": _valid_error_handling(),
        }
        cfg = AgentConfigInner(**data)
        assert cfg.script == "echo hello"

    def test_standard_type_requires_prompt(self):
        data = _minimal_agent_inner()
        del data["prompt"]
        with pytest.raises(ValidationError, match="'prompt' is required"):
            AgentConfigInner(**data)

    def test_standard_type_requires_inference(self):
        data = _minimal_agent_inner()
        del data["inference"]
        with pytest.raises(ValidationError, match="'inference' is required"):
            AgentConfigInner(**data)

    def test_default_safety_config(self):
        cfg = AgentConfigInner(**_minimal_agent_inner())
        assert isinstance(cfg.safety, SafetyConfig)

    def test_default_memory_config(self):
        cfg = AgentConfigInner(**_minimal_agent_inner())
        assert isinstance(cfg.memory, MemoryConfig)

    def test_default_observability_config(self):
        cfg = AgentConfigInner(**_minimal_agent_inner())
        assert isinstance(cfg.observability, ObservabilityConfig)

    def test_tools_list_accepts_strings(self):
        data = _minimal_agent_inner()
        data["tools"] = ["bash", "file_read"]
        cfg = AgentConfigInner(**data)
        assert "bash" in cfg.tools

    def test_tools_list_accepts_tool_references(self):
        data = _minimal_agent_inner()
        data["tools"] = [{"name": "bash", "config": {"timeout": 30}}]
        cfg = AgentConfigInner(**data)
        assert isinstance(cfg.tools[0], ToolReference)

    def test_persistent_default_false(self):
        cfg = AgentConfigInner(**_minimal_agent_inner())
        assert cfg.persistent is False

    def test_dialogue_aware_default_true(self):
        cfg = AgentConfigInner(**_minimal_agent_inner())
        assert cfg.dialogue_aware is True

    def test_max_dialogue_context_chars_positive(self):
        cfg = AgentConfigInner(**_minimal_agent_inner())
        assert cfg.max_dialogue_context_chars > 0

    def test_max_dialogue_context_chars_validation(self):
        data = _minimal_agent_inner()
        data["max_dialogue_context_chars"] = 0
        with pytest.raises(ValidationError):
            AgentConfigInner(**data)


# ---------------------------------------------------------------------------
# AgentConfig (top-level wrapper)
# ---------------------------------------------------------------------------


class TestAgentConfig:
    """Tests for the top-level AgentConfig wrapper."""

    def test_wraps_agent_inner(self):
        cfg = AgentConfig(agent=_minimal_agent_inner())
        assert isinstance(cfg.agent, AgentConfigInner)
        assert cfg.agent.name == "my-agent"

    def test_default_schema_version(self):
        cfg = AgentConfig(agent=_minimal_agent_inner())
        assert cfg.schema_version == "1.0"

    def test_custom_schema_version(self):
        cfg = AgentConfig(agent=_minimal_agent_inner(), schema_version="2.0")
        assert cfg.schema_version == "2.0"

    def test_agent_field_required(self):
        with pytest.raises(ValidationError):
            AgentConfig()
