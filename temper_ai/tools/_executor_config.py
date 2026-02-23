"""Configuration dataclass for ToolExecutor to reduce parameter count."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from temper_ai.shared.constants.durations import (
    DEFAULT_TIMEOUT_SECONDS,
    RATE_LIMIT_WINDOW_SECOND,
)
from temper_ai.shared.constants.limits import MIN_WORKERS

if TYPE_CHECKING:
    from temper_ai.safety.action_policy_engine import ActionPolicyEngine
    from temper_ai.safety.approval import ApprovalWorkflow
    from temper_ai.safety.rollback import RollbackManager


@dataclass
class ToolExecutorConfig:
    """Configuration for ToolExecutor initialization.

    Bundles all optional configuration parameters to reduce __init__ param count.
    """

    default_timeout: int = DEFAULT_TIMEOUT_SECONDS
    max_workers: int = MIN_WORKERS
    max_concurrent: int | None = None
    rate_limit: int | None = None
    rate_window: float = RATE_LIMIT_WINDOW_SECOND
    rollback_manager: RollbackManager | None = None
    policy_engine: ActionPolicyEngine | None = None
    approval_workflow: ApprovalWorkflow | None = None
    enable_auto_rollback: bool = True
    workspace_root: str | None = None
    enable_tool_cache: bool = False
    tool_cache_max_size: int | None = None
    tool_cache_ttl: int | None = None

    @property
    def workspace_path(self) -> Path | None:
        """Return workspace_root as Path if set."""
        return Path(self.workspace_root) if self.workspace_root else None
