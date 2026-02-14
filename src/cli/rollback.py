"""CLI commands for rollback operations.

Provides interactive commands for:
- Listing available snapshots
- Viewing snapshot details
- Executing manual rollbacks with safety checks

Example:
    # List recent snapshots
    python -m src.cli rollback list --workflow-id wf-123 --limit 10

    # Get snapshot details
    python -m src.cli rollback info snap-456

    # Dry run (preview without executing)
    python -m src.cli rollback execute snap-456 \
        --reason "Testing rollback" \
        --operator alice \
        --dry-run

    # Execute rollback
    python -m src.cli rollback execute snap-456 \
        --reason "Manual recovery from failed deployment" \
        --operator alice
"""
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import click

from src.constants.durations import SECONDS_PER_HOUR
from src.constants.limits import MEDIUM_ITEM_LIMIT
from src.safety.rollback import RollbackManager
from src.safety.rollback_api import RollbackAPI
from src.utils.logging import get_logger

logger = get_logger(__name__)


@click.group()
def rollback() -> None:
    """Rollback operations."""
    pass


@rollback.command()
@click.option("--workflow-id", help="Filter by workflow ID")
@click.option("--agent-id", help="Filter by agent ID")
@click.option("--since-hours", type=int, help="Show snapshots from last N hours")
@click.option("--limit", default=MEDIUM_ITEM_LIMIT, type=int, help="Max snapshots to show")
def list(workflow_id: Optional[str], agent_id: Optional[str], since_hours: Optional[int], limit: int) -> None:
    """List available snapshots."""
    try:
        manager = RollbackManager()
        api = RollbackAPI(manager)

        since = None
        if since_hours:
            since = datetime.now(UTC) - timedelta(hours=since_hours)

        snapshots = api.list_snapshots(
            workflow_id=workflow_id,
            agent_id=agent_id,
            since=since,
            limit=limit
        )

        if not snapshots:
            click.echo("No snapshots found.")
            return

        click.echo(f"\nFound {len(snapshots)} snapshot(s):\n")
        for snapshot in snapshots:
            age = (datetime.now(UTC) - snapshot.created_at).total_seconds() / SECONDS_PER_HOUR
            click.echo(
                f"  {snapshot.id}: {snapshot.action.get('tool', 'unknown')} "
                f"({snapshot.created_at.strftime('%Y-%m-%d %H:%M:%S')}, "
                f"{age:.1f}h ago)"
            )
    except Exception as e:
        click.echo(f"Error listing snapshots: {e}", err=True)
        raise click.Abort()


@rollback.command()
@click.argument("snapshot_id")
def info(snapshot_id: str) -> None:
    """Get snapshot details."""
    try:
        manager = RollbackManager()
        api = RollbackAPI(manager)

        details = api.get_snapshot_details(snapshot_id)
        if not details:
            click.echo(f"Snapshot not found: {snapshot_id}", err=True)
            raise click.Abort()

        click.echo(f"\nSnapshot: {details['id']}")
        click.echo(f"Created: {details['created_at']}")
        click.echo(f"Age: {details['age_hours']:.1f} hours")
        click.echo(f"Files: {details['file_count']}")

        if details['files']:
            click.echo("\nFiles in snapshot:")
            for file_path in details['files']:
                click.echo(f"  - {file_path}")

        if details.get('state_keys'):
            click.echo(f"\nState keys: {len(details['state_keys'])}")

        # Show safety validation
        is_safe, warnings = api.validate_rollback_safety(snapshot_id)
        if warnings:
            click.echo("\n⚠️  Warnings:")
            for warning in warnings:
                click.echo(f"  - {warning}")
        else:
            click.echo("\n✅ No safety warnings")

    except Exception as e:
        click.echo(f"Error getting snapshot info: {e}", err=True)
        raise click.Abort()


def _initialize_rollback_api() -> RollbackAPI:
    """Initialize rollback manager and API.

    Returns:
        Configured RollbackAPI instance

    Raises:
        click.Abort: If initialization fails
    """
    try:
        manager = RollbackManager()
        return RollbackAPI(manager)
    except (ImportError, RuntimeError) as e:
        click.echo(f"❌ Failed to initialize rollback system: {e}", err=True)
        raise click.Abort()


def _validate_rollback_safety(
    api: RollbackAPI, snapshot_id: str, force: bool
) -> tuple:
    """Validate rollback safety checks.

    Args:
        api: RollbackAPI instance
        snapshot_id: Snapshot identifier
        force: Skip safety checks if True

    Returns:
        Tuple of (is_safe, warnings)

    Raises:
        click.Abort: If validation fails
    """
    try:
        is_safe, warnings = api.validate_rollback_safety(snapshot_id)
    except ValueError as e:
        click.echo(f"❌ Invalid snapshot ID: {e}", err=True)
        raise click.Abort()
    except (OSError, IOError) as e:
        click.echo(f"❌ Error reading snapshot: {e}", err=True)
        raise click.Abort()

    if warnings:
        click.echo("⚠️  Warnings:")
        for warning in warnings:
            click.echo(f"  - {warning}")
        click.echo()

    if not is_safe and not force:
        click.echo("❌ Safety check failed. Use --force to override.", err=True)
        raise click.Abort()

    return is_safe, warnings


