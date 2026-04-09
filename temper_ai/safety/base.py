"""Base policy class and shared types for the safety module.

Each policy:
- Declares which ActionTypes it handles via `action_types`
- Implements `evaluate()` to return allow/deny/modify decisions
- Has `validate_config()` for compile-time validation
- Validates its own config in `__init__` for runtime safety
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from temper_ai.safety.exceptions import SafetyConfigError


class ActionType(StrEnum):
    """Types of actions that policies can evaluate.

    v1 only wires TOOL_CALL. Others are defined for forward
    compatibility — policies can declare them, and the engine
    will evaluate them when the calling code adds the hook.
    """

    TOOL_CALL = "tool_call"
    LLM_CALL = "llm_call"
    WORKFLOW_START = "workflow_start"
    WORKFLOW_END = "workflow_end"
    AGENT_OUTPUT = "agent_output"


@dataclass
class PolicyDecision:
    """Result of a policy evaluation."""

    action: str  # "allow", "deny", "modify"
    reason: str
    policy_name: str
    modified_params: dict[str, Any] | None = None  # If action == "modify"


class BasePolicy(ABC):
    """Base class for all safety policies.

    Subclasses must:
    - Set `action_types` to declare which actions they evaluate
    - Implement `evaluate()` to return a PolicyDecision
    - Override `validate_config()` to check required fields
    """

    # Which action types this policy handles.
    # The engine skips policies that don't handle the current action type.
    action_types: list[ActionType] = [ActionType.TOOL_CALL]

    def __init__(self, config: dict):
        errors = self.validate_config(config)
        if errors:
            raise SafetyConfigError(
                f"Invalid {self.__class__.__name__} config: {'; '.join(errors)}"
            )
        self.config = config
        self.name = config.get("name", self.__class__.__name__)
        self.enabled = config.get("enabled", True)

    @classmethod
    def validate_config(cls, config: dict) -> list[str]:
        """Validate config at compile time. Returns list of errors.

        Override in subclasses to check required fields.
        Called both at workflow load time (without instantiation)
        and in __init__ (with instantiation).
        """
        errors = []
        if not config.get("type"):
            errors.append("Policy config must have 'type'")
        return errors

    @abstractmethod
    def evaluate(
        self,
        action_type: ActionType,
        action_data: dict[str, Any],
        context: dict[str, Any],
    ) -> PolicyDecision:
        """Evaluate whether an action should be allowed.

        Args:
            action_type: What kind of action (TOOL_CALL, WORKFLOW_START, etc.)
            action_data: Action-specific data (e.g., tool_name, tool_params for TOOL_CALL)
            context: Execution context (run_id, agent_name, accumulated cost, etc.)

        Returns:
            PolicyDecision with action="allow", "deny", or "modify".
        """
        ...
