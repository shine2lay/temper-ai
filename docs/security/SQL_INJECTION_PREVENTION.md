# SQL Injection Prevention Guidelines

**Date:** 2026-01-27
**Status:** APPROVED
**Priority:** P0 (CRITICAL)

---

## Overview

This document provides security guidelines for preventing SQL injection vulnerabilities in Temper AI. All developers MUST follow these guidelines when working with database queries.

---

## Security Status

### Audit Results (2026-01-27)

✅ **PASSED** - Codebase audit shows NO SQL injection vulnerabilities in production code.

**Files Audited:**
- `temper_ai/observability/tracker.py` - ✅ Safe (uses SQLModel ORM)
- `temper_ai/observability/database.py` - ✅ Safe (hardcoded ping query)
- `temper_ai/observability/migrations.py` - ⚠️ Uses `text()` but properly validated
- `temper_ai/observability/visualize_trace.py` - ✅ Safe (uses SQLModel ORM)
- `temper_ai/observability/console.py` - ✅ Safe (uses SQLModel ORM)
- All other database code - ✅ Safe (uses SQLModel ORM)

---

## MANDATORY RULES

### Rule 1: NEVER Use String Concatenation or F-Strings in SQL

❌ **FORBIDDEN:**
```python
# NEVER DO THIS!
user_id = request.get("user_id")
query = f"SELECT * FROM users WHERE id = {user_id}"  # SQL INJECTION!
session.execute(text(query))

# NEVER DO THIS EITHER!
query = "SELECT * FROM users WHERE id = " + user_id  # SQL INJECTION!
query = "SELECT * FROM users WHERE id = %s" % user_id  # SQL INJECTION!
```

✅ **CORRECT:**
```python
from sqlmodel import select
from temper_ai.observability.models import User

user_id = request.get("user_id")
stmt = select(User).where(User.id == user_id)  # SAFE: Parameterized
user = session.exec(stmt).first()
```

---

### Rule 2: Use SQLModel ORM for All Queries

SQLModel automatically uses parameterized queries and provides type safety.

✅ **CORRECT: SELECT Queries**
```python
from sqlmodel import select, func
from temper_ai.observability.models import WorkflowExecution, StageExecution

# Simple select
stmt = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
workflow = session.exec(stmt).first()

# With multiple conditions
stmt = select(WorkflowExecution).where(
    WorkflowExecution.status == "completed",
    WorkflowExecution.workflow_name == name
)
workflows = session.exec(stmt).all()

# With aggregation
stmt = select(
    func.count(AgentExecution.id).label('total'),
    func.sum(AgentExecution.total_tokens).label('tokens')
).where(AgentExecution.stage_execution_id == stage_id)
metrics = session.exec(stmt).first()

# With joins
stmt = select(AgentExecution).join(
    StageExecution,
    AgentExecution.stage_execution_id == StageExecution.id
).where(StageExecution.workflow_execution_id == workflow_id)
agents = session.exec(stmt).all()
```

✅ **CORRECT: INSERT Queries**
```python
from temper_ai.observability.models import WorkflowExecution

# Create and insert
workflow = WorkflowExecution(
    id=workflow_id,
    workflow_name=name,
    status="running"
)
session.add(workflow)
session.commit()
```

✅ **CORRECT: UPDATE Queries**
```python
# Fetch, modify, commit
stmt = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
workflow = session.exec(stmt).first()
if workflow:
    workflow.status = "completed"
    workflow.end_time = utcnow()
    session.commit()
```

✅ **CORRECT: DELETE Queries**
```python
# Fetch, delete, commit
stmt = select(WorkflowExecution).where(WorkflowExecution.id == workflow_id)
workflow = session.exec(stmt).first()
if workflow:
    session.delete(workflow)
    session.commit()
```

---

### Rule 3: If You MUST Use text(), Use Bound Parameters

In rare cases where raw SQL is needed (e.g., database-specific functions), use bound parameters.

✅ **CORRECT:**
```python
from sqlalchemy import text

# Named parameters (preferred)
stmt = text(
    "SELECT * FROM workflows WHERE status = :status AND created_at > :date"
)
result = session.execute(stmt, {"status": "completed", "date": cutoff_date})

# Positional parameters (SQLite, PostgreSQL)
stmt = text("SELECT * FROM workflows WHERE status = ? AND created_at > ?")
result = session.execute(stmt, [status, cutoff_date])
```

❌ **FORBIDDEN:**
```python
# NEVER inject variables directly into text()!
stmt = text(f"SELECT * FROM workflows WHERE status = '{status}'")  # SQL INJECTION!
```

---

### Rule 4: Migrations Require Extra Validation

Migration scripts execute raw SQL and MUST be from trusted sources only.

✅ **CORRECT: Migration with Validation**
```python
def _validate_migration_sql(sql: str) -> None:
    """Validate migration SQL for basic safety checks."""
    if not sql or not sql.strip():
        raise ValueError("Migration SQL cannot be empty")

    # Check for dangerous patterns
    dangerous_patterns = [
        "DROP DATABASE",
        "CREATE USER",
        "GRANT ALL",
        "XP_",  # SQL Server extended procedures
    ]

    sql_upper = sql.upper()
    for pattern in dangerous_patterns:
        if pattern in sql_upper:
            raise ValueError(f"Migration contains dangerous pattern: {pattern}")

def apply_migration(db_manager, migration_sql: str, version: str):
    """Apply migration from TRUSTED SOURCE ONLY."""
    _validate_migration_sql(migration_sql)
    with db_manager.session() as session:
        session.execute(text(migration_sql))
```

