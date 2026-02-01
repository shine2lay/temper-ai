# Task Specification: code-crit-unsafe-deserial-09

## Problem Statement

`Database.import_from_json()` loads arbitrary JSON without validation, allowing malicious JSON to inject SQL, corrupt state, or bypass constraints. The method accepts any JSON structure and directly inserts it into the database, trusting that the input is well-formed and safe.

This is a critical security vulnerability that can lead to:
- SQL injection via crafted field values
- Database constraint violations
- Foreign key integrity violations
- Invalid state that breaks the application
- Data corruption

## Context

- **Source:** Code Review Report 2026-02-01 (Critical Issue #9)
- **File Affected:** `.claude-coord/coord_service/database.py:640-757`
- **Impact:** Data corruption, SQL injection, invalid database state
- **Module:** Coordination Service
- **OWASP Category:** A03:2021 - Injection, A08:2021 - Software and Data Integrity Failures

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Validate JSON schema before import
- [ ] Verify all foreign keys exist
- [ ] Check all constraints before inserting
- [ ] Use parameterized queries (prevent SQL injection)
- [ ] Atomic transaction (all or nothing)

### SECURITY CONTROLS
- [ ] JSON schema validation (jsonschema library)
- [ ] Whitelist allowed field names
- [ ] Validate data types match schema
- [ ] Prevent SQL injection via parameterized queries
- [ ] Reject unknown fields

### DATA INTEGRITY
- [ ] Verify foreign key references exist
- [ ] Validate unique constraints
- [ ] Check required fields are present
- [ ] Validate enum values
- [ ] Atomic import (rollback on any error)

### TESTING
- [ ] Test valid JSON imports successfully
- [ ] Test malicious JSON is rejected
- [ ] Test SQL injection attempts blocked
- [ ] Test foreign key violations detected
- [ ] Test partial imports are rolled back
- [ ] Fuzz testing with random JSON

## Implementation Plan

### Step 1: Read Current Implementation

**File:** `.claude-coord/coord_service/database.py:640-757`

```bash
grep -B 5 -A 120 "def import_from_json" .claude-coord/coord_service/database.py
```

Understand current implementation and identify vulnerabilities.

### Step 2: Define JSON Schema

**File:** `.claude-coord/coord_service/schemas.py` (new file)

```python
"""
JSON schemas for database import validation.
"""

# Schema for task import
TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "pattern": "^[a-z]+-[a-z]+-[a-zA-Z0-9_-]+$"},
        "subject": {"type": "string", "minLength": 10, "maxLength": 100},
        "description": {"type": "string"},
        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
        "priority": {"type": "integer", "minimum": 0, "maximum": 3},
        "owner": {"type": ["string", "null"]},
        "created_at": {"type": "string", "format": "date-time"},
    },
    "required": ["id", "subject", "status", "priority"],
    "additionalProperties": False,  # Reject unknown fields
}

# Schema for task dependency import
TASK_DEPENDENCY_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string"},
        "depends_on": {"type": "string"},
    },
    "required": ["task_id", "depends_on"],
    "additionalProperties": False,
}

# Schema for agent import
AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_id": {"type": "string", "minLength": 1, "maxLength": 100},
        "pid": {"type": "integer", "minimum": 1},
        "status": {"type": "string", "enum": ["active", "inactive"]},
    },
    "required": ["agent_id", "pid"],
    "additionalProperties": False,
}

# Top-level import schema
IMPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": TASK_SCHEMA,
        },
        "task_dependencies": {
            "type": "array",
            "items": TASK_DEPENDENCY_SCHEMA,
        },
        "agents": {
            "type": "array",
            "items": AGENT_SCHEMA,
        },
    },
    "additionalProperties": False,
}
```

### Step 3: Implement Secure Import

**File:** `.claude-coord/coord_service/database.py`

**Before (UNSAFE):**
```python
def import_from_json(self, json_data: str) -> None:
    """Import data from JSON (UNSAFE - no validation)"""
    import json

    data = json.loads(json_data)

    # UNSAFE: No validation, trusts input
    for task in data.get('tasks', []):
        self.conn.execute(
            # UNSAFE: String interpolation = SQL injection risk
            f"INSERT INTO tasks VALUES ('{task['id']}', ...)"
        )
```

**After (SAFE):**
```python
import json
import jsonschema
import logging
from typing import Dict, Any, List

from .schemas import IMPORT_SCHEMA, TASK_SCHEMA

logger = logging.getLogger(__name__)

class Database:
    # ... existing methods ...

    def import_from_json(self, json_data: str, validate: bool = True) -> Dict[str, int]:
        """
        Import database state from JSON with validation.

        Args:
            json_data: JSON string containing tasks, agents, dependencies
            validate: If True, validate schema and constraints (recommended)

        Returns:
            Dictionary with counts of imported items:
            {"tasks": N, "agents": M, "dependencies": K}

        Raises:
            ValueError: If JSON is invalid or validation fails
            jsonschema.ValidationError: If schema validation fails

        Example:
            >>> data = '{"tasks": [...], "agents": [...]}'
            >>> counts = db.import_from_json(data)
            >>> print(counts)  # {"tasks": 5, "agents": 2, "dependencies": 3}
        """
        # Step 1: Parse JSON
        try:
            data = json.loads(json_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

        # Step 2: Validate schema
        if validate:
            try:
                jsonschema.validate(instance=data, schema=IMPORT_SCHEMA)
            except jsonschema.ValidationError as e:
                raise ValueError(f"JSON schema validation failed: {e.message}")

        # Step 3: Validate foreign key references
        if validate:
            self._validate_foreign_keys(data)

        # Step 4: Import in transaction (atomic)
        counts = {"tasks": 0, "agents": 0, "dependencies": 0}

        try:
            with self.conn:  # Transaction
                # Import tasks
                for task in data.get('tasks', []):
                    self._import_task(task)
                    counts["tasks"] += 1

                # Import agents
                for agent in data.get('agents', []):
                    self._import_agent(agent)
                    counts["agents"] += 1

                # Import dependencies
                for dep in data.get('task_dependencies', []):
                    self._import_dependency(dep)
                    counts["dependencies"] += 1

            logger.info(f"Import successful: {counts}")
            return counts

        except Exception as e:
            logger.error(f"Import failed, rolling back: {e}")
            raise ValueError(f"Import failed: {e}")

    def _validate_foreign_keys(self, data: Dict[str, Any]) -> None:
        """
        Validate that all foreign key references exist.

        Raises:
            ValueError: If any foreign key reference is invalid
        """
        # Get all task IDs that will be imported
        imported_task_ids = {task['id'] for task in data.get('tasks', [])}

        # Get existing task IDs
        existing_tasks = set(self._get_all_task_ids())

        # Check task dependencies
        for dep in data.get('task_dependencies', []):
            task_id = dep['task_id']
            depends_on = dep['depends_on']

            # Both tasks must exist (either imported or already in DB)
            all_tasks = imported_task_ids | existing_tasks

            if task_id not in all_tasks:
                raise ValueError(f"Dependency references non-existent task: {task_id}")

            if depends_on not in all_tasks:
                raise ValueError(f"Dependency references non-existent task: {depends_on}")

        # Check task owners reference valid agents
        imported_agent_ids = {agent['agent_id'] for agent in data.get('agents', [])}
        existing_agents = set(self._get_all_agent_ids())
        all_agents = imported_agent_ids | existing_agents

        for task in data.get('tasks', []):
            if task.get('owner') and task['owner'] not in all_agents:
                raise ValueError(f"Task owner references non-existent agent: {task['owner']}")

    def _import_task(self, task: Dict[str, Any]) -> None:
        """Import single task using parameterized query (SQL injection safe)"""
        self.conn.execute(
            """
            INSERT INTO tasks (id, subject, description, status, priority, owner, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                subject = excluded.subject,
                description = excluded.description,
                status = excluded.status,
                priority = excluded.priority,
                owner = excluded.owner
            """,
            (
                task['id'],
                task['subject'],
                task.get('description', ''),
                task['status'],
                task['priority'],
                task.get('owner'),
                task.get('created_at'),
            )
        )

    def _import_agent(self, agent: Dict[str, Any]) -> None:
        """Import single agent using parameterized query"""
        self.conn.execute(
            """
            INSERT INTO agents (agent_id, pid, last_heartbeat)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(agent_id) DO UPDATE SET
                pid = excluded.pid,
                last_heartbeat = CURRENT_TIMESTAMP
            """,
            (agent['agent_id'], agent['pid'])
        )

    def _import_dependency(self, dep: Dict[str, Any]) -> None:
        """Import single dependency using parameterized query"""
        self.conn.execute(
            """
            INSERT INTO task_dependencies (task_id, depends_on)
            VALUES (?, ?)
            ON CONFLICT DO NOTHING
            """,
            (dep['task_id'], dep['depends_on'])
        )

    def _get_all_task_ids(self) -> List[str]:
        """Get all existing task IDs"""
        return [row[0] for row in self.conn.execute("SELECT id FROM tasks").fetchall()]

    def _get_all_agent_ids(self) -> List[str]:
        """Get all existing agent IDs"""
        return [row[0] for row in self.conn.execute("SELECT agent_id FROM agents").fetchall()]
```

### Step 4: Add Dependencies

**File:** `requirements.txt` or `pyproject.toml`

```
jsonschema>=4.0.0
```

## Test Strategy

### Unit Tests

**File:** `tests/coord_service/test_database_import_security.py`

```python
import pytest
import json
from coord_service.database import Database

def test_valid_json_imports_successfully(tmp_path):
    """Test that valid JSON is imported correctly"""
    db = Database(str(tmp_path / "test.db"))

    data = {
        "tasks": [
            {
                "id": "test-crit-import-1",
                "subject": "Test task import",
                "description": "Testing import",
                "status": "pending",
                "priority": 0,
            }
        ],
        "agents": [],
        "task_dependencies": [],
    }

    counts = db.import_from_json(json.dumps(data))

    assert counts["tasks"] == 1
    # Verify task was actually imported
    result = db.conn.execute("SELECT id FROM tasks WHERE id = ?", ("test-crit-import-1",)).fetchone()
    assert result is not None

def test_sql_injection_blocked(tmp_path):
    """Test that SQL injection attempts are blocked"""
    db = Database(str(tmp_path / "test.db"))

    # Attempt SQL injection in task ID
    malicious_data = {
        "tasks": [
            {
                "id": "test'; DROP TABLE tasks; --",
                "subject": "Malicious task",
                "description": "SQL injection attempt",
                "status": "pending",
                "priority": 0,
            }
        ]
    }

    # Should fail schema validation (invalid task ID pattern)
    with pytest.raises(ValueError, match="schema validation"):
        db.import_from_json(json.dumps(malicious_data))

    # Verify tasks table still exists
    result = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
    assert result.fetchone() is not None

def test_invalid_foreign_key_rejected(tmp_path):
    """Test that invalid foreign key references are rejected"""
    db = Database(str(tmp_path / "test.db"))

    data = {
        "tasks": [],
        "task_dependencies": [
            {
                "task_id": "nonexistent-task",
                "depends_on": "another-nonexistent-task",
            }
        ],
    }

    with pytest.raises(ValueError, match="non-existent task"):
        db.import_from_json(json.dumps(data))

def test_unknown_field_rejected(tmp_path):
    """Test that unknown fields are rejected (prevents data injection)"""
    db = Database(str(tmp_path / "test.db"))

    data = {
        "tasks": [
            {
                "id": "test-crit-badfield-1",
                "subject": "Test with bad field",
                "status": "pending",
                "priority": 0,
                "malicious_field": "DROP TABLE tasks",  # Unknown field
            }
        ]
    }

    with pytest.raises(ValueError, match="schema validation"):
        db.import_from_json(json.dumps(data))

def test_invalid_enum_value_rejected(tmp_path):
    """Test that invalid enum values are rejected"""
    db = Database(str(tmp_path / "test.db"))

    data = {
        "tasks": [
            {
                "id": "test-crit-enum-1",
                "subject": "Test invalid status",
                "status": "invalid_status",  # Not in enum
                "priority": 0,
            }
        ]
    }

    with pytest.raises(ValueError, match="schema validation"):
        db.import_from_json(json.dumps(data))

def test_transaction_rollback_on_error(tmp_path):
    """Test that partial imports are rolled back on error"""
    db = Database(str(tmp_path / "test.db"))

    # Valid task 1, valid task 2, invalid dependency
    data = {
        "tasks": [
            {"id": "task-1", "subject": "Task 1", "status": "pending", "priority": 0},
            {"id": "task-2", "subject": "Task 2", "status": "pending", "priority": 0},
        ],
        "task_dependencies": [
            {"task_id": "task-1", "depends_on": "nonexistent"},  # Invalid!
        ],
    }

    with pytest.raises(ValueError):
        db.import_from_json(json.dumps(data))

    # Verify NO tasks were imported (transaction rolled back)
    count = db.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert count == 0

def test_fuzz_random_json(tmp_path):
    """Fuzz test with random JSON"""
    import hypothesis
    from hypothesis import given, strategies as st

    db = Database(str(tmp_path / "test.db"))

    @given(st.text())
    def test_random_input(json_str):
        try:
            db.import_from_json(json_str, validate=True)
        except (ValueError, json.JSONDecodeError):
            # Expected for invalid JSON
            pass
        except Exception as e:
            # Unexpected exception - test fails
            pytest.fail(f"Unexpected exception: {e}")

    test_random_input()
```

## Error Handling

**Clear error messages:**
```python
# Good: Specific and actionable
raise ValueError("Task 'test-1' references non-existent agent 'agent-999'")

# Bad: Vague
raise Exception("Invalid data")
```

## Success Metrics

- [ ] All SQL injection attempts blocked
- [ ] Foreign key violations detected
- [ ] Schema validation works correctly
- [ ] Transactions are atomic (all or nothing)
- [ ] Unknown fields are rejected
- [ ] All tests pass
- [ ] Fuzz testing passes
- [ ] Security audit approves

## Dependencies

**Blocked by:** None

**Blocks:** None (can be done in parallel)

**Requires:** `jsonschema` library

## References

- Code Review Report: `.claude-coord/reports/code-review-20260201-002732.md` (lines 216-235)
- OWASP Injection: https://owasp.org/Top10/A03_2021-Injection/
- JSON Schema: https://json-schema.org/
- SQL Injection Prevention: https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html

## Estimated Effort

**Time:** 4-5 hours
**Complexity:** Medium-High (comprehensive validation, extensive testing)

---

*Priority: CRITICAL (0)*
*Category: Security (Injection Prevention & Data Integrity)*
