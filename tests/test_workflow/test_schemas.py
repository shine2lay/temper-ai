"""
Tests for Pydantic configuration schemas.

Tests validation of agent, stage, workflow, tool, and trigger configurations.
"""
import pytest
from pydantic import ValidationError

from temper_ai.stage._schemas import CollaborationConfig, ConflictResolutionConfig, StageConfig, StageExecutionConfig
from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    InferenceConfig,
    MemoryConfig,
    PromptConfig,
    SafetyConfig,
    ToolReference,
)
from temper_ai.tools._schemas import ToolConfig
from temper_ai.workflow._schemas import WorkflowConfig, WorkflowErrorHandlingConfig, WorkflowObservabilityConfig
from temper_ai.workflow._triggers import CronTrigger, EventTrigger, ThresholdTrigger

# ============================================
# AGENT SCHEMA TESTS
# ============================================

class TestInferenceConfig:
    """Tests for InferenceConfig schema."""

    def test_valid_inference_config(self):
        """Test valid inference configuration."""
        config = InferenceConfig(
            provider="ollama",
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            temperature=0.7,
            max_tokens=2048
        )
        assert config.provider == "ollama"
        assert config.model == "llama3.2:3b"
        assert config.temperature == 0.7
        assert config.max_tokens == 2048

    def test_inference_config_defaults(self):
        """Test default values in inference config."""
        config = InferenceConfig(provider="openai", model="gpt-4")
        assert config.temperature == 0.7
        assert config.max_tokens == 131072
        assert config.top_p == 0.9
        assert config.timeout_seconds == 1800  # 30 minutes default for LLM calls
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 2

    def test_invalid_provider(self):
        """Test invalid provider raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            InferenceConfig(provider="invalid_provider", model="test")
        # Pydantic's Literal validation error message
        assert "Input should be" in str(exc_info.value) and "literal_error" in str(exc_info.value)

    def test_temperature_bounds(self):
        """Test temperature validation bounds."""
        # Valid temperatures
        InferenceConfig(provider="ollama", model="test", temperature=0.0)
        InferenceConfig(provider="ollama", model="test", temperature=2.0)

        # Invalid temperatures
        with pytest.raises(ValidationError):
            InferenceConfig(provider="ollama", model="test", temperature=-0.1)
        with pytest.raises(ValidationError):
            InferenceConfig(provider="ollama", model="test", temperature=2.1)

    def test_top_p_bounds(self):
        """Test top_p validation bounds."""
        # Valid top_p
        InferenceConfig(provider="ollama", model="test", top_p=0.0)
        InferenceConfig(provider="ollama", model="test", top_p=1.0)

        # Invalid top_p
        with pytest.raises(ValidationError):
            InferenceConfig(provider="ollama", model="test", top_p=-0.1)
        with pytest.raises(ValidationError):
            InferenceConfig(provider="ollama", model="test", top_p=1.1)


class TestSafetyConfig:
    """Tests for SafetyConfig schema."""

    def test_valid_safety_config(self):
        """Test valid safety configuration."""
        config = SafetyConfig(
            mode="execute",
            require_approval_for_tools=["DatabaseQuery", "FileWriter"],
            max_tool_calls_per_execution=20,
            risk_level="medium"
        )
        assert config.mode == "execute"
        assert len(config.require_approval_for_tools) == 2
        assert config.risk_level == "medium"

    def test_safety_config_defaults(self):
        """Test default values."""
        config = SafetyConfig()
        assert config.mode == "execute"
        assert config.require_approval_for_tools == []
        assert config.max_tool_calls_per_execution == 20
        assert config.max_execution_time_seconds == 300
        assert config.risk_level == "medium"

    def test_invalid_mode(self):
        """Test invalid mode raises error."""
        with pytest.raises(ValidationError):
            SafetyConfig(mode="invalid_mode")

    def test_invalid_risk_level(self):
        """Test invalid risk level raises error."""
        with pytest.raises(ValidationError):
            SafetyConfig(risk_level="critical")


class TestMemoryConfig:
    """Tests for MemoryConfig schema."""

    def test_disabled_memory(self):
        """Test disabled memory config."""
        config = MemoryConfig(enabled=False)
        assert config.enabled is False
        assert config.type is None
        assert config.scope is None

    def test_enabled_memory_requires_type_and_scope(self):
        """Test enabled memory requires type and scope."""
        with pytest.raises(ValidationError) as exc_info:
            MemoryConfig(enabled=True)
        assert "type and scope must be specified" in str(exc_info.value)

    def test_valid_enabled_memory(self):
        """Test valid enabled memory config."""
        config = MemoryConfig(
            enabled=True,
            type="vector",
            scope="session",
            retrieval_k=10,
            relevance_threshold=0.7
        )
        assert config.enabled is True
        assert config.type == "vector"
        assert config.scope == "session"
        assert config.retrieval_k == 10

    def test_memory_defaults(self):
        """Test default values for memory config."""
        config = MemoryConfig(enabled=False)
        assert config.retrieval_k == 10
        assert config.relevance_threshold == 0.7
        assert config.max_episodes == 1000
        assert config.decay_factor == 0.95


class TestPromptConfig:
    """Tests for PromptConfig schema."""

    def test_template_prompt(self):
        """Test prompt config with template."""
        config = PromptConfig(
            template="prompts/researcher_base.txt",
            variables={"domain": "SaaS", "tone": "professional"}
        )
        assert config.template == "prompts/researcher_base.txt"
        assert config.inline is None
        assert len(config.variables) == 2

    def test_inline_prompt(self):
        """Test prompt config with inline string."""
        config = PromptConfig(inline="You are a researcher...")
        assert config.inline == "You are a researcher..."
        assert config.template is None
        assert config.variables == {}

    def test_missing_both_template_and_inline(self):
        """Test that at least one of template or inline is required."""
        with pytest.raises(ValidationError) as exc_info:
            PromptConfig()
        assert "Either template or inline must be specified" in str(exc_info.value)

    def test_both_template_and_inline_not_allowed(self):
        """Test that both template and inline cannot be specified."""
        with pytest.raises(ValidationError) as exc_info:
            PromptConfig(template="test.txt", inline="test")
        assert "Only one of template or inline" in str(exc_info.value)


class TestAgentConfig:
    """Tests for full AgentConfig schema."""

    def test_valid_agent_config(self):
        """Test valid complete agent configuration."""
        config_dict = {
            "agent": {
                "name": "test_agent",
                "description": "Test agent",
                "version": "1.0",
                "prompt": {
                    "inline": "You are a test agent"
                },
                "inference": {
                    "provider": "ollama",
                    "model": "llama3.2:3b",
                    "base_url": "http://localhost:11434"
                },
                "tools": ["WebScraper", "Calculator"],
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "fallback": "GracefulDegradation"
                }
            }
        }
        config = AgentConfig(**config_dict)
        assert config.agent.name == "test_agent"
        assert config.agent.inference.provider == "ollama"
        assert len(config.agent.tools) == 2

    def test_agent_with_tool_overrides(self):
        """Test agent config with tool overrides."""
        config_dict = {
            "agent": {
                "name": "test_agent",
                "description": "Test agent",
                "prompt": {"inline": "Test"},
                "inference": {"provider": "ollama", "model": "llama3.2:3b"},
                "tools": [
                    "WebScraper",
                    {
                        "name": "DatabaseQuery",
                        "config": {"max_rows": 1000, "timeout_seconds": 30}
                    }
                ],
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "fallback": "GracefulDegradation"
                }
            }
        }
        config = AgentConfig(**config_dict)
        assert len(config.agent.tools) == 2
        assert isinstance(config.agent.tools[0], str)
        assert isinstance(config.agent.tools[1], ToolReference)

    def test_agent_config_with_all_optional_fields(self):
        """Test agent config with all optional fields populated."""
        config_dict = {
            "agent": {
                "name": "full_agent",
                "description": "Full featured agent",
                "version": "2.0",
                "prompt": {"template": "researcher.txt", "variables": {"domain": "AI"}},
                "inference": {
                    "provider": "openai",
                    "model": "gpt-4",
                    "api_key": "test-key",
                    "temperature": 0.5,
                    "max_tokens": 4096
                },
                "tools": ["WebScraper"],
                "safety": {
                    "mode": "require_approval",
                    "require_approval_for_tools": ["FileWriter"],
                    "risk_level": "high"
                },
                "memory": {
                    "enabled": True,
                    "type": "vector",
                    "scope": "session",
                    "retrieval_k": 20
                },
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "max_retries": 5,
                    "fallback": "GracefulDegradation",
                    "escalate_to_human_after": 3
                },
                "merit_tracking": {
                    "enabled": True,
                    "track_decision_outcomes": True,
                    "domain_expertise": ["research", "analysis"]
                },
                "observability": {
                    "log_inputs": True,
                    "log_outputs": True,
                    "track_latency": True
                },
                "metadata": {
                    "tags": ["research", "external"],
                    "owner": "team_a"
                }
            }
        }
        config = AgentConfig(**config_dict)
        assert config.agent.name == "full_agent"
        assert config.agent.memory.enabled is True
        assert config.agent.safety.mode == "require_approval"


# ============================================
# TOOL SCHEMA TESTS
# ============================================

class TestToolConfig:
    """Tests for ToolConfig schema."""

    def test_valid_tool_config(self):
        """Test valid tool configuration."""
        config_dict = {
            "tool": {
                "name": "WebScraper",
                "description": "Web scraping tool",
                "version": "1.0",
                "implementation": "temper_ai.tools.web.WebScraperTool",
                "default_config": {
                    "max_pages": 10,
                    "timeout_seconds": 30
                }
            }
        }
        config = ToolConfig(**config_dict)
        assert config.tool.name == "WebScraper"
        assert config.tool.implementation == "temper_ai.tools.web.WebScraperTool"

    def test_tool_with_rate_limits(self):
        """Test tool config with rate limits."""
        config_dict = {
            "tool": {
                "name": "APITool",
                "description": "API tool",
                "implementation": "temper_ai.tools.api.APITool",
                "rate_limits": {
                    "max_calls_per_minute": 60,
                    "max_calls_per_hour": 1000,
                    "max_concurrent_requests": 5
                }
            }
        }
        config = ToolConfig(**config_dict)
        assert config.tool.rate_limits.max_calls_per_minute == 60
        assert config.tool.rate_limits.max_concurrent_requests == 5

    def test_tool_with_safety_checks(self):
        """Test tool config with safety checks."""
        config_dict = {
            "tool": {
                "name": "FileWriter",
                "description": "File writing tool",
                "implementation": "temper_ai.tools.file.FileWriterTool",
                "safety_checks": [
                    "PathTraversalPrevention",
                    {"name": "RateLimitEnforcement", "config": {"max_requests": 100}}
                ]
            }
        }
        config = ToolConfig(**config_dict)
        assert len(config.tool.safety_checks) == 2


# ============================================
# STAGE SCHEMA TESTS
# ============================================

class TestStageConfig:
    """Tests for StageConfig schema."""

    def test_valid_stage_config(self):
        """Test valid stage configuration."""
        config_dict = {
            "stage": {
                "name": "research",
                "description": "Research stage",
                "agents": ["market_researcher", "competitor_analyst"],
                "collaboration": {
                    "strategy": "DebateAndSynthesize",
                    "max_rounds": 3
                },
                "conflict_resolution": {
                    "strategy": "MeritWeighted"
                }
            }
        }
        config = StageConfig(**config_dict)
        assert config.stage.name == "research"
        assert len(config.stage.agents) == 2
        assert config.stage.collaboration.strategy == "DebateAndSynthesize"

    def test_stage_requires_at_least_one_agent(self):
        """Test that stage requires at least one agent."""
        config_dict = {
            "stage": {
                "name": "test",
                "description": "Test stage",
                "agents": [],
                "collaboration": {"strategy": "Test"},
                "conflict_resolution": {"strategy": "Test"}
            }
        }
        with pytest.raises(ValidationError) as exc_info:
            StageConfig(**config_dict)
        assert "At least one agent must be specified" in str(exc_info.value)

    def test_stage_with_execution_config(self):
        """Test stage with execution configuration."""
        config_dict = {
            "stage": {
                "name": "test",
                "description": "Test",
                "agents": ["agent1"],
                "execution": {
                    "agent_mode": "sequential",
                    "timeout_seconds": 300
                },
                "collaboration": {"strategy": "Test"},
                "conflict_resolution": {"strategy": "Test"}
            }
        }
        config = StageConfig(**config_dict)
        assert config.stage.execution.agent_mode == "sequential"
        assert config.stage.execution.timeout_seconds == 300


# ============================================
# WORKFLOW SCHEMA TESTS
# ============================================

class TestWorkflowConfig:
    """Tests for WorkflowConfig schema."""

    def test_valid_workflow_config(self):
        """Test valid workflow configuration."""
        config_dict = {
            "workflow": {
                "name": "mvp_lifecycle",
                "description": "MVP lifecycle workflow",
                "stages": [
                    {
                        "name": "research",
                        "stage_ref": "research_stage",
                        "depends_on": []
                    },
                    {
                        "name": "build",
                        "stage_ref": "build_stage",
                        "depends_on": ["research"]
                    }
                ],
                "error_handling": {
                    "on_stage_failure": "halt",
                    "escalation_policy": "HumanReview"
                }
            }
        }
        config = WorkflowConfig(**config_dict)
        assert config.workflow.name == "mvp_lifecycle"
        assert len(config.workflow.stages) == 2
        assert config.workflow.stages[1].depends_on == ["research"]

    def test_workflow_requires_at_least_one_stage(self):
        """Test that workflow requires at least one stage."""
        config_dict = {
            "workflow": {
                "name": "test",
                "description": "Test",
                "stages": [],
                "error_handling": {
                    "escalation_policy": "HumanReview"
                }
            }
        }
        with pytest.raises(ValidationError) as exc_info:
            WorkflowConfig(**config_dict)
        assert "At least one stage must be specified" in str(exc_info.value)

    def test_workflow_with_budget(self):
        """Test workflow with budget configuration."""
        config_dict = {
            "workflow": {
                "name": "test",
                "description": "Test",
                "stages": [{"name": "test", "stage_ref": "test_stage"}],
                "config": {
                    "budget": {
                        "max_cost_usd": 100.0,
                        "max_tokens": 1000000,
                        "action_on_exceed": "halt"
                    }
                },
                "error_handling": {
                    "escalation_policy": "HumanReview"
                }
            }
        }
        config = WorkflowConfig(**config_dict)
        assert config.workflow.config.budget.max_cost_usd == 100.0
        assert config.workflow.config.budget.max_tokens == 1000000


# ============================================
# TRIGGER SCHEMA TESTS
# ============================================

class TestEventTrigger:
    """Tests for EventTrigger schema."""

    def test_valid_event_trigger(self):
        """Test valid event trigger configuration."""
        config_dict = {
            "trigger": {
                "name": "feedback_processor",
                "description": "Process feedback events",
                "type": "EventTrigger",
                "source": {
                    "type": "message_queue",
                    "queue_name": "user_feedback"
                },
                "filter": {
                    "event_type": "new_feedback",
                    "conditions": [
                        {
                            "field": "sentiment",
                            "operator": "in",
                            "values": ["negative", "neutral"]
                        }
                    ]
                },
                "workflow": "feedback_workflow"
            }
        }
        config = EventTrigger(**config_dict)
        assert config.trigger.name == "feedback_processor"
        assert config.trigger.type == "EventTrigger"
        assert config.trigger.source.type == "message_queue"


class TestCronTrigger:
    """Tests for CronTrigger schema."""

    def test_valid_cron_trigger(self):
        """Test valid cron trigger configuration."""
        config_dict = {
            "trigger": {
                "name": "weekly_optimization",
                "description": "Weekly optimization job",
                "type": "CronTrigger",
                "schedule": "0 0 * * 0",
                "timezone": "UTC",
                "workflow": "optimization_workflow"
            }
        }
        config = CronTrigger(**config_dict)
        assert config.trigger.name == "weekly_optimization"
        assert config.trigger.schedule == "0 0 * * 0"
        assert config.trigger.timezone == "UTC"


class TestThresholdTrigger:
    """Tests for ThresholdTrigger schema."""

    def test_valid_threshold_trigger(self):
        """Test valid threshold trigger configuration."""
        config_dict = {
            "trigger": {
                "name": "error_rate_alert",
                "description": "Alert on high error rate",
                "type": "ThresholdTrigger",
                "metric": {
                    "source": "prometheus",
                    "query": "rate(http_errors_total[5m])",
                    "evaluation_interval_seconds": 60
                },
                "condition": "greater_than",
                "threshold": 0.05,
                "duration_minutes": 10,
                "workflow": "incident_response"
            }
        }
        config = ThresholdTrigger(**config_dict)
        assert config.trigger.name == "error_rate_alert"
        assert config.trigger.condition == "greater_than"
        assert config.trigger.threshold == 0.05


# ============================================
# M3 COLLABORATION TESTS
# ============================================

class TestConflictResolutionConfig:
    """Tests for M3 conflict resolution configuration."""

    def test_minimal_config(self):
        """Test minimal valid conflict resolution config."""
        config = ConflictResolutionConfig(strategy="HighestConfidence")
        assert config.strategy == "HighestConfidence"
        assert config.metrics == ["confidence"]  # default
        assert config.metric_weights == {}  # default
        assert config.auto_resolve_threshold == 0.85  # default
        assert config.escalation_threshold == 0.50  # default
        assert config.config == {}  # default

    def test_full_config_with_all_fields(self):
        """Test conflict resolution config with all fields specified."""
        config = ConflictResolutionConfig(
            strategy="MeritWeighted",
            metrics=["confidence", "merit", "recency"],
            metric_weights={"confidence": 0.4, "merit": 0.4, "recency": 0.2},
            auto_resolve_threshold=0.90,
            escalation_threshold=0.40,
            config={"enable_logging": True}
        )
        assert config.strategy == "MeritWeighted"
        assert config.metrics == ["confidence", "merit", "recency"]
        assert config.metric_weights == {"confidence": 0.4, "merit": 0.4, "recency": 0.2}
        assert config.auto_resolve_threshold == 0.90
        assert config.escalation_threshold == 0.40
        assert config.config["enable_logging"] is True

    def test_threshold_validation_escalation_higher_than_auto(self):
        """Test that escalation_threshold cannot exceed auto_resolve_threshold."""
        with pytest.raises(ValidationError) as exc_info:
            ConflictResolutionConfig(
                strategy="MeritWeighted",
                auto_resolve_threshold=0.70,
                escalation_threshold=0.80  # Invalid: higher than auto_resolve
            )
        assert "escalation_threshold" in str(exc_info.value).lower()

    def test_threshold_validation_equal_is_valid(self):
        """Test that equal thresholds are valid (edge case)."""
        config = ConflictResolutionConfig(
            strategy="MeritWeighted",
            auto_resolve_threshold=0.75,
            escalation_threshold=0.75  # Valid: equal
        )
        assert config.auto_resolve_threshold == 0.75
        assert config.escalation_threshold == 0.75

    def test_threshold_bounds_validation(self):
        """Test threshold bounds (must be 0.0-1.0)."""
        # Test auto_resolve_threshold lower bound
        with pytest.raises(ValidationError):
            ConflictResolutionConfig(
                strategy="Test",
                auto_resolve_threshold=-0.1
            )

        # Test auto_resolve_threshold upper bound
        with pytest.raises(ValidationError):
            ConflictResolutionConfig(
                strategy="Test",
                auto_resolve_threshold=1.1
            )

        # Test escalation_threshold bounds
        with pytest.raises(ValidationError):
            ConflictResolutionConfig(
                strategy="Test",
                escalation_threshold=-0.1
            )

        with pytest.raises(ValidationError):
            ConflictResolutionConfig(
                strategy="Test",
                escalation_threshold=1.1
            )

    def test_metric_weights_validation_negative(self):
        """Test that negative metric weights are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ConflictResolutionConfig(
                strategy="MeritWeighted",
                metric_weights={"confidence": 0.5, "merit": -0.3}
            )
        assert "negative" in str(exc_info.value).lower()

    def test_metric_weights_validation_zero_is_valid(self):
        """Test that zero weights are valid (metric disabled)."""
        config = ConflictResolutionConfig(
            strategy="MeritWeighted",
            metric_weights={"confidence": 1.0, "merit": 0.0}  # Valid
        )
        assert config.metric_weights["merit"] == 0.0

    def test_metric_weights_validation_positive(self):
        """Test that positive metric weights are valid."""
        config = ConflictResolutionConfig(
            strategy="MeritWeighted",
            metric_weights={"confidence": 0.6, "merit": 0.3, "recency": 0.1}
        )
        assert sum(config.metric_weights.values()) == 1.0

    def test_metrics_list_custom(self):
        """Test custom metrics list."""
        config = ConflictResolutionConfig(
            strategy="Custom",
            metrics=["domain_expertise", "historical_accuracy", "response_time"]
        )
        assert len(config.metrics) == 3
        assert "domain_expertise" in config.metrics

    def test_config_passthrough(self):
        """Test that additional config is passed through."""
        config = ConflictResolutionConfig(
            strategy="HighestConfidence",
            config={
                "tie_breaker": "random",
                "enable_caching": True,
                "timeout_ms": 5000
            }
        )
        assert config.config["tie_breaker"] == "random"
        assert config.config["enable_caching"] is True
        assert config.config["timeout_ms"] == 5000

    def test_realistic_merit_weighted_config(self):
        """Test realistic merit-weighted configuration."""
        config = ConflictResolutionConfig(
            strategy="MeritWeighted",
            metrics=["confidence", "merit", "recency"],
            metric_weights={
                "confidence": 0.5,
                "merit": 0.3,
                "recency": 0.2
            },
            auto_resolve_threshold=0.85,
            escalation_threshold=0.50,
            config={
                "merit_decay_days": 30,
                "require_unanimous": False
            }
        )
        assert config.strategy == "MeritWeighted"
        assert len(config.metrics) == 3
        assert config.metric_weights["confidence"] == 0.5