**Migration sources (trusted):**
- Version-controlled migration files in `migrations/` directory
- Embedded schema definitions in code
- SQLModel auto-generated DDL

**Migration sources (UNTRUSTED - NEVER USE):**
- User input
- API requests
- External file uploads
- Environment variables

---

## Code Review Checklist

When reviewing code that touches the database:

- [ ] ✅ No f-strings in SQL queries
- [ ] ✅ No string concatenation in SQL queries
- [ ] ✅ Uses SQLModel ORM (select, insert, update, delete)
- [ ] ✅ If using text(), uses bound parameters (`:name` or `?`)
- [ ] ✅ Migration scripts are from trusted source and validated
- [ ] ✅ No user input directly in queries
- [ ] ✅ Input validation before database operations
- [ ] ✅ No raw SQL in API endpoints or user-facing code

---

## Linting Rules

### Ruff Configuration

Add to `pyproject.toml`:

```toml
[tool.ruff.lint]
select = [
    "S608",  # SQL injection via string concatenation
]

[tool.ruff.lint.flake8-bandit]
# Detect SQL injection patterns
check-typed-exception = true
```

### Pre-commit Hook

Add to `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/astral-sh/ruff-pre-commit
  rev: v0.1.9
  hooks:
    - id: ruff
      args: [--fix, --exit-non-zero-on-fix]
```

### Custom Grep Check

```bash
# Check for SQL injection patterns in pre-commit
git diff --staged | grep -E "(\.execute\(.*f\"|\.execute\(.*f'|\.execute\(.*\+)"
if [ $? -eq 0 ]; then
    echo "ERROR: Potential SQL injection detected!"
    exit 1
fi
```

---

## Testing Requirements

All database code MUST include security tests:

```python
import pytest
from temper_ai.observability.tracker import ExecutionTracker

def test_sql_injection_prevention():
    """Verify parameterized queries prevent SQL injection."""
    tracker = ExecutionTracker()

    # Attempt SQL injection in workflow name
    malicious_name = "test'; DROP TABLE workflows; --"

    with tracker.track_workflow(
        workflow_name=malicious_name,
        workflow_config={}
    ) as workflow_id:
        pass

    # Verify workflow created safely (no SQL execution)
    with get_session() as session:
        stmt = select(WorkflowExecution).where(
            WorkflowExecution.id == workflow_id
        )
        workflow = session.exec(stmt).first()
        assert workflow.workflow_name == malicious_name  # Stored as literal string

    # Verify tables still exist
    with get_session() as session:
        stmt = select(func.count(WorkflowExecution.id))
        count = session.exec(stmt).first()
        assert count >= 1  # Tables not dropped
```

---

## Common Mistakes to Avoid

### 1. Dynamic Column Names

❌ **WRONG:**
```python
column_name = request.get("sort_by")
query = f"SELECT * FROM workflows ORDER BY {column_name}"  # INJECTION!
```

✅ **CORRECT:**
```python
# Whitelist allowed columns
ALLOWED_COLUMNS = {"workflow_name", "start_time", "status"}
column_name = request.get("sort_by")

if column_name not in ALLOWED_COLUMNS:
    raise ValueError(f"Invalid sort column: {column_name}")

# Use getattr for dynamic column access
stmt = select(WorkflowExecution).order_by(
    getattr(WorkflowExecution, column_name)
)
```

### 2. Dynamic Table Names

❌ **WRONG:**
```python
table_name = request.get("table")
query = f"SELECT * FROM {table_name}"  # INJECTION!
```

✅ **CORRECT:**
```python
# Use model classes, not dynamic table names
MODEL_MAP = {
    "workflows": WorkflowExecution,
    "stages": StageExecution,
}

table_name = request.get("table")
model_class = MODEL_MAP.get(table_name)
if not model_class:
    raise ValueError(f"Invalid table: {table_name}")

stmt = select(model_class)
```

### 3. LIKE Clauses

✅ **CORRECT:**
```python
# Escape wildcards if needed, but still use parameterized query
search_term = request.get("search")
# SQLModel handles escaping automatically
stmt = select(WorkflowExecution).where(
    WorkflowExecution.workflow_name.like(f"%{search_term}%")
)
```

---

## Emergency Response

If a SQL injection vulnerability is discovered:

1. **IMMEDIATE:** Disable affected endpoint/feature
2. **Assess:** Determine if vulnerability was exploited (check logs)
3. **Fix:** Apply parameterized query fix
4. **Test:** Run security tests to verify fix
5. **Deploy:** Emergency hotfix deployment
6. **Audit:** Review database logs for suspicious queries
7. **Report:** Document incident and lessons learned

---

## References

- [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- [SQLModel Documentation](https://sqlmodel.tiangolo.com/)
- [SQLAlchemy Security Best Practices](https://docs.sqlalchemy.org/en/20/faq/security.html)

---

## Document History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-01-27 | 1.0 | agent-7283f3 | Initial security guidelines and audit results |

---

**This is a LIVING DOCUMENT. Update as new patterns emerge or vulnerabilities are discovered.**
