"""
Configuration compiler and loader for Meta-Autonomous Framework.

This module handles loading, validating, and compiling YAML/JSON configurations
into executable LangGraph workflows.

New in M3.2-05: Domain state and execution context separation for checkpoint/resume.
New in M3.2-06: Checkpoint/resume capability for long-running workflows.
"""
from src.compiler.checkpoint_backends import (
    CheckpointBackend,
    CheckpointNotFoundError,
    FileCheckpointBackend,
    RedisCheckpointBackend,
)
from src.compiler.checkpoint_manager import (
    CheckpointLoadError,
    CheckpointManager,
    CheckpointSaveError,
    CheckpointStrategy,
    create_checkpoint_manager,
)
from src.compiler.config_loader import (
    ConfigLoader,
    ConfigNotFoundError,
    ConfigValidationError,
)
from src.compiler.domain_state import (
    DomainExecutionContext,
    InfrastructureContext,
    WorkflowDomainState,
    create_initial_domain_state,
    merge_domain_states,
)

# Note: LangGraphCompiler not imported here to avoid circular imports
# Import directly: from src.compiler.langgraph_compiler import LangGraphCompiler

# Note: WorkflowState in src/compiler/state.py is deprecated.
# Use WorkflowDomainState + InfrastructureContext from src/compiler/domain_state.py.
# DomainExecutionContext replaces the old ExecutionContext alias (which collided
# with src.core.context.ExecutionContext).

__all__ = [
    "ConfigLoader",
    "ConfigNotFoundError",
    "ConfigValidationError",
    "WorkflowDomainState",
    "InfrastructureContext",
    "DomainExecutionContext",
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
