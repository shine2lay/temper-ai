"""Forbidden operations policy — block dangerous shell commands."""

from __future__ import annotations

import re
from typing import Any

from temper_ai.safety.base import ActionType, BasePolicy, PolicyDecision

# What a node in the server or worker container can reach through Bash that
# no workflow has any business touching: the host's docker socket (root on
# the host, when it is mounted), credential files mounted for a provider,
# and the environment of the process that holds the API keys. The path
# check does not see Bash and the env scrub only covers Bash's own child,
# so these are the tripwires PolicyEngine.for_run() gives every run.
# Substring/regex on the command text: a tripwire, not a boundary — an
# attempt is refused and recorded, not made impossible.
PLATFORM_TRIPWIRE_PATTERNS = [
    "/var/run/docker.sock",
    ".credentials.json",
]
PLATFORM_TRIPWIRE_REGEXES = [
    r"/proc/[^/\s]+/environ",  # /proc/1/environ, /proc/<pid>/environ
]

_BARE_WORD = re.compile(r"^\w+$")


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """A forbidden pattern as a regex: substring, or whole word when the
    pattern is one bare word (see the class docstring)."""
    escaped = re.escape(pattern)
    if _BARE_WORD.match(pattern):
        escaped = rf"(?<!\w){escaped}(?!\w)"
    return re.compile(escaped, re.IGNORECASE)


class ForbiddenOpsPolicy(BasePolicy):
    """Block shell commands matching dangerous patterns.

    Config:
        type: forbidden_ops
        forbidden_patterns: ["rm -rf", "DROP TABLE", ...]  # optional, has defaults
        forbidden_regexes: ["/proc/\\S+/environ"]           # optional, case-insensitive

    A pattern matches the command text case-insensitively as a substring,
    except that a bare word (letters, digits, underscore only: TRUNCATE,
    mkfs) must match a whole word. The first `platform_baseline` blocked
    every epd_task run at stack_up because that agent's script has a
    comment saying a long name is "silently truncated"; "truncated" is not
    a TRUNCATE. Patterns with spaces or punctuation ("rm -rf /", "> /dev/sd")
    keep matching as prefixes/substrings, since that is what they are for.
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
        for pattern in config.get("forbidden_regexes", []):
            try:
                re.compile(pattern)
            except re.error as exc:
                errors.append(f"forbidden_regexes entry {pattern!r} is not a valid regex: {exc}")
        return errors

    def __init__(self, config: dict):
        super().__init__(config)
        self.forbidden_patterns: list[str] = config.get(
            "forbidden_patterns", self.DEFAULT_FORBIDDEN
        )
        self._pattern_regexes: list[tuple[str, re.Pattern[str]]] = [
            (pattern, _pattern_regex(pattern)) for pattern in self.forbidden_patterns
        ]
        self.forbidden_regexes: list[re.Pattern[str]] = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in config.get("forbidden_regexes", [])
        ]

    def evaluate(
        self,
        action_type: ActionType,
        action_data: dict[str, Any],
        context: dict[str, Any],
    ) -> PolicyDecision:
        tool_name = action_data.get("tool_name", "")
        tool_params = action_data.get("tool_params", {})

        # Only check bash/shell tools
        if tool_name.lower() not in ("bash", "git"):
            return PolicyDecision(
                action="allow", reason="Not a shell tool", policy_name=self.name,
            )

        command = tool_params.get("command", "")

        for pattern, regex in self._pattern_regexes:
            if regex.search(command):
                return PolicyDecision(
                    action="deny",
                    reason=f"Command contains forbidden pattern: '{pattern}'",
                    policy_name=self.name,
                )

        for regex in self.forbidden_regexes:
            if regex.search(command):
                return PolicyDecision(
                    action="deny",
                    reason=f"Command matches forbidden pattern: '{regex.pattern}'",
                    policy_name=self.name,
                )

        return PolicyDecision(
            action="allow", reason="Command allowed", policy_name=self.name,
        )
