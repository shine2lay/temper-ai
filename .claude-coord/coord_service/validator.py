"""
Validation layer for coordination service.

Enforces state invariants and validates all operations before execution.
"""

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ValidationError:
    """A single validation error with context."""
    code: str
    message: str
    hint: str = ""
    details: Dict = None
    examples: List[str] = None
    valid_prefixes: List[str] = None
    valid_categories: List[str] = None
    missing_sections: List[str] = None
    expected_path: str = None
    spec_path: str = None
    available_tasks: List[Dict] = None
    length: int = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "code": self.code,
            "message": self.message
        }
        if self.hint:
            result["hint"] = self.hint
        if self.details:
            result["details"] = self.details
        if self.examples:
            result["examples"] = self.examples
        if self.valid_prefixes:
            result["valid_prefixes"] = self.valid_prefixes
        if self.valid_categories:
            result["valid_categories"] = self.valid_categories
        if self.missing_sections:
            result["missing_sections"] = self.missing_sections
        if self.expected_path:
            result["expected_path"] = self.expected_path
        if self.spec_path:
            result["spec_path"] = self.spec_path
        if self.available_tasks:
            result["available_tasks"] = self.available_tasks
        if self.length is not None:
            result["length"] = self.length
        return result


class ValidationErrors(Exception):
    """Exception raised when validation fails."""

    def __init__(self, errors: List[ValidationError]):
        self.errors = errors
        super().__init__(self._format_errors())

    def _format_errors(self) -> str:
        """Format errors for display."""
        if len(self.errors) == 1:
            return self.errors[0].message
        return f"{len(self.errors)} validation errors:\n" + "\n".join(
            f"  {i+1}. {err.code}: {err.message}"
            for i, err in enumerate(self.errors)
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "validation_errors": [err.to_dict() for err in self.errors]
        }


@dataclass
class InvariantViolation:
    """A state invariant violation."""
    invariant: str
    details: List[Dict]


class InvariantViolations(Exception):
    """Exception raised when state invariants are violated."""

    def __init__(self, violations: List[InvariantViolation]):
        self.violations = violations
        super().__init__(self._format_violations())

    def _format_violations(self) -> str:
        """Format violations for display."""
        return f"{len(self.violations)} invariant violations:\n" + "\n".join(
            f"  - {v.invariant}: {len(v.details)} occurrences"
            for v in self.violations
        )


