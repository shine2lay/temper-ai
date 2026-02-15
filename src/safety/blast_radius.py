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

from src.constants.probabilities import PROB_VERY_LOW
from src.safety.base import BaseSafetyPolicy
from src.safety.constants import (
    BLAST_RADIUS_SEPARATOR,
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

# Blast radius policy priority
BLAST_RADIUS_PRIORITY = 90


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
        self._init_limits()
        self._init_forbidden_patterns()

    def _init_limits(self) -> None:
        """Validate and set numeric limit config values."""
        limit_defs = [
            ("max_files", "max_files_per_operation", self.DEFAULT_MAX_FILES, MAX_FILES_UPPER_BOUND),
            ("max_lines_per_file", "max_lines_per_file", self.DEFAULT_MAX_LINES_PER_FILE, MAX_LINES_UPPER_BOUND),
            ("max_total_lines", "max_total_lines", self.DEFAULT_MAX_TOTAL_LINES, MAX_TOTAL_LINES_UPPER_BOUND),
            ("max_entities", "max_entities_affected", self.DEFAULT_MAX_ENTITIES, MAX_ENTITIES_UPPER_BOUND),
            ("max_ops_per_minute", "max_operations_per_minute", self.DEFAULT_MAX_OPS_PER_MINUTE, MAX_OPS_UPPER_BOUND),
        ]
        for attr, key, default, upper in limit_defs:
            setattr(self, attr, self._validate_positive_int(
                self.config.get(key, default), key, min_value=1, max_value=upper))

    def _init_forbidden_patterns(self) -> None:
        """Validate and compile forbidden regex patterns."""
        raw = self.config.get("forbidden_patterns", [])
        validated = self._validate_string_list(
            raw, "forbidden_patterns", allow_empty=True, max_items=1000, max_item_length=1000)
        self.forbidden_patterns = [
            self._validate_regex_pattern(
                p, f"forbidden_patterns['{p}']", max_length=1000, test_timeout=PROB_VERY_LOW)
            for p in validated
        ]

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
        return BLAST_RADIUS_PRIORITY

    def _check_file_count(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Optional[SafetyViolation]:
        """Check if file count exceeds limit."""
        files = action.get("files", [])
        if isinstance(files, list) and len(files) > self.max_files:
            return SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.HIGH,
                message=f"Too many files affected: {len(files)}{BLAST_RADIUS_SEPARATOR}{self.max_files}",
                action=str(action),
                context=context,
                remediation_hint=f"Reduce file count to {self.max_files} or less"
            )
        return None

    def _check_lines_per_file(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[SafetyViolation]:
        """Check if any file exceeds line change limit."""
        violations: List[SafetyViolation] = []
        lines_changed = action.get("lines_changed", {})

        if isinstance(lines_changed, dict):
            for file_path, line_count in lines_changed.items():
                if line_count > self.max_lines_per_file:
                    violations.append(SafetyViolation(
                        policy_name=self.name,
                        severity=ViolationSeverity.HIGH,
                        message=f"Too many lines changed in {file_path}: {line_count}{BLAST_RADIUS_SEPARATOR}{self.max_lines_per_file}",
                        action=str(action),
                        context=context,
                        remediation_hint="Split changes across multiple operations"
                    ))
        return violations

    def _check_total_lines(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Optional[SafetyViolation]:
        """Check if total lines changed exceeds limit."""
        total_lines = action.get("total_lines", 0)
        if total_lines > self.max_total_lines:
            return SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.HIGH,
                message=f"Too many total lines changed: {total_lines}{BLAST_RADIUS_SEPARATOR}{self.max_total_lines}",
                action=str(action),
                context=context,
                remediation_hint="Break operation into smaller batches"
            )
        return None

    def _check_entities_affected(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Optional[SafetyViolation]:
        """Check if entities affected exceeds limit."""
        entities = action.get("entities", [])
        if isinstance(entities, list) and len(entities) > self.max_entities:
            return SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.CRITICAL,
                message=f"Too many entities affected: {len(entities)}{BLAST_RADIUS_SEPARATOR}{self.max_entities}",
                action=str(action),
                context=context,
                remediation_hint=f"Limit operation scope to {self.max_entities} entities"
            )
        return None

    def _check_forbidden_patterns(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[SafetyViolation]:
        """Check for forbidden patterns in content."""
        violations: List[SafetyViolation] = []
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
        return violations

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against blast radius limits.

        Args:
            action: Action to validate
            context: Execution context

        Returns:
            ValidationResult with violations if limits exceeded
        """
        violations: List[SafetyViolation] = []

        # Check all limits
        file_count_violation = self._check_file_count(action, context)
        if file_count_violation:
            violations.append(file_count_violation)

        violations.extend(self._check_lines_per_file(action, context))

        total_lines_violation = self._check_total_lines(action, context)
        if total_lines_violation:
            violations.append(total_lines_violation)

        entities_violation = self._check_entities_affected(action, context)
        if entities_violation:
            violations.append(entities_violation)

        violations.extend(self._check_forbidden_patterns(action, context))

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
