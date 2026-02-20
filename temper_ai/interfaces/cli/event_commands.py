"""CLI commands for event bus management (M9)."""
import logging
from datetime import datetime
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from temper_ai.interfaces.cli.event_constants import (
    CMD_LIST_EVENTS_HELP,
    CMD_REPLAY_HELP,
    CMD_SUBSCRIBE_HELP,
    CMD_SUBSCRIPTIONS_HELP,
    CMD_UNSUBSCRIBE_HELP,
    COLUMN_ACTIVE,
    COLUMN_AGENT,
    COLUMN_EVENT_TYPE,
    COLUMN_HANDLER,
    COLUMN_ID,
    COLUMN_SOURCE,
    COLUMN_TIMESTAMP,
    COLUMN_TYPE,
    DEFAULT_EVENT_LIST_LIMIT,
    EVENTS_GROUP_HELP,
    MSG_NO_EVENTS,
    MSG_SUBSCRIBED,
    MSG_UNSUBSCRIBED,
    SINCE_OPTION_HELP,
    TABLE_TITLE_EVENTS,
    TABLE_TITLE_SUBSCRIPTIONS,
    TYPE_OPTION_HELP,
    WORKFLOW_OPTION_HELP,
)

console = Console()
logger = logging.getLogger(__name__)


def _get_event_bus():
    """Lazy import TemperEventBus."""
    from temper_ai.events.event_bus import TemperEventBus

    return TemperEventBus()


def _get_subscription_registry():
    """Lazy import SubscriptionRegistry."""
    from temper_ai.events.subscription_registry import SubscriptionRegistry

    return SubscriptionRegistry()


def _parse_since(since: Optional[str]) -> Optional[datetime]:
    """Parse ISO format timestamp string. Raises SystemExit on invalid input."""
    if not since:
        return None
    try:
        return datetime.fromisoformat(since)
    except ValueError:
        console.print(f"[red]Invalid date format:[/red] {since}")
        raise SystemExit(1)


@click.group("events", help=EVENTS_GROUP_HELP)
def events_group():
    """Manage events and subscriptions."""
    pass


@events_group.command("list", help=CMD_LIST_EVENTS_HELP)
@click.option("--type", "event_type", default=None, help=TYPE_OPTION_HELP)
@click.option("--since", default=None, help=SINCE_OPTION_HELP)
@click.option("--limit", default=DEFAULT_EVENT_LIST_LIMIT, help="Max events to show")
def list_events(event_type: Optional[str], since: Optional[str], limit: int):
    """List recent events."""
    bus = _get_event_bus()
    since_dt = _parse_since(since)
    events = bus.replay_events(event_type=event_type, since=since_dt, limit=limit)

    if not events:
        console.print(MSG_NO_EVENTS)
        return

    table = Table(title=TABLE_TITLE_EVENTS)
    table.add_column(COLUMN_ID, style="dim")
    table.add_column(COLUMN_TYPE, style="cyan")
    table.add_column(COLUMN_TIMESTAMP)
    table.add_column(COLUMN_SOURCE)

    for evt in events:
        table.add_row(
            getattr(evt, "id", "")[:8],
            getattr(evt, "event_type", ""),
            str(getattr(evt, "timestamp", "")),
            getattr(evt, "source_workflow_id", "") or "",
        )

    console.print(table)


@events_group.command("subscribe", help=CMD_SUBSCRIBE_HELP)
@click.argument("agent_id")
@click.argument("event_type")
@click.option("--workflow", default=None, help=WORKFLOW_OPTION_HELP)
def subscribe(agent_id: str, event_type: str, workflow: Optional[str]):
    """Create an event subscription for an agent."""
    bus = _get_event_bus()
    sub_id = bus.subscribe_persistent(
        agent_id=agent_id,
        event_type=event_type,
        workflow_to_trigger=workflow,
    )
    console.print(f"[green]{MSG_SUBSCRIBED.format(sub_id=sub_id)}[/green]")


@events_group.command("unsubscribe", help=CMD_UNSUBSCRIBE_HELP)
@click.argument("subscription_id")
def unsubscribe(subscription_id: str):
    """Remove an event subscription."""
    registry = _get_subscription_registry()
    success = registry.unregister(subscription_id)
    if success:
        console.print(f"[green]{MSG_UNSUBSCRIBED.format(sub_id=subscription_id)}[/green]")
    else:
        console.print("[red]Subscription not found[/red]")
        raise SystemExit(1)


@events_group.command("subscriptions", help=CMD_SUBSCRIPTIONS_HELP)
def list_subscriptions():
    """List active event subscriptions."""
    registry = _get_subscription_registry()
    subs = registry.load_active()

    table = Table(title=TABLE_TITLE_SUBSCRIPTIONS)
    table.add_column(COLUMN_ID, style="dim")
    table.add_column(COLUMN_EVENT_TYPE, style="cyan")
    table.add_column(COLUMN_AGENT)
    table.add_column(COLUMN_HANDLER)
    table.add_column(COLUMN_ACTIVE)

    for sub in subs:
        handler = (
            getattr(sub, "workflow_to_trigger", None)
            or getattr(sub, "handler_ref", "")
            or ""
        )
        table.add_row(
            getattr(sub, "id", "")[:8],
            getattr(sub, "event_type", ""),
            getattr(sub, "agent_id", "") or "",
            handler,
            str(getattr(sub, "active", True)),
        )

    console.print(table)


@events_group.command("replay", help=CMD_REPLAY_HELP)
@click.argument("event_type")
@click.option("--since", default=None, help=SINCE_OPTION_HELP)
@click.option("--limit", default=DEFAULT_EVENT_LIST_LIMIT, help="Max events to replay")
def replay(event_type: str, since: Optional[str], limit: int):
    """Replay events of a given type."""
    bus = _get_event_bus()
    since_dt = _parse_since(since)
    events = bus.replay_events(event_type=event_type, since=since_dt, limit=limit)

    if not events:
        console.print(MSG_NO_EVENTS)
        return

    console.print(f"[cyan]Replaying {len(events)} event(s)[/cyan]")
    for evt in events:
        payload_str = str(getattr(evt, "payload", {}))
        console.print(
            f"  [{getattr(evt, 'timestamp', '')}] "
            f"{getattr(evt, 'event_type', '')}: {payload_str[:200]}"  # noqa: scanner: skip-magic
        )