class TestCollaborationConfig:
    """Tests for M3 collaboration strategy configuration."""

    def test_minimal_collaboration_config(self):
        """Test minimal collaboration config."""
        config = CollaborationConfig(strategy="Consensus")
        assert config.strategy == "Consensus"
        assert config.config == {}  # default

    def test_debate_collaboration_config(self):
        """Test debate collaboration configuration."""
        config = CollaborationConfig(
            strategy="DebateAndSynthesize",
            config={
                "max_rounds": 5,
                "convergence_threshold": 0.80,
                "min_rounds": 2
            }
        )
        assert config.strategy == "DebateAndSynthesize"
        assert config.config["max_rounds"] == 5
        assert config.config["convergence_threshold"] == 0.80


# ============================================
# ENUM AND TYPE VALIDATION TESTS
# ============================================

class TestEnumValidation:
    """Tests for enum validation across all schemas."""

    def test_invalid_agent_mode(self):
        """Test invalid agent_mode in stage execution."""
        with pytest.raises(ValidationError):
            StageExecutionConfig(agent_mode="invalid")

    def test_invalid_safety_mode(self):
        """Test invalid safety mode."""
        with pytest.raises(ValidationError):
            SafetyConfig(mode="invalid")

    def test_invalid_workflow_error_handling(self):
        """Test invalid error handling mode."""
        with pytest.raises(ValidationError):
            WorkflowErrorHandlingConfig(
                on_stage_failure="invalid",
                escalation_policy="Test"
            )


