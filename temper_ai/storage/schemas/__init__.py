"""Shared schema definitions for cross-module use.

This package contains Pydantic schemas that are referenced by multiple
top-level packages (e.g. ``temper_ai.agent`` and ``temper_ai.workflow``).  Keeping
them here avoids a bidirectional dependency between agents and compiler.

Re-exports from sub-modules for convenience::

    from temper_ai.storage.schemas import AgentConfig, AgentConfigInner, InferenceConfig
"""

from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    MemoryConfig,
    MeritTrackingConfig,
    MetadataConfig,
    ObservabilityConfig,
    PromptConfig,
    RetryConfig,
    SafetyConfig,
    ToolReference,
)

__all__ = [
    "AgentConfig",
    "AgentConfigInner",
    "ErrorHandlingConfig",
    "InferenceConfig",
    "MemoryConfig",
    "MeritTrackingConfig",
    "MetadataConfig",
    "ObservabilityConfig",
    "PromptConfig",
    "RetryConfig",
    "SafetyConfig",
    "ToolReference",
]
