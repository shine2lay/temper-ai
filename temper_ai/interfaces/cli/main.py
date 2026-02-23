"""Temper AI CLI — minimal entry point."""

import logging
import threading

import click
from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

DEFAULT_CONFIG_ROOT = "configs"
DEFAULT_SERVER_HOST = "0.0.0.0"  # nosec B104 — intentional: configurable bind address
DEFAULT_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8420
DEFAULT_MAX_WORKERS = 4


@click.group()
@click.version_option(package_name="temper-ai", prog_name="temper-ai")
def main() -> None:
    """Temper AI CLI."""
    pass


@main.command()
@click.option(
    "--host",
    default=DEFAULT_HOST,
    show_default=True,
    envvar="TEMPER_HOST",
    help="Bind address",
)
@click.option(
    "--port",
    default=DEFAULT_DASHBOARD_PORT,
    show_default=True,
    envvar="TEMPER_PORT",
    help="Listen port",
)
@click.option(
    "--config-root",
    default=DEFAULT_CONFIG_ROOT,
    show_default=True,
    envvar="TEMPER_CONFIG_ROOT",
    help="Config directory root",
)
@click.option(
    "--db", default=None, envvar="TEMPER_DATABASE_URL", help="Database URL override"
)
@click.option(
    "--workers",
    default=DEFAULT_MAX_WORKERS,
    show_default=True,
    envvar="TEMPER_MAX_WORKERS",
    help="Max concurrent workflows",
)
@click.option(
    "--reload", "dev_reload", is_flag=True, help="Auto-reload on code changes"
)
@click.option("--dev", is_flag=True, help="Dev mode: disable auth, permissive CORS")
@click.option(
    "--mcp",
    "enable_mcp",
    is_flag=True,
    help="Also start MCP stdio server in a daemon thread",
)
def serve(**kwargs: object) -> None:
    """Start Temper AI HTTP API server.

    Use --dev for local development (disables auth, permissive CORS).
    Without --dev, runs in production mode with auth and restrictive CORS.
    Use --mcp to also expose workflows via MCP stdio (daemon thread).
    """
    host: str = kwargs["host"]  # type: ignore[assignment]
    port: int = kwargs["port"]  # type: ignore[assignment]
    config_root: str = kwargs["config_root"]  # type: ignore[assignment]
    db: str | None = kwargs["db"]  # type: ignore[assignment]
    workers: int = kwargs["workers"]  # type: ignore[assignment]
    dev_reload: bool = kwargs["dev_reload"]  # type: ignore[assignment]
    dev: bool = kwargs["dev"]  # type: ignore[assignment]
    enable_mcp: bool = kwargs["enable_mcp"]  # type: ignore[assignment]

    app = _init_server_app(config_root, db, workers, dev)

    if enable_mcp:
        _start_mcp_thread(config_root, app)

    if host == DEFAULT_SERVER_HOST:  # nosec B104
        console.print(
            "[yellow]Warning:[/yellow] Binding to 0.0.0.0 exposes service on all network interfaces"
        )

    label = "Temper AI (Dev)" if dev else "Temper AI Server"
    console.print(f"\n[cyan]{label}[/cyan] listening on http://{host}:{port}")
    console.print("Press Ctrl+C to stop\n")

    _run_uvicorn(app, host, port, dev_reload)


def _init_server_app(
    config_root: str, db: str | None, workers: int, dev: bool
) -> object:
    """Create the FastAPI app with database and observability wiring."""
    try:
        from temper_ai.interfaces.dashboard.app import create_app
    except ImportError as e:
        console.print(
            f"[red]Error:[/red] Server dependencies not installed: {e}\n"
            "Install with: pip install 'temper-ai[dashboard]'"
        )
        raise SystemExit(1)

    from temper_ai.events.event_bus import TemperEventBus
    from temper_ai.observability.backends import SQLObservabilityBackend
    from temper_ai.observability.event_bus import ObservabilityEventBus
    from temper_ai.observability.tracker import ExecutionTracker
    from temper_ai.storage.database.engine import get_database_url

    db_url = db or get_database_url()
    try:
        ExecutionTracker.ensure_database(db_url)
    except (OSError, ConnectionError, RuntimeError) as e:
        console.print(f"[red]Database error:[/red] {e}")
        raise SystemExit(1)

    backend = SQLObservabilityBackend(buffer=False)
    event_bus = TemperEventBus(observability_bus=ObservabilityEventBus(), persist=False)
    return create_app(
        backend=backend,
        event_bus=event_bus,
        mode="dev" if dev else "server",
        config_root=config_root,
        max_workers=workers,
    )


def _start_mcp_thread(config_root: str, app: object) -> None:
    """Start MCP stdio server in a daemon thread."""
    from temper_ai.mcp.server import create_mcp_server

    mcp = create_mcp_server(
        config_root=config_root,
        execution_service=getattr(
            getattr(app, "state", None), "execution_service", None
        ),
    )
    threading.Thread(target=lambda: mcp.run(transport="stdio"), daemon=True).start()
    console.print("[cyan]MCP stdio server[/cyan] started in background thread")


def _run_uvicorn(app: object, host: str, port: int, dev_reload: bool) -> None:
    """Start the uvicorn server."""
    import uvicorn

    try:
        uvicorn.run(app, host=host, port=port, log_level="info", reload=dev_reload)  # type: ignore[arg-type]
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped[/yellow]")
