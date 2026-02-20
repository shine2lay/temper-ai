"""CLI commands for persistent agent management (M9)."""
import json
import logging
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from temper_ai.interfaces.cli.agent_constants import (
    AGENT_GROUP_HELP,
    CMD_CHAT_HELP,
    CMD_LIST_HELP,
    CMD_REGISTER_HELP,
    CMD_STATUS_HELP,
    CMD_UNREGISTER_HELP,
    COLUMN_INVOCATIONS,
    COLUMN_LAST_ACTIVE,
    COLUMN_NAME,
    COLUMN_STATUS,
    COLUMN_TYPE,
    METADATA_OPTION_HELP,
    MSG_AGENT_PROMPT,
    MSG_CHAT_EXIT,
    MSG_CHAT_PROMPT,
    MSG_NOT_FOUND,
    MSG_REGISTERED,
    MSG_UNREGISTERED,
    STATUS_OPTION_HELP,
    TABLE_TITLE_AGENTS,
    TABLE_TITLE_STATUS,
    VERBOSE_OPTION_HELP,
)

console = Console()
logger = logging.getLogger(__name__)


def _get_service():
    """Lazy import AgentRegistryService."""
    from temper_ai.registry.service import AgentRegistryService

    return AgentRegistryService()


@click.group("agent", help=AGENT_GROUP_HELP)
def agent_group():
    """Manage persistent agents."""
    pass


@agent_group.command("list", help=CMD_LIST_HELP)
@click.option("--status", default=None, help=STATUS_OPTION_HELP)
def list_agents(status: Optional[str]):
    """List all registered agents."""
    service = _get_service()
    agents = service.list_agents(status=status)

    table = Table(title=TABLE_TITLE_AGENTS)
    table.add_column(COLUMN_NAME, style="cyan")
    table.add_column(COLUMN_TYPE)
    table.add_column(COLUMN_STATUS)
    table.add_column(COLUMN_INVOCATIONS)
    table.add_column(COLUMN_LAST_ACTIVE)

    for agent in agents:
        last_active = str(agent.last_active_at) if agent.last_active_at else "never"
        table.add_row(
            agent.name,
            agent.agent_type,
            agent.status,
            str(agent.total_invocations),
            last_active,
        )

    console.print(table)


@agent_group.command("register", help=CMD_REGISTER_HELP)
@click.argument("config_path", type=click.Path(exists=True))
@click.option("--metadata", default=None, help=METADATA_OPTION_HELP)
def register_agent(config_path: str, metadata: Optional[str]):
    """Register a persistent agent from config file."""
    meta_dict = None
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON metadata:[/red] {e}")
            raise SystemExit(1)

    service = _get_service()
    try:
        entry = service.register_agent(config_path, metadata=meta_dict)
        console.print(f"[green]{MSG_REGISTERED.format(name=entry.name)}[/green]")
        console.print(f"  ID: {entry.id}")
        console.print(f"  Namespace: {entry.memory_namespace}")
    except (ValueError, FileNotFoundError) as e:
        console.print(f"[red]Registration failed:[/red] {e}")
        raise SystemExit(1)


@agent_group.command("unregister", help=CMD_UNREGISTER_HELP)
@click.argument("name")
def unregister_agent(name: str):
    """Unregister a persistent agent."""
    service = _get_service()
    success = service.unregister_agent(name)
    if success:
        console.print(f"[green]{MSG_UNREGISTERED.format(name=name)}[/green]")
    else:
        console.print(f"[red]{MSG_NOT_FOUND.format(name=name)}[/red]")
        raise SystemExit(1)


@agent_group.command("status", help=CMD_STATUS_HELP)
@click.argument("name")
def agent_status(name: str):
    """Show status for a registered agent."""
    service = _get_service()
    entry = service.get_agent(name)
    if not entry:
        console.print(f"[red]{MSG_NOT_FOUND.format(name=name)}[/red]")
        raise SystemExit(1)

    table = Table(title=TABLE_TITLE_STATUS)
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("Name", entry.name)
    table.add_row("ID", entry.id)
    table.add_row("Type", entry.agent_type)
    table.add_row("Version", entry.version)
    table.add_row("Status", entry.status)
    table.add_row("Namespace", entry.memory_namespace)
    table.add_row("Invocations", str(entry.total_invocations))
    table.add_row("Registered", str(entry.registered_at))
    last_active = str(entry.last_active_at) if entry.last_active_at else "never"
    table.add_row("Last Active", last_active)

    console.print(table)


def _run_chat_loop(service, name: str, verbose: bool) -> None:
    """Run interactive chat loop with a registered agent."""
    from temper_ai.registry._schemas import MessageRequest

    console.print(f"[cyan]Chatting with {name}[/cyan]")
    console.print(MSG_CHAT_EXIT)

    while True:
        try:
            user_input = input(MSG_CHAT_PROMPT)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Chat ended[/yellow]")
            break

        if user_input.strip().lower() in ("exit", "quit"):
            console.print("[yellow]Chat ended[/yellow]")
            break

        if not user_input.strip():
            continue

        try:
            request = MessageRequest(content=user_input)
            response = service.invoke(name, request)
            console.print(f"{MSG_AGENT_PROMPT}{response.content}")
            if verbose and response.tokens_used:
                console.print(f"[dim]({response.tokens_used} tokens)[/dim]")
        except (RuntimeError, ValueError, KeyError) as e:
            console.print(f"[red]Error:[/red] {e}")


@agent_group.command("chat", help=CMD_CHAT_HELP)
@click.argument("name")
@click.option("--verbose", "-v", is_flag=True, help=VERBOSE_OPTION_HELP)
def chat_agent(name: str, verbose: bool):
    """Interactive chat with a registered agent."""
    service = _get_service()
    entry = service.get_agent(name)
    if not entry:
        console.print(f"[red]{MSG_NOT_FOUND.format(name=name)}[/red]")
        raise SystemExit(1)

    _run_chat_loop(service, name, verbose)
