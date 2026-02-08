"""
AgentPathValidator for M5 Self-Improvement System.

Validates agent names and generates safe filesystem paths.
Extracted from PerformanceAnalyzer to follow Single Responsibility Principle.

Design Principles:
- Security-first (path traversal prevention)
- Allowlist validation (regex pattern)
- Symlink detection
- Clear error messages
"""

import re
from pathlib import Path


class AgentPathValidator:
    """
    Validates agent names and generates safe paths within a base directory.

    Security features:
    - Allowlist regex pattern (alphanumerics, hyphens, underscores)
    - Path containment verification
    - Symlink detection
    - Length limit (64 chars)

    Example:
        >>> validator = AgentPathValidator(Path(".baselines"))
        >>> path = validator.validate_and_resolve("my_agent")
        >>> print(path)  # .baselines/my_agent_baseline.json
    """

    # Allowlist: starts with letter, alphanumerics/hyphens/underscores, max 64 chars
    _AGENT_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,63}$')

    def __init__(self, base_path: Path):
        """
        Initialize validator with base directory.

        Args:
            base_path: Base directory for path resolution
        """
        self.base_path = base_path.resolve()

    def validate_and_resolve(self, agent_name: str) -> Path:
        """
        Validate agent name and return safe path within base_path.

        Args:
            agent_name: Name of agent to validate

        Returns:
            Resolved Path guaranteed to be within base_path

        Raises:
            ValueError: If agent_name is invalid or path escapes base_path

        Example:
            >>> validator = AgentPathValidator(Path(".baselines"))
            >>> path = validator.validate_and_resolve("code_review_agent")
            >>> # Returns: /absolute/path/.baselines/code_review_agent_baseline.json
        """
        # Type check
        if not isinstance(agent_name, str):
            raise ValueError("Invalid agent name")

        # Pattern validation
        if not self._AGENT_NAME_PATTERN.match(agent_name):
            raise ValueError(
                "Invalid agent name: must start with a letter, "
                "contain only alphanumerics, hyphens, or underscores, "
                "and be at most 64 characters"
            )

        # Generate baseline file path
        baseline_file = self.base_path / f"{agent_name}_baseline.json"
        resolved = baseline_file.resolve()

        # Containment check: ensure resolved path is within base_path
        try:
            resolved.relative_to(self.base_path)
        except ValueError:
            raise ValueError("Invalid agent name: path escape detected")

        # Reject symlinks pointing outside storage
        if baseline_file.is_symlink():
            raise ValueError("Invalid agent name: symlink detected")

        return resolved

    @staticmethod
    def is_valid_agent_name(name: str) -> bool:
        """
        Check if name passes allowlist pattern.

        Args:
            name: Agent name to check

        Returns:
            True if valid, False otherwise

        Example:
            >>> AgentPathValidator.is_valid_agent_name("my_agent")
            True
            >>> AgentPathValidator.is_valid_agent_name("../etc/passwd")
            False
        """
        if not isinstance(name, str):
            return False  # type: ignore[unreachable]
        return bool(AgentPathValidator._AGENT_NAME_PATTERN.match(name))
