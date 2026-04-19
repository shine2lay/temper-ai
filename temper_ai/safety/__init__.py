"""Safety module — composable policy enforcement.

Policies evaluate actions (tool calls, workflow starts, agent outputs)
and return allow/deny/modify decisions. The PolicyEngine runs all
active policies before an action executes.

Usage:
    from temper_ai.safety import PolicyEngine, ActionType

    engine = PolicyEngine.from_config(workflow_safety_config)
    decision = engine.evaluate(ActionType.TOOL_CALL, {"tool_name": "bash", ...}, context)
    if decision.action == "deny":
        # blocked by safety policy
"""

from temper_ai.safety.base import ActionType, BasePolicy, PolicyDecision
from temper_ai.safety.budget import BudgetPolicy
from temper_ai.safety.engine import PolicyEngine, register_policy
from temper_ai.safety.file_access import FileAccessPolicy
from temper_ai.safety.forbidden_ops import ForbiddenOpsPolicy

# Register built-in policies
register_policy("file_access", FileAccessPolicy)
register_policy("forbidden_ops", ForbiddenOpsPolicy)
register_policy("budget", BudgetPolicy)

__all__ = [
    "ActionType",
    "BasePolicy",
    "PolicyDecision",
    "PolicyEngine",
    "register_policy",
    "FileAccessPolicy",
    "ForbiddenOpsPolicy",
    "BudgetPolicy",
]
