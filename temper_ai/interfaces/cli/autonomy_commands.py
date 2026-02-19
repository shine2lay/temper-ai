"""CLI commands for progressive autonomy management.

Usage:
    temper-ai autonomy status [--agent NAME]     Show autonomy levels
    temper-ai autonomy escalate --agent NAME     Manual escalation
    temper-ai autonomy deescalate --agent NAME   Manual de-escalation
    temper-ai autonomy emergency-stop --reason   Activate emergency stop
    temper-ai autonomy resume --reason           Deactivate emergency stop
    temper-ai autonomy budget [--scope SCOPE]    Show budget status
    temper-ai autonomy history [--agent NAME]    Transition audit log
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

console = Console()

DEFAULT_AUTONOMY_DB = "sqlite:///./autonomy.db"
DEFAULT_HISTORY_LIMIT = 20
_HELP_DB = "Autonomy database URL"
_OPT_DB = "--db"
_COL_WIDTH_ID = 12
_ID_DISPLAY_LEN = 12
_DATETIME_DISPLAY_LEN = 19
_OPT_AGENT = "--agent"
_OPT_REASON = "--reason"
_COL_DOMAIN = "Domain"

LEVEL_NAMES = {0: "SUPERVISED", 1: "SPOT_CHECKED", 2: "RISK_GATED", 3: "AUTONOMOUS", 4: "STRATEGIC"}
LEVEL_COLORS = {0: "red", 1: "yellow", 2: "cyan", 3: "green", 4: "blue"}


def _get_store(db_url: str = DEFAULT_AUTONOMY_DB):  # type: ignore[no-untyped-def]
    """Create an AutonomyStore instance."""
    from temper_ai.safety.autonomy.store import AutonomyStore
    return AutonomyStore(database_url=db_url)


def _level_display(level: int) -> str:
    """Format autonomy level with color."""
    name = LEVEL_NAMES.get(level, f"UNKNOWN({level})")
    color = LEVEL_COLORS.get(level, "white")
    return f"[{color}]{name}[/{color}]"


@click.group("autonomy")
def autonomy_group() -> None:
    """Progressive autonomy — trust levels, budgets, emergency stop."""


@autonomy_group.command("status")
@click.option(_OPT_AGENT, default=None, help="Filter by agent name")
@click.option(_OPT_DB, default=DEFAULT_AUTONOMY_DB, help=_HELP_DB)
def status(agent: str | None, db: str) -> None:
    """Show autonomy levels for all agents."""
    store = _get_store(db)
    states = store.list_states()

    if agent:
        states = [s for s in states if s.agent_name == agent]

    if not states:
        console.print("[yellow]No autonomy states found[/yellow]")
        return

    table = Table(title="Agent Autonomy Status")
    table.add_column("Agent", style="cyan")
    table.add_column(_COL_DOMAIN)
    table.add_column("Level")
    table.add_column("Shadow")
    table.add_column("Shadow Runs")
    table.add_column("Updated")

    for s in states:
        shadow_text = _level_display(s.shadow_level) if s.shadow_level is not None else "-"
        shadow_runs = f"{s.shadow_agreements}/{s.shadow_runs}" if s.shadow_runs > 0 else "-"
        table.add_row(
            s.agent_name,
            s.domain,
            _level_display(s.current_level),
            shadow_text,
            shadow_runs,
            str(s.updated_at)[:_DATETIME_DISPLAY_LEN] if s.updated_at else "-",
        )
    console.print(table)


@autonomy_group.command("escalate")
@click.option(_OPT_AGENT, required=True, help="Agent name")
@click.option("--domain", default="general", help=_COL_DOMAIN)
@click.option("--level", type=int, default=None, help="Target level (0-4)")
@click.option(_OPT_REASON, default="manual CLI escalation", help="Reason")
@click.option(_OPT_DB, default=DEFAULT_AUTONOMY_DB, help=_HELP_DB)
def escalate(agent: str, domain: str, level: int | None, reason: str, db: str) -> None:
    """Manually escalate an agent's autonomy level."""
    from temper_ai.safety.autonomy.manager import AutonomyManager
    from temper_ai.safety.autonomy.schemas import AutonomyLevel

    store = _get_store(db)
    manager = AutonomyManager(store=store, max_level=AutonomyLevel.STRATEGIC)

    target = AutonomyLevel(level) if level is not None else None
    transition = manager.escalate(agent, domain, reason=reason, target_level=target)

    if transition is None:
        console.print("[yellow]No escalation occurred[/yellow] (cooldown, max level, or already at level)")
    else:
        console.print(
            f"[green]Escalated[/green] {agent}/{domain}: "
            f"{_level_display(transition.from_level)} -> {_level_display(transition.to_level)}"
        )


@autonomy_group.command("deescalate")
@click.option(_OPT_AGENT, required=True, help="Agent name")
@click.option("--domain", default="general", help=_COL_DOMAIN)
@click.option(_OPT_REASON, default="manual CLI de-escalation", help="Reason")
@click.option(_OPT_DB, default=DEFAULT_AUTONOMY_DB, help=_HELP_DB)
def deescalate(agent: str, domain: str, reason: str, db: str) -> None:
    """Manually de-escalate an agent's autonomy level."""
    from temper_ai.safety.autonomy.manager import AutonomyManager
    from temper_ai.safety.autonomy.schemas import AutonomyLevel

    store = _get_store(db)
    manager = AutonomyManager(store=store, max_level=AutonomyLevel.STRATEGIC)

    transition = manager.de_escalate(agent, domain, reason=reason)
    if transition is None:
        console.print("[yellow]No de-escalation occurred[/yellow] (already at SUPERVISED or cooldown)")
    else:
        console.print(
            f"[green]De-escalated[/green] {agent}/{domain}: "
            f"{_level_display(transition.from_level)} -> {_level_display(transition.to_level)}"
        )


