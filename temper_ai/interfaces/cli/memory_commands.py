"""CLI commands for memory management.

Usage:
    temper-ai memory list    --tenant --workflow --agent [--type]
    temper-ai memory add     --tenant --workflow --agent --type
    temper-ai memory search  --tenant --workflow --agent --query
    temper-ai memory clear   --tenant --workflow --agent --confirm
    temper-ai memory seed    <seed-file.yaml>
"""

from __future__ import annotations

from typing import Any, Optional

import click
import yaml
from rich.console import Console
from rich.table import Table

console = Console()

# Memory type values (mirrors temper_ai.memory.constants to avoid cross-module import)
_TYPE_EPISODIC = "episodic"
_TYPE_PROCEDURAL = "procedural"
_TYPE_CROSS_SESSION = "cross_session"

VALID_MEMORY_TYPES = (_TYPE_EPISODIC, _TYPE_PROCEDURAL, _TYPE_CROSS_SESSION)

DEFAULT_SEARCH_LIMIT = 5
DEFAULT_PROVIDER = "in_memory"
_DEFAULT_TENANT = "default"

# Common Click option names and help text
_OPT_TENANT = "--tenant"
_OPT_WORKFLOW = "--workflow"
_OPT_AGENT = "--agent"
_OPT_PROVIDER = "--provider"
_HELP_TENANT = "Tenant ID"
_HELP_WORKFLOW = "Workflow name"
_HELP_AGENT = "Agent name"
_HELP_PROVIDER = "Memory provider"

# Table column widths
_COL_WIDTH_ID = 12
_COL_WIDTH_CONTENT = 80


def _build_service_and_scope(
    provider: str, tenant: str, workflow: str, agent: str,
) -> tuple:
    """Create a MemoryService and MemoryScope from CLI args.

    Returns:
        Tuple of (MemoryService, MemoryScope).
    """
    from temper_ai.memory.service import MemoryService

    service = MemoryService(provider_name=provider)
    scope = service.build_scope(
        tenant_id=tenant,
        workflow_name=workflow,
        agent_name=agent,
    )
    return service, scope


@click.group("memory")
def memory_group() -> None:
    """Memory management commands."""
    pass


@memory_group.command("list")
@click.option(_OPT_TENANT, default=_DEFAULT_TENANT, show_default=True, help=_HELP_TENANT)
@click.option(_OPT_WORKFLOW, default="", help=_HELP_WORKFLOW)
@click.option(_OPT_AGENT, default="", help=_HELP_AGENT)
@click.option(
    "--type", "memory_type", default=None,
    type=click.Choice(VALID_MEMORY_TYPES, case_sensitive=False),
    help="Filter by memory type",
)
@click.option(_OPT_PROVIDER, default=DEFAULT_PROVIDER, show_default=True, help=_HELP_PROVIDER)
def list_memories(tenant: str, workflow: str, agent: str, memory_type: str, provider: str) -> None:
    """List stored memories for a scope."""
    service, scope = _build_service_and_scope(provider, tenant, workflow, agent)
    entries = service.list_memories(scope, memory_type=memory_type)

    if not entries:
        console.print("[yellow]No memories found[/yellow]")
        return

    table = Table(title=f"Memories (scope: {scope.scope_key})")
    table.add_column("ID", style="dim", max_width=_COL_WIDTH_ID)
    table.add_column("Type", style="cyan")
    table.add_column("Content")
    table.add_column("Created", style="green")

    for entry in entries:
        table.add_row(
            entry.id[:_COL_WIDTH_ID],
            entry.memory_type,
            entry.content[:_COL_WIDTH_CONTENT],
            entry.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)
    console.print(f"\nTotal: {len(entries)} memories")


@memory_group.command("add")
@click.option(_OPT_TENANT, default=_DEFAULT_TENANT, show_default=True, help=_HELP_TENANT)
@click.option(_OPT_WORKFLOW, default="", help=_HELP_WORKFLOW)
@click.option(_OPT_AGENT, default="", help=_HELP_AGENT)
@click.option(
    "--type", "memory_type", required=True,
    type=click.Choice(VALID_MEMORY_TYPES, case_sensitive=False),
    help="Memory type",
)
@click.option("--content", default=None, help="Memory content (interactive if omitted)")
@click.option(_OPT_PROVIDER, default=DEFAULT_PROVIDER, show_default=True, help=_HELP_PROVIDER)
def add_memory(tenant: str, workflow: str, agent: str, memory_type: str, content: Optional[str], provider: str) -> None:
    """Add a memory to the store."""
    if content is None:
        content = click.prompt("Enter memory content")

    service, scope = _build_service_and_scope(provider, tenant, workflow, agent)
    memory_id = _store_by_type(service, scope, content, memory_type)

    console.print(f"[green]Memory stored[/green] (id={memory_id[:_COL_WIDTH_ID]})")


