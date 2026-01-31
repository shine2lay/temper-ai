# Fix Type Safety Errors - Part 31

**Date:** 2026-01-27
**Task:** m3.1-01 (in progress)
**Agent:** agent-d6e90e

---

## Summary

Thirty-first batch of type safety fixes targeting CLI rollback command module. Fixed missing return type annotations for all Click command functions. Successfully fixed 7 total errors (5 direct in rollback.py + 2 cascading) reducing overall error count from 171 to 164.

---

## Changes

### Files Modified

**src/cli/rollback.py:**
- Added `-> None` return type annotation for all command functions:
  - `rollback() -> None` - Click group decorator function
  - `list(...) -> None` - List available snapshots command
  - `info(snapshot_id: str) -> None` - Get snapshot details command
  - `execute(...) -> None` - Execute manual rollback command
  - `history(...) -> None` - View rollback history command
- **Errors fixed:** 5 direct errors → 0 direct errors

---

## Progress

### Type Error Count

**Before Part 31:** 171 errors in 44 files
**After Part 31:** 164 errors in 43 files
**Direct fixes:** 5 errors in rollback.py
**Total impact:** 7 errors fixed (5 direct + 2 cascading)
**Net change:** -7 errors, -1 file ✓

**Progress: 59% complete (403→164 is 239 down, 59% reduction from start)**

### Files Checked Successfully

- `src/cli/rollback.py` - 0 direct errors ✓

### Verification

```bash
source .venv/bin/activate
mypy --strict src/cli/rollback.py
# No errors found (only cascading from imports)
```

---

## Implementation Details

### Pattern 1: Click Command Return Types

All Click commands should return None:

```python
# Before - Missing return type
import click

@click.group()
def rollback():
    """Rollback operations."""
    pass

@rollback.command()
@click.argument("snapshot_id")
def info(snapshot_id: str):
    """Get snapshot details."""
    try:
        # ... implementation ...
        click.echo("Snapshot info here")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()

# After - Explicit None return
import click

@click.group()
def rollback() -> None:
    """Rollback operations."""
    pass

@rollback.command()
@click.argument("snapshot_id")
def info(snapshot_id: str) -> None:
    """Get snapshot details."""
    try:
        # ... implementation ...
        click.echo("Snapshot info here")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
```