def _confirm_rollback_execution(
    api: RollbackAPI, snapshot_id: str, operator: str, reason: str, force: bool
) -> None:
    """Confirm rollback execution with user.

    Args:
        api: RollbackAPI instance
        snapshot_id: Snapshot identifier
        operator: Operator name
        reason: Rollback reason
        force: Skip confirmation if True

    Raises:
        click.Abort: If user cancels or details retrieval fails
    """
    try:
        details = api.get_snapshot_details(snapshot_id)
    except ValueError as e:
        click.echo(f"❌ Invalid snapshot: {e}", err=True)
        raise click.Abort()
    except (OSError, IOError) as e:
        click.echo(f"❌ Error reading snapshot details: {e}", err=True)
        raise click.Abort()

    if details:
        click.echo(f"About to rollback {details['file_count']} file(s)")
        click.echo(f"Operator: {operator}")
        click.echo(f"Reason: {reason}\n")

        if not force:
            if not click.confirm("Proceed with rollback?"):
                click.echo("Rollback cancelled.")
                raise click.Abort()


def _execute_rollback_operation(
    api: RollbackAPI, snapshot_id: str, operator: str,
    reason: str, dry_run: bool, force: bool
) -> Any:
    """Execute the rollback operation.

    Args:
        api: RollbackAPI instance
        snapshot_id: Snapshot identifier
        operator: Operator name
        reason: Rollback reason
        dry_run: Preview mode if True
        force: Force execution if True

    Returns:
        Rollback result object

    Raises:
        click.Abort: If execution fails
    """
    try:
        return api.execute_manual_rollback(
            snapshot_id=snapshot_id,
            operator=operator,
            reason=reason,
            dry_run=dry_run,
            force=force
        )
    except ValueError as e:
        click.echo(f"❌ Invalid rollback parameters: {e}", err=True)
        raise click.Abort()
    except (OSError, IOError, PermissionError) as e:
        click.echo(f"❌ File system error during rollback: {e}", err=True)
        raise click.Abort()
    except RuntimeError as e:
        click.echo(f"❌ Rollback execution error: {e}", err=True)
        raise click.Abort()


def _display_rollback_results(result: Any) -> None:
    """Display rollback execution results.

    Args:
        result: Rollback result object

    Raises:
        click.Abort: If rollback failed
    """
    if result.success:
        click.echo(f"✅ Rollback completed: {result.status.value}")
        click.echo(f"Reverted: {len(result.reverted_items)} items")
        if result.failed_items:
            click.echo(f"Failed: {len(result.failed_items)} items")
            for item in result.failed_items:
                click.echo(f"  - {item}")
    else:
        click.echo(f"❌ Rollback failed: {result.status.value}", err=True)
        if result.errors:
            click.echo("\nErrors:")
            for error in result.errors:
                click.echo(f"  - {error}")
        raise click.Abort()


@rollback.command()
@click.argument("snapshot_id")
@click.option("--reason", required=True, help="Reason for rollback")
@click.option("--operator", required=True, help="Your name/ID")
@click.option("--dry-run", is_flag=True, help="Preview changes without executing")
@click.option("--force", is_flag=True, help="Skip safety checks")
def execute(snapshot_id: str, reason: str, operator: str, dry_run: bool, force: bool) -> None:
    """Execute manual rollback."""
    # Initialize
    api = _initialize_rollback_api()

    # Validate safety
    is_safe, warnings = _validate_rollback_safety(api, snapshot_id, force)

    if dry_run:
        click.echo("🔍 Dry run mode - no changes will be made\n")

    # Confirm before execution
    if not dry_run:
        _confirm_rollback_execution(api, snapshot_id, operator, reason, force)

    # Execute and display results
    result = _execute_rollback_operation(api, snapshot_id, operator, reason, dry_run, force)
    _display_rollback_results(result)



@rollback.command()
@click.option("--snapshot-id", help="Filter by snapshot ID")
@click.option("--limit", default=MEDIUM_ITEM_LIMIT, type=int, help="Max results to show")
def history(snapshot_id: Optional[str], limit: int) -> None:
    """View rollback execution history."""
    try:
        manager = RollbackManager()
        api = RollbackAPI(manager)

        results = api.get_rollback_history(snapshot_id=snapshot_id, limit=limit)

        if not results:
            click.echo("No rollback history found.")
            return

        click.echo(f"\nRollback history ({len(results)} result(s)):\n")
        for result in results:
            status_icon = "✅" if result.success else "❌"
            click.echo(
                f"{status_icon} {result.snapshot_id}: {result.status.value} "
                f"({len(result.reverted_items)} reverted, "
                f"{len(result.failed_items)} failed) - "
                f"{result.completed_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            if result.metadata.get("operator"):
                click.echo(f"   Operator: {result.metadata['operator']}")
            if result.metadata.get("reason"):
                click.echo(f"   Reason: {result.metadata['reason']}")
            click.echo()

    except Exception as e:
        click.echo(f"Error getting rollback history: {e}", err=True)
        raise click.Abort()


if __name__ == "__main__":
    rollback()
