"""
Configuration compiler and loader for Meta-Autonomous Framework.

This module handles loading, validating, and compiling YAML/JSON configurations
into executable LangGraph workflows.

New in M3.2-05: Domain state and execution context separation for checkpoint/resume.
New in M3.2-06: Checkpoint/resume capability for long-running workflows.
"""
from src.compiler.config_loader import (
    ConfigLoader,
    ConfigNotFoundError,
    ConfigValidationError,
)
from src.compiler.domain_state import (
    WorkflowDomainState,
    InfrastructureContext,
    create_initial_domain_state,
    merge_domain_states,
)

# Backward-compatible alias
ExecutionContext = InfrastructureContext
from src.compiler.checkpoint_manager import (
    CheckpointManager,
    CheckpointStrategy,
    CheckpointSaveError,
    CheckpointLoadError,
    create_checkpoint_manager,
)
from src.compiler.checkpoint_backends import (
    CheckpointBackend,
    FileCheckpointBackend,
    RedisCheckpointBackend,
    CheckpointNotFoundError,
)

# Note: LangGraphCompiler not imported here to avoid circular imports
# Import directly: from src.compiler.langgraph_compiler import LangGraphCompiler

# Note: WorkflowState in src/compiler/state.py is deprecated.
# Use WorkflowDomainState + InfrastructureContext from src/compiler/domain_state.py.
# ExecutionContext is a backward-compatible alias for InfrastructureContext.

__all__ = [
    "ConfigLoader",
    "ConfigNotFoundError",
    "ConfigValidationError",
    "WorkflowDomainState",
    "ExecutionContext",
    "create_initial_domain_state",
    "merge_domain_states",
    "CheckpointManager",
    "CheckpointStrategy",
    "CheckpointSaveError",
    "CheckpointLoadError",
    "create_checkpoint_manager",
    "CheckpointBackend",
    "FileCheckpointBackend",
    "RedisCheckpointBackend",
    "CheckpointNotFoundError",
]