**Why -> None:**
- Click commands are side-effect functions (print to console)
- Never return values (Click framework handles exit codes)
- Strict mode requires explicit return type annotations
- Documents function contract (doesn't produce return value)

### Pattern 2: Click Command Structure

Standard CLI command pattern:

```python
@rollback.command()
@click.argument("snapshot_id")
@click.option("--reason", required=True, help="Reason for rollback")
@click.option("--operator", required=True, help="Your name/ID")
@click.option("--dry-run", is_flag=True, help="Preview without executing")
@click.option("--force", is_flag=True, help="Skip safety checks")
def execute(
    snapshot_id: str,
    reason: str,
    operator: str,
    dry_run: bool,
    force: bool
) -> None:
    """Execute manual rollback."""
    try:
        # Initialize services
        manager = RollbackManager()
        api = RollbackAPI(manager)

        # Validate safety
        is_safe, warnings = api.validate_rollback_safety(snapshot_id)
        if warnings:
            for warning in warnings:
                click.echo(f"⚠️  {warning}")

        # Confirm action (unless dry run)
        if not dry_run:
            if not click.confirm("Proceed with rollback?"):
                click.echo("Rollback cancelled.")
                return

        # Execute operation
        result = api.execute_manual_rollback(
            snapshot_id=snapshot_id,
            operator=operator,
            reason=reason,
            dry_run=dry_run
        )

        # Display results
        if result.success:
            click.echo(f"✅ Rollback completed")
        else:
            click.echo(f"❌ Rollback failed", err=True)
            raise click.Abort()

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
```

**Key elements:**
- Decorators: @rollback.command(), @click.option(), @click.argument()
- Type annotations for parameters (from decorators)
- Return type -> None (always)
- Exception handling with click.echo(err=True)
- Raise click.Abort() for fatal errors
- User-friendly output with emojis (✅ ❌ ⚠️)

### Pattern 3: CLI Rollback Commands

Four rollback operations available:

```python
# 1. List snapshots
python -m src.cli rollback list \
    --workflow-id wf-123 \
    --since-hours 24 \
    --limit 10
# Shows available snapshots with age, file count

# 2. Get snapshot details
python -m src.cli rollback info snap-456
# Shows files, state keys, safety warnings

# 3. Execute rollback (dry run)
python -m src.cli rollback execute snap-456 \
    --reason "Testing" \
    --operator alice \
    --dry-run
# Preview changes without executing

# 4. Execute rollback (real)
python -m src.cli rollback execute snap-456 \
    --reason "Recovery from failed deployment" \
    --operator alice
# Restores files and state with confirmation

# 5. View history
python -m src.cli rollback history \
    --snapshot-id snap-456 \
    --limit 20
# Shows past rollback operations
```

**Safety features:**
- Dry run mode for testing
- Confirmation prompt before execution
- Safety validation checks
- Warning display
- Operator tracking (who did what)
- Reason required (why)
- Force flag to skip checks (dangerous)

### Pattern 4: Rollback System Architecture

Complete rollback system components:

```python
# Layer 1: Storage (RollbackSnapshot dataclass)
@dataclass
class RollbackSnapshot:
    id: str
    action: Dict[str, Any]           # Tool/action that was executed
    context: Dict[str, Any]          # Execution context (workflow, stage, agent)
    file_snapshots: Dict[str, str]   # path -> content before action
    state_snapshots: Dict[str, Any]  # state keys -> values before action
    created_at: datetime

# Layer 2: Manager (RollbackManager)
class RollbackManager:
    def create_snapshot(...) -> RollbackSnapshot:
        """Capture current state before action."""

    def restore_snapshot(snapshot_id: str) -> RollbackResult:
        """Restore files and state from snapshot."""

# Layer 3: API (RollbackAPI)
class RollbackAPI:
    def list_snapshots(...) -> List[RollbackSnapshot]:
        """Query snapshots with filters."""

    def get_snapshot_details(snapshot_id: str) -> Dict[str, Any]:
        """Get detailed snapshot information."""

    def validate_rollback_safety(snapshot_id: str) -> Tuple[bool, List[str]]:
        """Check if rollback is safe (age, conflicts, etc.)."""

    def execute_manual_rollback(snapshot_id: str, ...) -> RollbackResult:
        """Execute rollback with audit trail."""

    def get_rollback_history(...) -> List[RollbackResult]:
        """Query past rollback operations."""

# Layer 4: CLI (src/cli/rollback.py)
@click.group()
def rollback() -> None:
    """Click commands for interactive rollback."""
```

**Benefits:**
- Automatic snapshots before dangerous operations
- Manual rollback when needed
- Safety validation (age checks, conflict detection)
- Dry run preview
- Audit trail (who, when, why, what)
- Database persistence (survives restarts)

---

## Next Steps

### Phase 4: Other High-Error Modules (Continuing)

**Completed:**
- console.py (30 errors) ✓
- hooks.py (23 errors) ✓
- buffer.py (21 errors) ✓
- visualize_trace.py (19 errors) ✓
- sql_backend.py (28 errors) ✓
- s3_backend.py (20 errors) ✓
- prometheus_backend.py (45 errors with cascading) ✓
- models.py (20 errors) ✓
- tracker.py (10 errors) ✓
- circuit_breaker.py (22 errors) ✓
- token_bucket.py (17 errors) ✓
- rollback.py (7 errors) ✓

**Next highest error counts:**
- `src/tools/executor.py` - 15 errors
- `src/agents/llm_providers.py` - 15 errors (may be less with cascading)
- `src/tools/calculator.py` - 12 errors
- `src/agents/agent_orchestrator.py` - 11 errors

---

## Technical Notes

### Click Framework Type Patterns

Click command functions:
- **Group functions:** `@click.group() def name() -> None:`
- **Command functions:** `@click.command() def name(...) -> None:`
- **Always return None** - Click handles exit codes internally
- **Exceptions:** Raise `click.Abort()` for fatal errors
- **Parameters:** Type annotations from decorators (@click.option, @click.argument)

### CLI Best Practices

User-friendly CLI design:
- **Confirmation prompts** for destructive operations
- **Dry run mode** for testing without changes
- **Safety validation** before dangerous operations
- **Rich output** with emojis and formatting
- **Error handling** with clear messages
- **Audit trail** (operator, reason, timestamp)
- **Help text** on all commands and options

### Rollback System Benefits

Why automatic rollback matters:
- **Undo mistakes:** Revert file changes from failed operations
- **Safe experimentation:** Try changes with safety net
- **Audit trail:** Track who changed what and why
- **Fast recovery:** Instant restore vs manual reconstruction
- **State consistency:** Files + in-memory state restored together

**Use cases:**
- Tool execution failure (partial file changes)
- Agent decision reversal (undo action)
- Testing and experimentation (try then revert)
- Production incidents (quick recovery)

---

## Related Documentation

- Task: m3.1-01 (Fix Type Safety Errors 174 → 0)
- Previous: changes/0062-fix-type-safety-part30.md
- Click Documentation: https://click.palletsprojects.com/

---

## Notes

- rollback.py now has zero direct type errors ✓
- Fixed 7 errors (5 direct + 2 cascading)
- All Click command functions have explicit -> None return types
- No behavioral changes - all fixes are type annotations only
- 35 files now have 0 type errors
- **Progress: 59% complete (403→164 is 239 down, 59% reduction)**
- **Remaining: Only 164 errors to fix! Less than 41% remaining! 🎯**