def _store_by_type(service: Any, scope: Any, content: str, memory_type: str) -> str:
    """Route storage to the correct service method by type."""
    if memory_type == _TYPE_EPISODIC:
        return str(service.store_episodic(scope, content))
    if memory_type == _TYPE_PROCEDURAL:
        return str(service.store_procedural(scope, content))
    return str(service.store_cross_session(scope, content))


@memory_group.command("search")
@click.option(_OPT_TENANT, default=_DEFAULT_TENANT, show_default=True, help=_HELP_TENANT)
@click.option(_OPT_WORKFLOW, default="", help=_HELP_WORKFLOW)
@click.option(_OPT_AGENT, default="", help=_HELP_AGENT)
@click.option("--query", required=True, help="Search query")
@click.option("--limit", default=DEFAULT_SEARCH_LIMIT, show_default=True, type=int, help="Max results")
@click.option(_OPT_PROVIDER, default=DEFAULT_PROVIDER, show_default=True, help=_HELP_PROVIDER)
def search_memories(tenant: str, workflow: str, agent: str, query: str, limit: int, provider: str) -> None:
    """Search memories by query."""
    service, scope = _build_service_and_scope(provider, tenant, workflow, agent)
    entries = service.search(scope=scope, query=query, limit=limit)

    if not entries:
        console.print("[yellow]No matching memories found[/yellow]")
        return

    table = Table(title=f"Search results for: {query}")
    table.add_column("ID", style="dim", max_width=_COL_WIDTH_ID)
    table.add_column("Type", style="cyan")
    table.add_column("Score", style="magenta")
    table.add_column("Content")

    for entry in entries:
        table.add_row(
            entry.id[:_COL_WIDTH_ID],
            entry.memory_type,
            f"{entry.relevance_score:.2f}",
            entry.content[:_COL_WIDTH_CONTENT],
        )

    console.print(table)


@memory_group.command("clear")
@click.option(_OPT_TENANT, default=_DEFAULT_TENANT, show_default=True, help=_HELP_TENANT)
@click.option(_OPT_WORKFLOW, default="", help=_HELP_WORKFLOW)
@click.option(_OPT_AGENT, default="", help=_HELP_AGENT)
@click.option("--confirm", is_flag=True, required=True, help="Confirm deletion")
@click.option(_OPT_PROVIDER, default=DEFAULT_PROVIDER, show_default=True, help=_HELP_PROVIDER)
def clear_memories(tenant: str, workflow: str, agent: str, confirm: bool, provider: str) -> None:
    """Delete all memories for a scope."""
    service, scope = _build_service_and_scope(provider, tenant, workflow, agent)
    count = service.clear_memories(scope)
    console.print(f"[green]Cleared {count} memories[/green] (scope: {scope.scope_key})")


@memory_group.command("seed")
@click.argument("seed_file", type=click.Path(exists=True))
@click.option(_OPT_PROVIDER, default=DEFAULT_PROVIDER, show_default=True, help=_HELP_PROVIDER)
def seed_memories(seed_file: str, provider: str) -> None:
    """Bulk load memories from a YAML seed file."""
    from temper_ai.memory.service import MemoryService

    with open(seed_file) as f:
        data = yaml.safe_load(f)

    if not data or "memories" not in data:
        console.print("[red]Error:[/red] Seed file must contain a 'memories' key")
        raise SystemExit(1)

    service = MemoryService(provider_name=provider)
    count = 0

    for item in data["memories"]:
        scope_data = item.get("scope", {})
        scope = service.build_scope(
            tenant_id=scope_data.get("tenant_id", _DEFAULT_TENANT),
            workflow_name=scope_data.get("workflow_name", ""),
            agent_name=scope_data.get("agent_name", ""),
        )
        for entry in item.get("entries", []):
            content = entry.get("content", "")
            if not content:
                continue
            memory_type = entry.get("type", _TYPE_EPISODIC)
            _store_by_type(service, scope, content, memory_type)
            count += 1

    console.print(f"[green]Seeded {count} memories[/green]")
