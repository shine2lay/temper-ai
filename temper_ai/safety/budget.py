"""Budget policy — enforce cost and token limits per workflow run.

Evaluates at TOOL_CALL (check before each tool call) and
WORKFLOW_START (validate budget is configured).
"""

from __future__ import annotations

from typing import Any

from temper_ai.safety.base import ActionType, BasePolicy, PolicyDecision


class BudgetPolicy(BasePolicy):
    """Enforce cost and token limits for a workflow run.

    Checks accumulated cost/tokens from context before allowing
    further tool calls. The executor passes running totals in context.

    Config:
        type: budget
        max_cost_usd: 1.00     # max total cost for the run
        max_tokens: 100000     # max total tokens for the run
    """

    action_types = [ActionType.TOOL_CALL, ActionType.LLM_CALL, ActionType.WORKFLOW_START]

    @classmethod
    def validate_config(cls, config: dict) -> list[str]:
        errors = super().validate_config(config)
        max_cost = config.get("max_cost_usd")
        max_tokens = config.get("max_tokens")
        if max_cost is None and max_tokens is None:
            errors.append("BudgetPolicy needs 'max_cost_usd' or 'max_tokens' (or both)")
        if max_cost is not None and max_cost <= 0:
            errors.append(f"max_cost_usd must be positive, got {max_cost}")
        if max_tokens is not None and max_tokens <= 0:
            errors.append(f"max_tokens must be positive, got {max_tokens}")
        return errors

    def __init__(self, config: dict):
        super().__init__(config)
        self.max_cost_usd: float | None = config.get("max_cost_usd")
        self.max_tokens: int | None = config.get("max_tokens")

    def evaluate(
        self,
        action_type: ActionType,
        action_data: dict[str, Any],
        context: dict[str, Any],
    ) -> PolicyDecision:
        if action_type == ActionType.WORKFLOW_START:
            # Just validate that budget is set — no cost accumulated yet
            return PolicyDecision(
                action="allow",
                reason=f"Budget configured: ${self.max_cost_usd} / {self.max_tokens} tokens",
                policy_name=self.name,
            )

        # TOOL_CALL: check accumulated cost/tokens from context
        current_cost = context.get("run_cost_usd", 0.0)
        current_tokens = context.get("run_tokens", 0)

        if self.max_cost_usd is not None and current_cost >= self.max_cost_usd:
            return PolicyDecision(
                action="deny",
                reason=f"Budget exceeded: ${current_cost:.4f} >= ${self.max_cost_usd:.2f}",
                policy_name=self.name,
            )

        if self.max_tokens is not None and current_tokens >= self.max_tokens:
            return PolicyDecision(
                action="deny",
                reason=f"Token limit exceeded: {current_tokens:,} >= {self.max_tokens:,}",
                policy_name=self.name,
            )

        return PolicyDecision(
            action="allow",
            reason="Within budget",
            policy_name=self.name,
        )
