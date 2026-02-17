"""CLI commands for strategic goal proposals.

Usage:
    maf goals list       List goal proposals
    maf goals propose    Run analysis and generate proposals
    maf goals review     Apply review decision to a proposal
    maf goals approve    Shortcut to approve a proposal
    maf goals reject     Shortcut to reject a proposal
    maf goals status     Show acceptance rate and proposal stats
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from src.goals.store import GoalStore

console = Console()

_COL_STATUS = "Status"
_OPT_REVIEWER = "--reviewer"
_OPT_REASON = "--reason"
_HELP_REVIEWER = "Reviewer name"
_RECENT_ANALYSIS_RUNS = 5  # noqa: scanner: skip-magic

DEFAULT_LOOKBACK_HOURS = 48
DEFAULT_PROPOSAL_LIMIT = 20
DEFAULT_GOALS_DB = "sqlite:///./goals.db"
_HELP_DB = "Goals database URL"
_OPT_DB = "--db"
_COL_WIDTH_ID = 16
_COL_WIDTH_TITLE = 40
_ID_DISPLAY_LEN = 16


def _get_store(db_url: str = DEFAULT_GOALS_DB) -> GoalStore:
    """Create a GoalStore instance."""
    from src.goals.store import GoalStore
    return GoalStore(database_url=db_url)


@click.group("goals")
def goals_group() -> None:
    """Strategic goal proposals — analyze, propose, review."""


@goals_group.command("list")
@click.option("--type", "goal_type", default=None, help="Filter by goal type")
@click.option("--status", default=None, help="Filter by status")
@click.option("--product", default=None, help="Filter by product type")
@click.option("--limit", default=DEFAULT_PROPOSAL_LIMIT, help="Max proposals")
@click.option(_OPT_DB, default=DEFAULT_GOALS_DB, help=_HELP_DB)
def list_proposals(
    goal_type: str | None,
    status: str | None,
    product: str | None,
    limit: int,
    db: str,
) -> None:
    """List goal proposals."""
    store = _get_store(db)
    proposals = store.list_proposals(
        status=status, goal_type=goal_type, product_type=product, limit=limit
    )

    if not proposals:
        console.print("[yellow]No proposals found[/yellow]")
        return

    table = Table(title=f"Goal Proposals ({len(proposals)})")
    table.add_column("ID", width=_COL_WIDTH_ID)
    table.add_column("Type")
    table.add_column("Title", width=_COL_WIDTH_TITLE)
    table.add_column(_COL_STATUS)
    table.add_column("Priority")
    table.add_column("Risk")
    for p in proposals:
        risk = p.risk_assessment.get("level", "?") if p.risk_assessment else "?"
        table.add_row(
            p.id[:_ID_DISPLAY_LEN],
            p.goal_type,
            p.title[:_COL_WIDTH_TITLE],
            p.status,
            f"{p.priority_score:.3f}",
            risk,
        )
    console.print(table)


@goals_group.command("propose")
@click.option("--lookback", default=DEFAULT_LOOKBACK_HOURS, help="Hours of history to analyze")
@click.option(_OPT_DB, default=DEFAULT_GOALS_DB, help=_HELP_DB)
def propose(lookback: int, db: str) -> None:
    """Run analysis and generate goal proposals."""
    from src.goals.analysis_orchestrator import AnalysisOrchestrator

    store = _get_store(db)
    orch = AnalysisOrchestrator(store=store)
    run = orch.run_analysis(lookback_hours=lookback)

    status_color = "green" if run.status == "completed" else "red"
    console.print(
        f"[{status_color}]Analysis {run.status}[/{status_color}] — "
        f"{run.proposals_generated} proposals generated"
    )
    if run.error_message:
        console.print(f"[red]Error:[/red] {run.error_message}")


@goals_group.command("review")
@click.argument("proposal_id")
@click.option("--action", type=click.Choice(["approve", "reject", "defer"]), required=True)
@click.option(_OPT_REVIEWER, required=True, help=_HELP_REVIEWER)
@click.option(_OPT_REASON, default=None, help="Review reason")
@click.option(_OPT_DB, default=DEFAULT_GOALS_DB, help=_HELP_DB)
def review(proposal_id: str, action: str, reviewer: str, reason: str | None, db: str) -> None:
    """Apply a review decision to a proposal."""
    from src.goals._schemas import GoalReviewAction
    from src.goals.review_workflow import GoalReviewWorkflow

    store = _get_store(db)
    workflow = GoalReviewWorkflow(store)
    review_action = GoalReviewAction(action)
    ok = workflow.review(proposal_id, review_action, reviewer, reason)

    if ok:
        console.print(f"[green]Proposal {proposal_id}: {action}[/green]")
    else:
        console.print(f"[red]Failed to {action} proposal {proposal_id}[/red]")


@goals_group.command("approve")
@click.argument("proposal_id")
@click.option(_OPT_REVIEWER, required=True, help=_HELP_REVIEWER)
@click.option(_OPT_REASON, default=None, help="Approval reason")
@click.option(_OPT_DB, default=DEFAULT_GOALS_DB, help=_HELP_DB)
def approve(proposal_id: str, reviewer: str, reason: str | None, db: str) -> None:
    """Approve a goal proposal."""
    from src.goals._schemas import GoalReviewAction
    from src.goals.review_workflow import GoalReviewWorkflow

    store = _get_store(db)
    workflow = GoalReviewWorkflow(store)
    ok = workflow.review(proposal_id, GoalReviewAction.APPROVE, reviewer, reason)

    if ok:
        console.print(f"[green]Approved: {proposal_id}[/green]")
    else:
        console.print(f"[red]Failed to approve {proposal_id}[/red]")


@goals_group.command("reject")
@click.argument("proposal_id")
@click.option(_OPT_REVIEWER, required=True, help=_HELP_REVIEWER)
@click.option(_OPT_REASON, default=None, help="Rejection reason")
@click.option(_OPT_DB, default=DEFAULT_GOALS_DB, help=_HELP_DB)
def reject(proposal_id: str, reviewer: str, reason: str | None, db: str) -> None:
    """Reject a goal proposal."""
    from src.goals._schemas import GoalReviewAction
    from src.goals.review_workflow import GoalReviewWorkflow

    store = _get_store(db)
    workflow = GoalReviewWorkflow(store)
    ok = workflow.review(proposal_id, GoalReviewAction.REJECT, reviewer, reason)

    if ok:
        console.print(f"[green]Rejected: {proposal_id}[/green]")
    else:
        console.print(f"[red]Failed to reject {proposal_id}[/red]")


@goals_group.command("status")
@click.option(_OPT_DB, default=DEFAULT_GOALS_DB, help=_HELP_DB)
def status(db: str) -> None:
    """Show acceptance rate and proposal statistics."""
    from src.goals.review_workflow import GoalReviewWorkflow

    store = _get_store(db)
    workflow = GoalReviewWorkflow(store)

    counts = store.count_by_status()
    rate = workflow.get_acceptance_rate()
    total = sum(counts.values())

    console.print(f"Total proposals: {total}")
    console.print(f"Acceptance rate: {rate * 100:.1f}%")

    if counts:
        table = Table(title="Proposals by Status")
        table.add_column(_COL_STATUS)
        table.add_column("Count")
        for s, c in sorted(counts.items()):
            table.add_row(s, str(c))
        console.print(table)

    # Show recent analysis runs
    runs = store.list_analysis_runs(limit=_RECENT_ANALYSIS_RUNS)
    if runs:
        run_table = Table(title="Recent Analysis Runs")
        run_table.add_column("ID", width=_COL_WIDTH_ID)
        run_table.add_column(_COL_STATUS)
        run_table.add_column("Proposals")
        run_table.add_column("Started")
        for r in runs:
            started = r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "?"
            run_table.add_row(
                r.id[:_ID_DISPLAY_LEN],
                r.status,
                str(r.proposals_generated),
                started,
            )
        console.print(run_table)
