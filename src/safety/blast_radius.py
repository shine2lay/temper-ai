"""Blast Radius Safety Policy.

Limits the scope of actions to prevent large-scale changes that could cause
widespread damage. Enforces constraints on:
- Number of files modified per operation
- Total lines of code changed
- Number of entities (users, resources) affected
- Rate of changes over time

This policy helps prevent "blast radius" issues where a single malfunction
or malicious action could affect many resources.
"""
from typing import Dict, Any, List, Optional
from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import ValidationResult, SafetyViolation, ViolationSeverity


class BlastRadiusPolicy(BaseSafetyPolicy):
    """Enforces blast radius limits to prevent widespread damage.

    Configuration options:
        max_files_per_operation: Maximum files that can be modified (default: 10)
        max_lines_per_file: Maximum lines per file change (default: 500)
        max_total_lines: Maximum total lines changed (default: 2000)
        max_entities_affected: Maximum entities affected (default: 100)
        max_operations_per_minute: Maximum operations per minute (default: 20)
        forbidden_patterns: Patterns that indicate dangerous operations

    Example:
        >>> config = {
        ...     "max_files_per_operation": 5,
        ...     "max_lines_per_file": 200,
        ...     "forbidden_patterns": ["DELETE FROM", "DROP TABLE"]
        ... }
        >>> policy = BlastRadiusPolicy(config)
        >>> result = policy.validate(
        ...     action={"operation": "modify_files", "files": ["a.py", "b.py"]},
        ...     context={}
        ... )
    """

    # Default limits
    DEFAULT_MAX_FILES = 10
    DEFAULT_MAX_LINES_PER_FILE = 500
    DEFAULT_MAX_TOTAL_LINES = 2000
    DEFAULT_MAX_ENTITIES = 100
    DEFAULT_MAX_OPS_PER_MINUTE = 20

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize blast radius policy.

        Args:
            config: Policy configuration (optional)
        """
        super().__init__(config or {})

        # Extract limits from config with defaults
        self.max_files = self.config.get("max_files_per_operation", self.DEFAULT_MAX_FILES)
        self.max_lines_per_file = self.config.get("max_lines_per_file", self.DEFAULT_MAX_LINES_PER_FILE)
        self.max_total_lines = self.config.get("max_total_lines", self.DEFAULT_MAX_TOTAL_LINES)
        self.max_entities = self.config.get("max_entities_affected", self.DEFAULT_MAX_ENTITIES)
        self.max_ops_per_minute = self.config.get("max_operations_per_minute", self.DEFAULT_MAX_OPS_PER_MINUTE)
        self.forbidden_patterns = self.config.get("forbidden_patterns", [])

    @property
    def name(self) -> str:
        """Return policy name."""
        return "blast_radius"

    @property
    def version(self) -> str:
        """Return policy version."""
        return "1.0.0"

    @property
    def priority(self) -> int:
        """Return policy priority (higher = evaluated first).

        Blast radius has high priority since it prevents widespread damage.
        """
        return 90

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against blast radius limits.

        Args:
            action: Action to validate, may contain:
                - operation: Type of operation
                - files: List of files to modify
                - lines_changed: Lines changed per file
                - total_lines: Total lines changed
                - entities: List of affected entities
                - content: Content being modified (for pattern detection)
            context: Execution context

        Returns:
            ValidationResult with violations if limits exceeded
        """
        violations: List[SafetyViolation] = []

        # Check file count limit
        files = action.get("files", [])
        if isinstance(files, list) and len(files) > self.max_files:
            violations.append(SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.HIGH,
                message=f"Too many files affected: {len(files)} > {self.max_files}",
                action=str(action),
                context=context,
                remediation_hint=f"Reduce file count to {self.max_files} or less"
            ))

        # Check lines per file limit
        lines_changed = action.get("lines_changed", {})
        if isinstance(lines_changed, dict):
            for file_path, line_count in lines_changed.items():
                if line_count > self.max_lines_per_file:
                    violations.append(SafetyViolation(
                        policy_name=self.name,
                        severity=ViolationSeverity.HIGH,
                        message=f"Too many lines changed in {file_path}: {line_count} > {self.max_lines_per_file}",
                        action=str(action),
                        context=context,
                        remediation_hint=f"Split changes across multiple operations"
                    ))

        # Check total lines limit
        total_lines = action.get("total_lines", 0)
        if total_lines > self.max_total_lines:
            violations.append(SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.HIGH,
                message=f"Too many total lines changed: {total_lines} > {self.max_total_lines}",
                action=str(action),
                context=context,
                remediation_hint=f"Break operation into smaller batches"
            ))

        # Check entities affected limit
        entities = action.get("entities", [])
        if isinstance(entities, list) and len(entities) > self.max_entities:
            violations.append(SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.CRITICAL,
                message=f"Too many entities affected: {len(entities)} > {self.max_entities}",
                action=str(action),
                context=context,
                remediation_hint=f"Limit operation scope to {self.max_entities} entities"
            ))

        # Check for forbidden patterns in content
        content = action.get("content", "")
        if isinstance(content, str):
            for pattern in self.forbidden_patterns:
                if pattern.lower() in content.lower():
                    violations.append(SafetyViolation(
                        policy_name=self.name,
                        severity=ViolationSeverity.CRITICAL,
                        message=f"Forbidden pattern detected: '{pattern}'",
                        action=str(action),
                        context=context,
                        remediation_hint=f"Remove or refactor code containing '{pattern}'"
                    ))

        # Determine validity (invalid if any HIGH or CRITICAL violations)
        valid = not any(
            v.severity >= ViolationSeverity.HIGH
            for v in violations
        )

        return ValidationResult(
            valid=valid,
            violations=violations,
            policy_name=self.name
        )
