"""
Data models for M5 Self-Improvement system.

Contains models for agent configuration, performance profiles, improvement proposals,
experiments, and deployment tracking.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List


@dataclass
class AgentConfig:
    """
    Agent configuration data model.

    Represents the configurable parameters for an agent that M5 can optimize.
    This includes inference settings, prompt configuration, and tool settings.

    Used by:
    - ImprovementStrategy to generate config variants
    - ExperimentOrchestrator to test different configurations
    - ConfigDeployer to deploy winning configurations
    """

    # Identity
    agent_name: str
    agent_version: str = "1.0.0"

    # Inference configuration
    inference: Dict[str, Any] = field(default_factory=lambda: {
        "provider": "ollama",
        "model": "llama3.1:8b",
        "temperature": 0.7,
        "max_tokens": 2048,
        "top_p": 0.9,
        "base_url": None,
    })

    # Prompt configuration
    prompt: Dict[str, Any] = field(default_factory=lambda: {
        "template": None,
        "include_examples": False,
        "num_examples": 0,
        "include_reasoning_guide": False,
        "include_citations": False,
        "require_source_verification": False,
        "sections": [],
    })

    # Tool configuration
    tools: Dict[str, Any] = field(default_factory=lambda: {
        "enabled_tools": [],
        "tool_timeout_seconds": 60,
        "max_retries": 3,
        "safety_checks": True,
    })

    # Caching configuration
    caching: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": False,
        "cache_type": "memory",
        "ttl_seconds": 3600,
    })

    # Retry configuration
    retry: Dict[str, Any] = field(default_factory=lambda: {
        "max_retries": 3,
        "backoff_multiplier": 2,
        "initial_delay_seconds": 1,
    })

    # Metadata
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def copy(self) -> "AgentConfig":
        """Create a deep copy of this config for generating variants."""
        import copy
        return AgentConfig(
            agent_name=self.agent_name,
            agent_version=self.agent_version,
            inference=copy.deepcopy(self.inference),
            prompt=copy.deepcopy(self.prompt),
            tools=copy.deepcopy(self.tools),
            caching=copy.deepcopy(self.caching),
            retry=copy.deepcopy(self.retry),
            extra_metadata=copy.deepcopy(self.extra_metadata),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "agent_name": self.agent_name,
            "agent_version": self.agent_version,
            "inference": self.inference,
            "prompt": self.prompt,
            "tools": self.tools,
            "caching": self.caching,
            "retry": self.retry,
            "extra_metadata": self.extra_metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        """Load from dictionary (e.g., from database)."""
        return cls(
            agent_name=data["agent_name"],
            agent_version=data.get("agent_version", "1.0.0"),
            inference=data.get("inference", {}),
            prompt=data.get("prompt", {}),
            tools=data.get("tools", {}),
            caching=data.get("caching", {}),
            retry=data.get("retry", {}),
            extra_metadata=data.get("extra_metadata", {}),
        )
