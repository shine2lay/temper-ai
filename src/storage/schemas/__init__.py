"""Shared schema definitions for cross-module use.

This package contains Pydantic schemas that are referenced by multiple
top-level packages (e.g. ``src.agent`` and ``src.workflow``).  Keeping
them here avoids a bidirectional dependency between agents and compiler.

Re-exports from sub-modules for convenience::

    from src.storage.schemas import AgentConfig, AgentConfigInner, InferenceConfig
"""
from src.storage.schemas.agent_config import (
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