@autonomy_group.command("emergency-stop")
@click.option(_OPT_REASON, required=True, help="Reason for emergency stop")
@click.option(_OPT_DB, default=DEFAULT_AUTONOMY_DB, help=_HELP_DB)
def emergency_stop(reason: str, db: str) -> None:
    """Activate emergency stop — halt all autonomous operations."""
    from temper_ai.safety.autonomy.emergency_stop import EmergencyStopController

    store = _get_store(db)
    controller = EmergencyStopController(store=store)
    event = controller.activate(triggered_by="cli", reason=reason)
    console.print(f"[red]EMERGENCY STOP ACTIVATED[/red] — {event.id}")
    console.print(f"Reason: {reason}")
    console.print("Resume with: temper-ai autonomy resume --reason <reason>")


@autonomy_group.command("resume")
@click.option(_OPT_REASON, required=True, help="Reason for resuming")
@click.option(_OPT_DB, default=DEFAULT_AUTONOMY_DB, help=_HELP_DB)
def resume(reason: str, db: str) -> None:
    """Deactivate emergency stop — resume autonomous operations."""
    from temper_ai.safety.autonomy.emergency_stop import EmergencyStopController

    store = _get_store(db)
    controller = EmergencyStopController(store=store)

    if not controller.is_active():
        console.print("[yellow]Emergency stop is not active[/yellow]")
        return

    controller.deactivate(resolution_reason=reason)
    console.print(f"[green]Emergency stop deactivated[/green] — {reason}")


@autonomy_group.command("budget")
@click.option("--scope", default=None, help="Budget scope (agent name)")
@click.option(_OPT_DB, default=DEFAULT_AUTONOMY_DB, help=_HELP_DB)
def budget(scope: str | None, db: str) -> None:
    """Show budget status."""
    from temper_ai.safety.autonomy.budget_enforcer import BudgetEnforcer

    store = _get_store(db)
    enforcer = BudgetEnforcer(store=store)

    if scope:
        _display_budget_for_scope(enforcer, scope)
    else:
        _display_all_budgets(store)


def _display_budget_for_scope(enforcer, scope: str) -> None:  # type: ignore[no-untyped-def]
    """Display budget for a single scope."""
    status = enforcer.get_budget_status(scope)
    color = "green" if status.status == "active" else ("yellow" if status.status == "warning" else "red")

    table = Table(title=f"Budget: {scope}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Budget", f"${status.budget_usd:.2f}")
    table.add_row("Spent", f"${status.spent_usd:.4f}")
    table.add_row("Remaining", f"${status.remaining_usd:.4f}")
    table.add_row("Utilization", f"{status.utilization:.1%}")
    table.add_row("Actions", str(status.action_count))
    table.add_row("Status", f"[{color}]{status.status}[/{color}]")
    console.print(table)


def _display_all_budgets(store) -> None:  # type: ignore[no-untyped-def]
    """Display all budget records."""
    from temper_ai.safety.autonomy.models import BudgetRecord
    from sqlmodel import Session, select

    with Session(store.engine) as session:
        budgets = list(session.exec(select(BudgetRecord)).all())

    if not budgets:
        console.print("[yellow]No budget records found[/yellow]")
        return

    table = Table(title="Budget Overview")
    table.add_column("Scope", style="cyan")
    table.add_column("Budget")
    table.add_column("Spent")
    table.add_column("Remaining")
    table.add_column("Status")

    for b in budgets:
        remaining = max(0.0, b.budget_usd - b.spent_usd)
        color = "green" if b.status == "active" else ("yellow" if b.status == "warning" else "red")
        table.add_row(
            b.scope,
            f"${b.budget_usd:.2f}",
            f"${b.spent_usd:.4f}",
            f"${remaining:.4f}",
            f"[{color}]{b.status}[/{color}]",
        )
    console.print(table)


@autonomy_group.command("history")
@click.option(_OPT_AGENT, default=None, help="Filter by agent name")
@click.option("--limit", default=DEFAULT_HISTORY_LIMIT, help="Max transitions to show")
@click.option(_OPT_DB, default=DEFAULT_AUTONOMY_DB, help=_HELP_DB)
def history(agent: str | None, limit: int, db: str) -> None:
    """Show autonomy transition history."""
    store = _get_store(db)
    transitions = store.list_transitions(agent_name=agent, limit=limit)

    if not transitions:
        console.print("[yellow]No transitions found[/yellow]")
        return

    table = Table(title=f"Autonomy Transitions ({len(transitions)})")
    table.add_column("ID", width=_COL_WIDTH_ID)
    table.add_column("Agent")
    table.add_column(_COL_DOMAIN)
    table.add_column("From")
    table.add_column("To")
    table.add_column("Trigger")
    table.add_column("Time")

    for t in transitions:
        table.add_row(
            t.id[:_ID_DISPLAY_LEN],
            t.agent_name,
            t.domain,
            _level_display(t.from_level),
            _level_display(t.to_level),
            t.trigger,
            str(t.created_at)[:_DATETIME_DISPLAY_LEN] if t.created_at else "-",
        )
    console.print(table)
