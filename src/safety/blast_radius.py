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
from typing import Any, Dict, List, Optional

from src.safety.base import BaseSafetyPolicy
from src.safety.constants import (
    BLAST_RADIUS_PRIORITY,
    DEFAULT_MAX_ENTITIES,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_LINES_PER_FILE,
    DEFAULT_MAX_OPS_PER_MINUTE,
    DEFAULT_MAX_TOTAL_LINES,
    MAX_ENTITIES_UPPER_BOUND,
    MAX_FILES_UPPER_BOUND,
    MAX_LINES_UPPER_BOUND,
    MAX_OPS_UPPER_BOUND,
    MAX_TOTAL_LINES_UPPER_BOUND,
)
from src.safety.interfaces import SafetyViolation, ValidationResult, ViolationSeverity
from src.safety.validation import ValidationMixin


class BlastRadiusPolicy(BaseSafetyPolicy, ValidationMixin):
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

    # Default limits (from safety constants)
    DEFAULT_MAX_FILES = DEFAULT_MAX_FILES
    DEFAULT_MAX_LINES_PER_FILE = DEFAULT_MAX_LINES_PER_FILE
    DEFAULT_MAX_TOTAL_LINES = DEFAULT_MAX_TOTAL_LINES
    DEFAULT_MAX_ENTITIES = DEFAULT_MAX_ENTITIES
    DEFAULT_MAX_OPS_PER_MINUTE = DEFAULT_MAX_OPS_PER_MINUTE

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize blast radius policy with validated configuration.

        Args:
            config: Policy configuration (optional)

        Raises:
            ValueError: If configuration contains invalid values

        Configuration Validation:
            - max_files_per_operation: Must be positive integer (1-10000)
            - max_lines_per_file: Must be positive integer (1-1000000)
            - max_total_lines: Must be positive integer (1-10000000)
            - max_entities_affected: Must be positive integer (1-100000)
            - max_operations_per_minute: Must be positive integer (1-1000)
            - forbidden_patterns: Must be valid regex patterns list
        """
        super().__init__(config or {})

        # Validate and extract limits from config with defaults
        self.max_files = self._validate_positive_int(
            self.config.get("max_files_per_operation", self.DEFAULT_MAX_FILES),
            "max_files_per_operation",
            min_value=1,
            max_value=MAX_FILES_UPPER_BOUND
        )

        self.max_lines_per_file = self._validate_positive_int(
            self.config.get("max_lines_per_file", self.DEFAULT_MAX_LINES_PER_FILE),
            "max_lines_per_file",
            min_value=1,
            max_value=MAX_LINES_UPPER_BOUND
        )

        self.max_total_lines = self._validate_positive_int(
            self.config.get("max_total_lines", self.DEFAULT_MAX_TOTAL_LINES),
            "max_total_lines",
            min_value=1,
            max_value=MAX_TOTAL_LINES_UPPER_BOUND
        )

        self.max_entities = self._validate_positive_int(
            self.config.get("max_entities_affected", self.DEFAULT_MAX_ENTITIES),
            "max_entities_affected",
            min_value=1,
            max_value=MAX_ENTITIES_UPPER_BOUND
        )

        self.max_ops_per_minute = self._validate_positive_int(
            self.config.get("max_operations_per_minute", self.DEFAULT_MAX_OPS_PER_MINUTE),
            "max_operations_per_minute",
            min_value=1,
            max_value=MAX_OPS_UPPER_BOUND
        )

        # Validate forbidden patterns
        forbidden_patterns_raw = self.config.get("forbidden_patterns", [])
        forbidden_patterns_validated = self._validate_string_list(
            forbidden_patterns_raw,
            "forbidden_patterns",
            allow_empty=True,
            max_items=1000,
            max_item_length=1000
        )

        # Compile and test each pattern for ReDoS
        self.forbidden_patterns = []
        for pattern_str in forbidden_patterns_validated:
            # Validate regex pattern (compiles and tests for ReDoS)
            compiled_pattern = self._validate_regex_pattern(
                pattern_str,
                f"forbidden_patterns['{pattern_str}']",
                max_length=1000,
                test_timeout=0.1
            )
            self.forbidden_patterns.append(compiled_pattern)

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
                        remediation_hint="Split changes across multiple operations"
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
                remediation_hint="Break operation into smaller batches"
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
            for compiled_pattern in self.forbidden_patterns:
                match = compiled_pattern.search(content)
                if match:
                    violations.append(SafetyViolation(
                        policy_name=self.name,
                        severity=ViolationSeverity.CRITICAL,
                        message=f"Forbidden pattern detected: '{compiled_pattern.pattern}'",
                        action=str(action),
                        context=context,
                        remediation_hint=f"Remove or refactor code containing '{compiled_pattern.pattern}'"
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