# ============================================
# DEFAULT VALUE TESTS
# ============================================

class TestDefaultValues:
    """Tests for default values across schemas."""

    def test_inference_config_defaults(self):
        """Test inference config defaults."""
        config = InferenceConfig(provider="ollama", model="test")
        assert config.temperature == 0.7
        assert config.max_tokens == 131072
        assert config.top_p == 0.9
        assert config.timeout_seconds == 1800  # 30 minutes default for LLM calls
        assert config.max_retries == 3

    def test_safety_config_defaults(self):
        """Test safety config defaults."""
        config = SafetyConfig()
        assert config.mode == "execute"
        assert config.require_approval_for_tools == []
        assert config.max_tool_calls_per_execution == 20
        assert config.risk_level == "medium"

    def test_stage_execution_defaults(self):
        """Test stage execution defaults."""
        config = StageExecutionConfig()
        assert config.agent_mode == "parallel"
        assert config.timeout_seconds == 1800  # 30 minutes default

    def test_workflow_observability_defaults(self):
        """Test workflow observability defaults."""
        config = WorkflowObservabilityConfig()
        assert config.console_mode == "standard"
        assert config.trace_everything is True
        assert config.export_format == ["json", "sqlite"]


# ============================================
# INTEGRATION TESTS
# ============================================