class StateValidator:
    """Validates operations and enforces state invariants."""

    # Valid task prefixes and categories
    VALID_PREFIXES = ['test', 'code', 'docs', 'gap', 'refactor', 'perf']
    VALID_CATEGORIES = ['crit', 'high', 'med', 'medi', 'low', 'quick']

    # Priority definitions (0 is highest, 3 is lowest)
    PRIORITY_CRITICAL = 0
    PRIORITY_HIGH = 1
    PRIORITY_MEDIUM = 2
    PRIORITY_LOW = 3

    # Category to priority mapping (enforced)
    CATEGORY_TO_PRIORITY = {
        'crit': 0,
        'high': 1,
        'med': 2,
        'medi': 2,
        'low': 3,
        'quick': 2  # Quick tasks default to medium priority
    }

    # Categories that skip spec file validation
    VALIDATION_SKIP_CATEGORIES = ['quick']

    def __init__(self, db):
        """Initialize validator.

        Args:
            db: Database instance
        """
        self.db = db

        # Derive project root from database path
        # db_path is like: /path/to/project/.claude-coord/coordination.db
        db_dir = os.path.dirname(self.db.db_path)  # /path/to/project/.claude-coord
        self.project_root = os.path.dirname(db_dir)  # /path/to/project

    def derive_priority_from_task_id(self, task_id: str) -> int:
        """Derive priority from task ID category.

        Args:
            task_id: Task identifier

        Returns:
            Priority level (0-3) based on category

        Raises:
            ValueError: If task ID doesn't have valid category
        """
        parts = task_id.split('-')
        if len(parts) < 2:
            return self.PRIORITY_MEDIUM  # Default fallback

        category = parts[1]
        return self.CATEGORY_TO_PRIORITY.get(category, self.PRIORITY_MEDIUM)

    def validate_task_create(
        self,
        task_id: str,
        subject: str,
        description: str,
        priority: int,
        spec_path: str = None
    ) -> None:
        """Validate task creation.

        Args:
            task_id: Task identifier
            subject: Task subject/title
            description: Task description
            priority: Task priority (0-3, where 0 is highest)
            spec_path: Optional path to task spec file

        Raises:
            ValidationErrors: If validation fails
        """
        errors = []

        # Task ID must follow naming convention
        if not re.match(r'^[a-z]+-[a-z]+-[a-z0-9-]+$', task_id):
            errors.append(ValidationError(
                code="INVALID_TASK_ID",
                message=f"Task ID '{task_id}' doesn't follow naming convention",
                hint="Format: <prefix>-<category>-<number> (e.g., test-crit-01)",
                examples=[
                    "test-crit-secret-detection-01",
                    "code-high-refactor-engine-02",
                    "docs-med-api-endpoints-03"
                ]
            ))

        # Extract and validate prefix and category
        parts = task_id.split('-')
        if len(parts) >= 2:
            prefix = parts[0]
            category = parts[1]

            # Validate prefix
            if prefix not in self.VALID_PREFIXES:
                errors.append(ValidationError(
                    code="UNKNOWN_PREFIX",
                    message=f"Unknown task prefix '{prefix}'",
                    valid_prefixes=self.VALID_PREFIXES,
                    hint="Use standard prefixes or register new prefix"
                ))

            # Validate category
            if category not in self.VALID_CATEGORIES:
                errors.append(ValidationError(
                    code="UNKNOWN_CATEGORY",
                    message=f"Unknown category '{category}'",
                    valid_categories=self.VALID_CATEGORIES,
                    hint="Use standard categories: crit, high, med/medi, low, quick"
                ))
            else:
                # Enforce category-to-priority mapping
                expected_priority = self.CATEGORY_TO_PRIORITY[category]
                if priority != expected_priority:
                    errors.append(ValidationError(
                        code="PRIORITY_CATEGORY_MISMATCH",
                        message=f"Priority {priority} doesn't match category '{category}' (expected {expected_priority})",
                        hint=f"Category '{category}' must have priority {expected_priority}, or omit --priority flag to auto-set",
                        details={
                            "category": category,
                            "provided_priority": priority,
                            "expected_priority": expected_priority
                        }
                    ))

        # Subject required and non-empty
        if not subject or not subject.strip():
            errors.append(ValidationError(
                code="MISSING_SUBJECT",
                message="Task subject is required",
                hint="Provide a concise task title"
            ))

        # Subject length limits (10-100 chars)
        if subject and (len(subject) < 10 or len(subject) > 100):
            errors.append(ValidationError(
                code="INVALID_SUBJECT_LENGTH",
                message=f"Subject length {len(subject)} out of range (10-100)",
                hint="Keep subject concise but descriptive"
            ))

        # Check if this category skips validation
        parts = task_id.split('-')
        category = parts[1] if len(parts) >= 2 else None
        skip_validation = category in self.VALIDATION_SKIP_CATEGORIES

        # Description required for critical/high priority (unless quick)
        if not skip_validation and priority in [self.PRIORITY_CRITICAL, self.PRIORITY_HIGH]:
            if not description or len(description) < 20:
                errors.append(ValidationError(
                    code="INSUFFICIENT_DESCRIPTION",
                    message="Critical/high priority tasks need detailed description",
                    hint="Provide at least 20 characters describing the task"
                ))

        # Priority must be in range 0-3
        if not (0 <= priority <= 3):
            errors.append(ValidationError(
                code="INVALID_PRIORITY",
                message=f"Priority {priority} out of range (0-3)",
                hint="0=critical, 1=high, 2=medium, 3=low"
            ))

        # Task spec validation for critical/high priority (unless quick)
        if not skip_validation and priority in [self.PRIORITY_CRITICAL, self.PRIORITY_HIGH]:
            # Use absolute path from project root
            relative_spec = f".claude-coord/task-specs/{task_id}.md"
            expected_spec = os.path.join(self.project_root, relative_spec)
            spec_file = spec_path or expected_spec

            if not os.path.exists(spec_file):
                errors.append(ValidationError(
                    code="MISSING_TASK_SPEC",
                    message="Critical/high priority task missing spec file",
                    expected_path=expected_spec,
                    hint="Create spec file with acceptance criteria, test strategy, or use 'quick' category"
                ))
            else:
                # Validate spec file has required sections
                spec_errors = self._validate_task_spec(spec_file, task_id)
                errors.extend(spec_errors)

        # Check for duplicate task ID
        if self.db.task_exists(task_id):
            existing = self.db.get_task(task_id)
            errors.append(ValidationError(
                code="DUPLICATE_TASK_ID",
                message=f"Task {task_id} already exists",
                details={
                    "status": existing['status'],
                    "owner": existing['owner'],
                    "created_at": existing['created_at']
                },
                hint="Use unique task ID or update existing task"
            ))

        if errors:
            raise ValidationErrors(errors)

    def _validate_task_spec(self, spec_path: str, task_id: str) -> List[ValidationError]:
        """Validate task spec file has required sections.

        Args:
            spec_path: Path to spec file
            task_id: Task ID

        Returns:
            List of validation errors
        """
        errors = []

        try:
            with open(spec_path) as f:
                content = f.read()

            # Required sections for task specs
            required_sections = [
                "# Task Specification",
                "## Problem Statement",
                "## Acceptance Criteria",
                "## Test Strategy",
            ]

            missing_sections = []
            for section in required_sections:
                if section not in content:
                    missing_sections.append(section)

            if missing_sections:
                errors.append(ValidationError(
                    code="INCOMPLETE_TASK_SPEC",
                    message="Task spec missing required sections",
                    missing_sections=missing_sections,
                    spec_path=spec_path,
                    hint="Add all required sections to task spec"
                ))

            # Warn if spec is too short (< 100 chars)
            if len(content) < 100:
                errors.append(ValidationError(
                    code="INSUFFICIENT_SPEC_DETAIL",
                    message="Task spec is too short",
                    length=len(content),
                    hint="Provide detailed specification with context and requirements"
                ))

            # Check for task ID match in spec
            if task_id not in content:
                errors.append(ValidationError(
                    code="TASK_ID_MISMATCH",
                    message=f"Task ID '{task_id}' not found in spec file",
                    hint="Ensure spec file references correct task ID"
                ))

        except Exception as e:
            errors.append(ValidationError(
                code="SPEC_FILE_READ_ERROR",
                message=f"Failed to read spec file: {e}",
                spec_path=spec_path
            ))

        return errors

    def validate_task_claim(self, agent_id: str, task_id: str) -> None:
        """Validate task claim operation.

        Args:
            agent_id: Agent identifier
            task_id: Task identifier

        Raises:
            ValidationErrors: If validation fails
        """
        errors = []

        # Agent must be registered
        if not self.db.agent_exists(agent_id):
            errors.append(ValidationError(
                code="AGENT_NOT_REGISTERED",
                message=f"Agent {agent_id} is not registered",
                hint="Register agent using: coord register <agent_id>"
            ))

        # Task must exist
        task = self.db.get_task(task_id)
        if not task:
            errors.append(ValidationError(
                code="TASK_NOT_FOUND",
                message=f"Task {task_id} does not exist",
                available_tasks=self.db.get_available_tasks(limit=5)
            ))
        elif task['status'] != 'pending':
            # Task must be pending
            errors.append(ValidationError(
                code="TASK_UNAVAILABLE",
                message=f"Task {task_id} is {task['status']}",
                details={
                    "current_status": task['status'],
                    "owner": task['owner'],
                    "claimed_at": task['started_at']
                }
            ))

        # Agent can't have another in_progress task
        current_task = self.db.get_agent_task(agent_id)
        if current_task:
            errors.append(ValidationError(
                code="AGENT_HAS_TASK",
                message=f"Agent {agent_id} already has task {current_task['id']}",
                hint="Complete or release current task first"
            ))

        if errors:
            raise ValidationErrors(errors)

    def validate_lock_acquire(self, file_path: str, agent_id: str) -> None:
        """Validate lock acquisition.

        Args:
            file_path: File path to lock
            agent_id: Agent identifier

        Raises:
            ValidationErrors: If validation fails
        """
        errors = []

        # Agent must be registered
        if not self.db.agent_exists(agent_id):
            errors.append(ValidationError(
                code="AGENT_NOT_REGISTERED",
                message=f"Agent {agent_id} is not registered",
                hint="Register agent first"
            ))

        # Check if file is locked by another agent
        locks = self.db.get_file_locks(file_path)
        other_locks = [owner for owner in locks if owner != agent_id]

        if other_locks:
            errors.append(ValidationError(
                code="FILE_LOCKED",
                message=f"File {file_path} is locked by {other_locks[0]}",
                details={"locked_by": other_locks},
                hint=f"Wait for {other_locks[0]} to release the lock"
            ))

        if errors:
            raise ValidationErrors(errors)

    def validate_post_operation(self) -> None:
        """Validate state invariants after an operation.

        Raises:
            InvariantViolations: If invariants are violated
        """
        violations = []

        # Invariant: Each task has at most one owner
        multi_owner = self.db.query("""
            SELECT id, COUNT(DISTINCT owner) as owners
            FROM tasks WHERE owner IS NOT NULL
            GROUP BY id HAVING owners > 1
        """)
        if multi_owner:
            violations.append(InvariantViolation(
                invariant="Unique task owners",
                details=[dict(row) for row in multi_owner]
            ))

        # Invariant: Each agent has at most one in_progress task
        multi_task = self.db.query("""
            SELECT owner, COUNT(*) as task_count
            FROM tasks WHERE status='in_progress'
            GROUP BY owner HAVING task_count > 1
        """)
        if multi_task:
            violations.append(InvariantViolation(
                invariant="One task per agent",
                details=[dict(row) for row in multi_task]
            ))

        # Invariant: All locks owned by registered agents
        invalid_locks = self.db.query("""
            SELECT l.file_path, l.owner
            FROM locks l
            LEFT JOIN agents a ON l.owner = a.id
            WHERE a.id IS NULL
        """)
        if invalid_locks:
            violations.append(InvariantViolation(
                invariant="Locks belong to agents",
                details=[dict(row) for row in invalid_locks]
            ))

        if violations:
            raise InvariantViolations(violations)
