"""MCP protocol CLI commands."""
import logging
import os

import click
from rich.console import Console
from rich.table import Table

from temper_ai.interfaces.cli.constants import DEFAULT_CONFIG_ROOT, ENV_VAR_CONFIG_ROOT

logger = logging.getLogger(__name__)
console = Console()

DEFAULT_MCP_PORT = 8421


@click.group("mcp")
def mcp_group() -> None:
    """MCP protocol commands."""
    pass


@mcp_group.command("serve")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"]),
    default="stdio",
    show_default=True,
    help="MCP transport protocol",
)
@click.option(
    "--port",
    default=DEFAULT_MCP_PORT,
    show_default=True,
    type=int,
    help="HTTP transport port",
)
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="HTTP transport host address",
)
@click.option(
    "--config-root",
    default=DEFAULT_CONFIG_ROOT,
    show_default=True,
    envvar=ENV_VAR_CONFIG_ROOT,
    help="Configuration directory root",
)
def mcp_serve(transport: str, port: int, host: str, config_root: str) -> None:
    """Start Temper AI as an MCP server."""
    try:
        from temper_ai.mcp.server import create_mcp_server
    except ImportError as exc:
        console.print(
            f"[red]Error:[/red] MCP dependencies not installed: {exc}\n"
            "Install with: pip install 'temper-ai[mcp]'"
        )
        raise SystemExit(1)

    api_key: str | None = None
    if transport == "http":
        if host == "0.0.0.0":
            console.print(
                "[yellow]Warning:[/yellow] Binding to 0.0.0.0 exposes the MCP server "
                "on all network interfaces. Prefer 127.0.0.1 for local use."
            )
        api_key = os.environ.get("TEMPER_MCP_API_KEY")
        if not api_key:
            console.print(
                "[red]Error:[/red] TEMPER_MCP_API_KEY environment variable is required "
                "for HTTP transport. Set it to a strong secret value."
            )
            raise SystemExit(1)

    # Create execution service for bounded concurrency and run tracking
    from temper_ai.workflow.execution_service import WorkflowExecutionService

    execution_service = WorkflowExecutionService(
        backend=None, event_bus=None, config_root=config_root,
    )
    mcp_server = create_mcp_server(
        config_root=config_root,
        execution_service=execution_service,
        api_key=api_key,
    )

    if transport == "stdio":
        console.print("[cyan]Temper AI MCP Server[/cyan] (stdio transport)")
        console.print("Ready for MCP client connections...")
        mcp_server.run(transport="stdio")
    else:
        console.print(
            f"[cyan]Temper AI MCP Server[/cyan] listening on {host}:{port} (HTTP transport)"
        )
        mcp_server.run(transport="streamable-http", host=host, port=port)


@mcp_group.command("list-tools")
@click.option(
    "--config",
    "config_path",
    required=True,
    type=click.Path(exists=True),
    help="Agent config YAML with mcp_servers",
)
def mcp_list_tools(config_path: str) -> None:
    """List tools from MCP servers in an agent config."""
    import yaml

    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    mcp_servers_raw = raw.get("agent", {}).get("mcp_servers")
    if not mcp_servers_raw:
        console.print("[yellow]No mcp_servers configured in this agent.[/yellow]")
        return

    try:
        from temper_ai.mcp._schemas import MCPServerConfig
        from temper_ai.mcp.manager import MCPManager
    except ImportError as exc:
        console.print(
            f"[red]Error:[/red] MCP not installed: {exc}\n"
            "Install with: pip install 'temper-ai[mcp]'"
        )
        raise SystemExit(1)

    configs = [MCPServerConfig(**s) if isinstance(s, dict) else s for s in mcp_servers_raw]

    try:
        with MCPManager(configs) as manager:
            tools = manager.connect_all()
            table = Table(title="MCP Tools")
            table.add_column("Name", style="cyan")
            table.add_column("Server")
            table.add_column("Description")
            table.add_column("Read-Only", style="green")

            for tool in tools:
                meta = tool.get_metadata()
                parts = meta.name.split("__", 1)
                server_name = parts[0] if len(parts) > 1 else "?"
                read_only = "Yes" if not meta.modifies_state else "No"
                table.add_row(meta.name, server_name, meta.description, read_only)

            console.print(table)
            console.print(
                f"\n[green]{len(tools)} tools[/green] from {len(configs)} server(s)"
            )
    except (RuntimeError, ValueError, ConnectionError) as exc:
        console.print(f"[red]Error connecting to MCP servers:[/red] {exc}")
        raise SystemExit(1)