class TestSchemaIntegration:
    """Integration tests using complete config examples."""

    def test_complete_agent_workflow(self):
        """Test complete agent configuration from spec."""
        agent_config = {
            "agent": {
                "name": "market_researcher",
                "description": "Market research agent",
                "version": "1.0",
                "prompt": {
                    "template": "prompts/researcher_base.txt",
                    "variables": {"domain": "SaaS", "tone": "analytical"}
                },
                "inference": {
                    "provider": "ollama",
                    "model": "llama3.2:3b",
                    "base_url": "http://localhost:11434",
                    "temperature": 0.7,
                    "max_tokens": 2048
                },
                "tools": [
                    "WebScraper",
                    {"name": "DatabaseQuery", "config": {"max_rows": 1000}}
                ],
                "safety": {
                    "mode": "execute",
                    "max_tool_calls_per_execution": 20,
                    "risk_level": "medium"
                },
                "memory": {
                    "enabled": False
                },
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "max_retries": 3,
                    "fallback": "GracefulDegradation",
                    "escalate_to_human_after": 3
                }
            }
        }

        config = AgentConfig(**agent_config)
        assert config.agent.name == "market_researcher"
        assert config.agent.inference.provider == "ollama"
        assert len(config.agent.tools) == 2
        assert config.agent.safety.mode == "execute"

    def test_complete_workflow_from_spec(self):
        """Test complete workflow configuration from spec."""
        workflow_config = {
            "workflow": {
                "name": "mvp_lifecycle",
                "description": "MVP development lifecycle",
                "version": "1.0",
                "product_type": "web_app",
                "stages": [
                    {
                        "name": "research",
                        "stage_ref": "research_stage",
                        "depends_on": []
                    },
                    {
                        "name": "requirements",
                        "stage_ref": "requirements_stage",
                        "depends_on": ["research"]
                    },
                    {
                        "name": "build",
                        "stage_ref": "build_stage",
                        "depends_on": ["requirements"]
                    }
                ],
                "config": {
                    "max_iterations": 5,
                    "timeout_seconds": 3600,
                    "budget": {
                        "max_cost_usd": 100.0,
                        "action_on_exceed": "halt"
                    }
                },
                "safety": {
                    "composition_strategy": "MostRestrictive",
                    "global_mode": "execute",
                    "approval_required_stages": ["build"]
                },
                "observability": {
                    "console_mode": "standard",
                    "trace_everything": True
                },
                "error_handling": {
                    "on_stage_failure": "halt",
                    "max_stage_retries": 2,
                    "escalation_policy": "HumanReview"
                }
            }
        }

        config = WorkflowConfig(**workflow_config)
        assert config.workflow.name == "mvp_lifecycle"
        assert len(config.workflow.stages) == 3
        assert config.workflow.config.budget.max_cost_usd == 100.0
        assert config.workflow.safety.approval_required_stages == ["build"]
