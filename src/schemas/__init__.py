"""Shared schema definitions for cross-module use.

This package contains Pydantic schemas that are referenced by multiple
top-level packages (e.g. ``src.agents`` and ``src.compiler``).  Keeping
them here avoids a bidirectional dependency between agents and compiler.

Re-exports from sub-modules for convenience::

    from src.schemas import AgentConfig, AgentConfigInner, InferenceConfig
"""
from src.schemas.agent_config import (
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
