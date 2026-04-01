"""Forbidden operations policy — block dangerous shell commands."""

from __future__ import annotations

from typing import Any

from temper_ai.safety.base import ActionType, BasePolicy, PolicyDecision


class ForbiddenOpsPolicy(BasePolicy):
    """Block shell commands matching dangerous patterns.

    Config:
        type: forbidden_ops
        forbidden_patterns: ["rm -rf", "DROP TABLE", ...]  # optional, has defaults
    """

    action_types = [ActionType.TOOL_CALL]

    DEFAULT_FORBIDDEN = [
        "rm -rf /", "rm -rf ~", "rm -rf .",
        "DROP TABLE", "DROP DATABASE", "TRUNCATE",
        "mkfs", "dd if=", "> /dev/sd",
        "chmod 777", "curl | sh", "wget | sh",
        "curl | bash", "wget | bash",
    ]

    @classmethod
    def validate_config(cls, config: dict) -> list[str]:
        errors = super().validate_config(config)
        # No required fields beyond type — uses defaults if patterns not specified
        return errors

    def __init__(self, config: dict):
        super().__init__(config)
        self.forbidden_patterns: list[str] = config.get(
            "forbidden_patterns", self.DEFAULT_FORBIDDEN
        )

    def evaluate(
        self,
        action_type: ActionType,
        action_data: dict[str, Any],
        context: dict[str, Any],
    ) -> PolicyDecision:
        tool_name = action_data.get("tool_name", "")
        tool_params = action_data.get("tool_params", {})

        # Only check bash/shell tools
        if tool_name.lower() not in ("bash",):
            return PolicyDecision(
                action="allow", reason="Not a shell tool", policy_name=self.name,
            )

        command = tool_params.get("command", "")

        for pattern in self.forbidden_patterns:
            if pattern.lower() in command.lower():
                return PolicyDecision(
                    action="deny",
                    reason=f"Command contains forbidden pattern: '{pattern}'",
                    policy_name=self.name,
                )

        return PolicyDecision(
            action="allow", reason="Command allowed", policy_name=self.name,
        )
