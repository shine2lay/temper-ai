"""File access policy — restrict file operations to allowed/denied paths."""

from __future__ import annotations

from typing import Any

from temper_ai.safety.base import ActionType, BasePolicy, PolicyDecision


class FileAccessPolicy(BasePolicy):
    """Restrict file operations to allowed paths and block denied paths.

    Config:
        type: file_access
        allowed_paths: ["/workspace"]        # only these paths allowed (if set)
        denied_paths: [".env", "credentials"] # these patterns always blocked
    """

    action_types = [ActionType.TOOL_CALL]

    @classmethod
    def validate_config(cls, config: dict) -> list[str]:
        errors = super().validate_config(config)
        if not config.get("denied_paths") and not config.get("allowed_paths"):
            errors.append("FileAccessPolicy needs 'denied_paths' or 'allowed_paths'")
        return errors

    def __init__(self, config: dict):
        super().__init__(config)
        self.allowed_paths: list[str] = config.get("allowed_paths", [])
        self.denied_paths: list[str] = config.get("denied_paths", [
            ".env", "credentials", "/etc/", "/root/",
        ])

    def evaluate(
        self,
        action_type: ActionType,
        action_data: dict[str, Any],
        context: dict[str, Any],
    ) -> PolicyDecision:
        tool_name = action_data.get("tool_name", "")
        tool_params = action_data.get("tool_params", {})

        # Only check file-related tools
        if tool_name.lower() not in ("bash", "file_writer", "filewriter", "fileedit", "file_edit", "fileappend", "file_append", "git"):
            return PolicyDecision(
                action="allow", reason="Not a file tool", policy_name=self.name,
            )

        # Extract paths from params
        target_path = (
            tool_params.get("file_path")
            or tool_params.get("path")
            or tool_params.get("command", "")
        )

        # Check denied paths
        for denied in self.denied_paths:
            if denied in str(target_path):
                return PolicyDecision(
                    action="deny",
                    reason=f"Access to '{target_path}' blocked (matches denied pattern '{denied}')",
                    policy_name=self.name,
                )

        # Check allowed paths (if configured)
        if self.allowed_paths:
            if not any(str(target_path).startswith(a) for a in self.allowed_paths):
                return PolicyDecision(
                    action="deny",
                    reason=f"Path '{target_path}' not in allowed paths: {self.allowed_paths}",
                    policy_name=self.name,
                )

        return PolicyDecision(
            action="allow", reason="Path allowed", policy_name=self.name,
        )
