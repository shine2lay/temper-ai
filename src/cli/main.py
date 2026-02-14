"""
Unified CLI for Meta-Autonomous Framework.

Entry point: `maf`

Commands:
    maf run <workflow>          Run a workflow from a YAML config
    maf dashboard               Launch dashboard to browse past executions
    maf validate <workflow>     Validate workflow config without running
    maf list workflows          List available workflows
    maf list agents             List available agents
    maf list stages             List available stages
    maf rollback ...            Rollback operations
    maf m5 ...                  M5 self-improvement commands
"""
import json
import logging
from pathlib import Path
from typing import Any, Optional

import click
import yaml
from rich.console import Console
from rich.table import Table

from src.constants.durations import HOURS_PER_WEEK
from src.utils.exceptions import WorkflowStageError

console = Console()
logger = logging.getLogger(__name__)

# Project root for resolving paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = ".meta-autonomous/observability.db"
DEFAULT_DASHBOARD_PORT = 8420

# Exit codes
EXIT_CODE_KEYBOARD_INTERRUPT = 130  # POSIX standard exit code for SIGINT (Ctrl+C)


# ─── Helpers ──────────────────────────────────────────────────────────


def _load_and_validate_workflow(
    workflow_path: str, verbose: bool = False
) -> Any:
    """Load a workflow YAML file and validate against schema.

    Returns the parsed workflow config dict.
    Raises SystemExit(1) on validation failure.
    """
    from src.compiler.schemas import WorkflowConfig as WorkflowConfigSchema

    with open(workflow_path) as f:
        workflow_config = yaml.safe_load(f)

    if not workflow_config:
        console.print("[red]Error:[/red] Empty workflow file")
        raise SystemExit(1)

    try:
        WorkflowConfigSchema(**workflow_config)
        if verbose:
            console.print("[green]Schema validation passed[/green]")
    except Exception as e:  # noqa: BLE001 -- CLI validation catch-all
        console.print(f"[red]Validation error:[/red] {e}")
        raise SystemExit(1)

    return workflow_config

def _cleanup_tool_executor(engine: Any) -> None:
    """Clean up tool executor resources.

    Args:
        engine: The workflow engine instance
    """
    logger.debug(f"Starting cleanup, engine type: {type(engine)}")
    tool_executor = None
    if hasattr(engine, 'tool_executor'):
        tool_executor = engine.tool_executor
    elif hasattr(engine, 'compiler') and hasattr(engine.compiler, 'tool_executor'):
        tool_executor = engine.compiler.tool_executor

    if tool_executor is not None:
        try:
            logger.debug("Calling tool_executor.shutdown()")
            tool_executor.shutdown()
            logger.debug("tool_executor.shutdown() completed")
        except Exception as e:  # noqa: BLE001 -- defensive cleanup
            logger.debug(f"Error during tool executor shutdown: {e}")
    else:
        logger.debug("No tool_executor found to cleanup")

# ─── Root group ───────────────────────────────────────────────────────


@click.group()
@click.version_option(package_name="meta-autonomous-framework", prog_name="maf")
def main() -> None:
    """Meta-Autonomous Framework CLI."""
    pass


# ─── run command ──────────────────────────────────────────────────────


def _setup_logging(verbose: bool, show_details: bool) -> None:
    """Configure logging based on verbosity and detail flags.

    Args:
        verbose: Enable DEBUG level logging
        show_details: Attach RichHandler for INFO level streaming logs
    """
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    else:
        logging.basicConfig(level=logging.WARNING)

    # Attach RichHandler for streaming logs when --show-details is active
    if show_details and not verbose:
        from rich.logging import RichHandler
        src_logger = logging.getLogger("src")
        if not any(isinstance(h, RichHandler) for h in src_logger.handlers):
            src_logger.setLevel(logging.INFO)
            src_logger.propagate = False
            rh = RichHandler(console=console, show_path=False, show_time=True, markup=False)
            rh.setLevel(logging.INFO)
            src_logger.addHandler(rh)


def _load_workflow_config(
    workflow: str, input_file: Optional[str], config_root: str, verbose: bool
) -> tuple:
    """Load and validate workflow config, load inputs, and check requirements.

    Args:
        workflow: Path to workflow YAML file
        input_file: Optional path to input YAML file
        config_root: Config directory root
        verbose: Enable verbose output

    Returns:
        Tuple of (workflow_config, inputs)

    Raises:
        SystemExit: On validation failure or missing required inputs
    """
    # Load and validate workflow YAML
    workflow_config = _load_and_validate_workflow(workflow, verbose=verbose)

    # Load inputs
    inputs: dict = {}
    if input_file:
        with open(input_file) as f:
            inputs = yaml.safe_load(f) or {}

    # Check required inputs
    wf = workflow_config.get("workflow", {})
    required = wf.get("inputs", {}).get("required", [])
    missing = [r for r in required if r not in inputs]
    if missing:
        console.print(
            f"[red]Missing required inputs:[/red] {', '.join(missing)}"
        )
        console.print("Provide them in an input file: --input inputs.yaml")
        raise SystemExit(1)

    return workflow_config, inputs


def _start_dashboard_server(backend: Any, event_bus: Any, port: int) -> Any:
    """Start dashboard server in background thread.

    Args:
        backend: ObservabilityBackend instance
        event_bus: ObservabilityEventBus instance
        port: Port number for dashboard

    Returns:
        uvicorn.Server instance or None if failed to start
    """
    try:
        import threading

        import uvicorn

        from src.dashboard.app import create_app

        app = create_app(backend=backend, event_bus=event_bus)
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")  # noqa: S104  # nosec B104
        dashboard_server = uvicorn.Server(config)
        thread = threading.Thread(target=dashboard_server.run, daemon=True)
        thread.start()
        console.print(f"\n[cyan]Dashboard:[/cyan] http://localhost:{port}\n")
        return dashboard_server
    except ImportError as e:
        console.print(
            f"[yellow]Warning:[/yellow] Dashboard not available: {e}\n"
            "Install: pip install 'meta-autonomous-framework[dashboard]'"
        )
        return None


def _initialize_infrastructure(
    config_root: str, db_path: str, dashboard_port: Optional[int], verbose: bool
) -> tuple:
    """Initialize database, registries, tracker, event bus, and optionally dashboard server.

    Args:
        config_root: Config directory root
        db_path: Database file path
        dashboard_port: Optional port for dashboard (None = no dashboard)
        verbose: Enable verbose output

    Returns:
        Tuple of (config_loader, tool_registry, tracker, engine, event_bus, dashboard_server)

    Raises:
        SystemExit: On initialization failure
    """
    # Import dependencies
    try:
        from src.compiler.config_loader import ConfigLoader
        from src.observability.tracker import ExecutionTracker
        from src.tools.registry import ToolRegistry
    except ImportError as e:
        console.print(f"[red]Import error:[/red] {e}")
        if verbose:
            logger.exception("Failed to import required modules")
        raise SystemExit(1)

    # Init database
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        ExecutionTracker.ensure_database(f"sqlite:///{db_path}")
    except (OSError, PermissionError) as e:
        console.print(f"[red]Database initialization error:[/red] {e}")
        if verbose:
            logger.exception("Failed to initialize database")
        raise SystemExit(1)

    # Create infrastructure
    config_loader = ConfigLoader(config_root=config_root)
    tool_registry = ToolRegistry(auto_discover=True)

    # Create event bus and tracker
    event_bus = None
    if dashboard_port is not None:
        try:
            from src.observability.event_bus import ObservabilityEventBus
            event_bus = ObservabilityEventBus()
        except ImportError:
            console.print("[yellow]Warning:[/yellow] Event bus not available")

    tracker = ExecutionTracker(event_bus=event_bus) if event_bus else ExecutionTracker()

    # Start dashboard server if requested
    dashboard_server = None
    if dashboard_port is not None and event_bus is not None:
        dashboard_server = _start_dashboard_server(tracker.backend, event_bus, dashboard_port)

    return config_loader, tool_registry, tracker, event_bus, dashboard_server


def _execute_workflow(
    compiled: Any,
    workflow_config: Any,
    inputs: Any,
    tracker: Any,
    config_loader: Any,
    tool_registry: Any,
    workflow_id: str,
    show_details: bool,
    engine: Any,
    verbose: bool,
    workspace: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Any:
    """Execute the compiled workflow with tracking and error handling.

    Args:
        compiled: Compiled workflow graph
        workflow_config: Workflow configuration dict
        inputs: Input values dict
        tracker: ExecutionTracker instance
        config_loader: ConfigLoader instance
        tool_registry: ToolRegistry instance
        workflow_id: Unique workflow execution ID
        show_details: Enable detailed output
        engine: Workflow engine instance
        verbose: Enable verbose output

    Returns:
        Workflow execution result dict

    Raises:
        SystemExit: On execution failure or interruption
    """
    try:
        # Set up streaming display for real-time LLM token visibility
        stream_display = None
        if show_details:
            try:
                from src.cli.stream_display import StreamDisplay
                stream_display = StreamDisplay(console)
            except ImportError:
                pass  # stream_display not available, skip

        state: dict[str, Any] = {
            "workflow_inputs": inputs,
            "tracker": tracker,
            "config_loader": config_loader,
            "tool_registry": tool_registry,
            "workflow_id": workflow_id,
            "show_details": show_details,
            "detail_console": console if show_details else None,
            "stream_callback": stream_display,
        }
        if workspace is not None:
            state["workspace_root"] = workspace
        if run_id is not None:
            state["run_id"] = run_id
        return compiled.invoke(state)
    except WorkflowStageError as e:
        console.print(
            f"[red]Stage failure:[/red] {e.stage_name} — {e}"
        )
        if verbose:
            logger.exception("Stage failure halted workflow")
        _cleanup_tool_executor(engine)
        raise SystemExit(1)
    except (RuntimeError, ValueError) as e:
        console.print(f"[red]Workflow execution error:[/red] {e}")
        if verbose:
            logger.exception("Workflow execution failed")
        _cleanup_tool_executor(engine)
        raise SystemExit(1)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        if 'engine' in locals():
            _cleanup_tool_executor(engine)
        raise SystemExit(EXIT_CODE_KEYBOARD_INTERRUPT)


def _handle_post_execution(
    result: Any,
    show_details: bool,
    output: Optional[str],
    workflow_id: str,
    workflow_name: str,
    verbose: bool,
) -> None:
    """Handle post-execution tasks: summary, reports, gantt chart, and output saving.

    Args:
        result: Workflow execution result
        show_details: Enable detailed output
        output: Optional output file path
        workflow_id: Workflow execution ID
        workflow_name: Workflow name
        verbose: Enable verbose output
    """
    # Display Rich summary
    _print_run_summary(workflow_name, workflow_id, result)

    # Display detailed report if --show-details
    if show_details and isinstance(result, dict):
        try:
            from src.cli.detail_report import print_detailed_report
            print_detailed_report(result, console)
        except ImportError as e:
            logger.debug(f"Could not display detailed report: {e}")
        except Exception as e:  # noqa: BLE001 -- optional feature, non-fatal
            logger.debug(f"Error displaying detailed report: {e}")

    # Display hierarchical gantt chart
    try:
        import sys
        from pathlib import Path as ImportPath
        # Add project root to Python path for examples module
        project_root = ImportPath(__file__).parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from examples.export_waterfall import export_waterfall_trace
        from src.observability.visualize_trace import print_console_gantt

        trace = export_waterfall_trace(workflow_id)
        if "error" not in trace:
            print_console_gantt(trace)
    except ImportError as e:
        logger.debug(f"Could not display gantt chart - module not found: {e}")
    except Exception as e:  # noqa: BLE001 -- optional visualization, non-fatal
        logger.debug(f"Could not display gantt chart: {e}")

    # Save results if --output
    if output:
        try:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(result, f, indent=2, default=str)
            console.print(f"\nResults saved to [cyan]{output}[/cyan]")
        except (IOError, OSError, PermissionError) as e:
            console.print(f"[red]Error saving results:[/red] {e}")
            if verbose:
                logger.exception("Failed to save results")
            # Non-fatal, continue


def _handle_dashboard_keepalive(
    dashboard_server: Optional[Any], dashboard_port: int
) -> None:
    """Keep dashboard server alive until user interrupts.

    Args:
        dashboard_server: uvicorn.Server instance or None
        dashboard_port: Dashboard port number
    """
    if dashboard_server is None:
        return

    console.print(
        f"\n[cyan]Dashboard running at http://localhost:{dashboard_port}[/cyan] "
        "(Ctrl+C to exit)"
    )
    try:
        import signal
        signal.pause()  # Wait for Ctrl+C
    except (KeyboardInterrupt, AttributeError):
        # AttributeError: signal.pause() not available on Windows
        try:
            import time
            while True:
                time.sleep(1)  # Intentional blocking: keep-alive loop for dashboard server; Windows fallback for signal.pause()
        except KeyboardInterrupt:
            pass
    console.print("\n[yellow]Dashboard stopped[/yellow]")


@main.command()
@click.argument("workflow", type=click.Path(exists=True))
@click.option(
    "--input",
    "input_file",
    type=click.Path(exists=True),
    help="YAML file with input values",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option(
    "--output", "-o", type=click.Path(), help="Save results to JSON file"
)
@click.option("--db", type=click.Path(), help="Database path override")
@click.option(
    "--config-root",
    default="configs",
    show_default=True,
    envvar="MAF_CONFIG_ROOT",
    help="Config directory root",
)
@click.option(
    "--show-details",
    "-d",
    is_flag=True,
    help="Show real-time agent progress and detailed post-execution report",
)
@click.option(
    "--dashboard",
    type=int,
    default=None,
    is_flag=True,
    flag_value=DEFAULT_DASHBOARD_PORT,
    help="Launch live dashboard (default port: 8420)",
)
@click.option(
    "--workspace",
    type=click.Path(),
    default=None,
    envvar="MAF_WORKSPACE",
    help="Restrict file operations to this directory",
)
@click.option(
    "--events-to",
    type=click.Choice(["stderr", "stdout", "file"]),
    default="stderr",
    show_default=True,
    help="Where to route observability events",
)
@click.option(
    "--event-format",
    type=click.Choice(["text", "json", "jsonl"]),
    default="text",
    show_default=True,
    help="Event output format",
)
@click.option(
    "--run-id",
    type=str,
    default=None,
    help="Externally-provided run ID for tracking",
)
def run(
    workflow: str,
    input_file: Optional[str],
    verbose: bool,
    output: Optional[str],
    db: Optional[str],
    config_root: str,
    show_details: bool,
    dashboard: Optional[int],
    workspace: Optional[str],
    events_to: str,
    event_format: str,
    run_id: Optional[str],
) -> None:
    """Run a workflow from a YAML config file."""
    # 1. Setup logging
    _setup_logging(verbose, show_details)

    # 2. Load workflow config and inputs
    workflow_config, inputs = _load_workflow_config(workflow, input_file, config_root, verbose)

    # 3. Initialize infrastructure (db, registries, tracker, dashboard)
    db_path = db or DEFAULT_DB_PATH
    # Create event bus when events-to or dashboard is requested
    needs_event_bus = dashboard is not None or events_to != "stderr" or event_format != "text"
    config_loader, tool_registry, tracker, event_bus, dashboard_server = _initialize_infrastructure(
        config_root, db_path, dashboard if dashboard is not None else (0 if needs_event_bus else None), verbose
    )

    # 3b. Set up event output routing if requested
    event_output_handler = None
    if event_bus and (events_to != "stderr" or event_format != "text"):
        try:
            from src.cli.event_output import EventOutputHandler
            event_output_handler = EventOutputHandler(
                mode=events_to,
                fmt=event_format,
                run_id=run_id,
            )
            event_bus.subscribe(event_output_handler.handle_event)
        except ImportError:
            if verbose:
                console.print("[yellow]Warning:[/yellow] Event output routing not available")

    # 4. Compile workflow
    try:
        from src.compiler.engine_registry import EngineRegistry
        registry = EngineRegistry()
        engine = registry.get_engine_from_config(
            workflow_config,
            tool_registry=tool_registry,
            config_loader=config_loader,
        )
        compiled = engine.compile(workflow_config)
    except (ValueError, KeyError, AttributeError) as e:
        console.print(f"[red]Workflow compilation error:[/red] {e}")
        if verbose:
            logger.exception("Failed to compile workflow")
        raise SystemExit(1)

    # 5. Execute workflow with tracking
    wf = workflow_config.get("workflow", {})
    workflow_name = wf.get("name", Path(workflow).stem)
    with tracker.track_workflow(
        workflow_name=workflow_name,
        workflow_config=workflow_config,
        trigger_type="cli",
        environment="local",
    ) as workflow_id:
        result = _execute_workflow(
            compiled, workflow_config, inputs, tracker,
            config_loader, tool_registry, workflow_id,
            show_details, engine, verbose,
            workspace=workspace,
            run_id=run_id,
        )

    # 6. Handle post-execution (reports, gantt, output saving)
    _handle_post_execution(result, show_details, output, workflow_id, workflow_name, verbose)

    # 7. Keep dashboard alive if enabled
    if dashboard is not None:
        _handle_dashboard_keepalive(dashboard_server, dashboard)

    # 8. Cleanup resources
    _cleanup_tool_executor(engine)



def _print_run_summary(
    workflow_name: str, workflow_id: str, result: object
) -> None:
    """Print a Rich summary table after a workflow run."""
    table = Table(title=f"Workflow: {workflow_name}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("Workflow ID", workflow_id)

    if not isinstance(result, dict):
        table.add_row("Result", str(result))
        console.print()
        console.print(table)
        return

    status = result.get("status", "completed")
    style = "green" if status == "completed" else "red"
    table.add_row("Status", f"[{style}]{status}[/{style}]")

    if "duration" in result:
        table.add_row("Duration", f"{result['duration']:.1f}s")
    if "total_tokens" in result:
        table.add_row("Tokens", str(result["total_tokens"]))
    if "total_cost" in result:
        table.add_row("Cost", f"${result['total_cost']:.4f}")

    console.print()
    console.print(table)


# ─── dashboard command ────────────────────────────────────────────────


@main.command()
@click.option("--port", default=DEFAULT_DASHBOARD_PORT, show_default=True, help="Dashboard port")
@click.option("--db", default=None, help="Database path")
def dashboard(port: int, db: Optional[str]) -> None:
    """Launch dashboard to browse past workflow executions."""
    try:
        import uvicorn

        from src.dashboard.app import create_app
    except ImportError as e:
        console.print(
            f"[red]Error:[/red] Dashboard dependencies not installed: {e}\n"
            "Install with: pip install 'meta-autonomous-framework[dashboard]'"
        )
        raise SystemExit(1)

    from src.observability.backends import SQLObservabilityBackend
    from src.observability.event_bus import ObservabilityEventBus
    from src.observability.tracker import ExecutionTracker

    # Init database
    db_path = db or DEFAULT_DB_PATH
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        ExecutionTracker.ensure_database(f"sqlite:///{db_path}")
    except (OSError, PermissionError) as e:
        console.print(f"[red]Database error:[/red] {e}")
        raise SystemExit(1)

    backend = SQLObservabilityBackend(buffer=False)
    event_bus = ObservabilityEventBus()
    app = create_app(backend=backend, event_bus=event_bus)

    console.print(f"\n[cyan]MAF Dashboard[/cyan] running at http://localhost:{port}")
    console.print("Press Ctrl+C to stop\n")

    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")  # noqa: S104  # nosec B104
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped[/yellow]")


# ─── serve command ────────────────────────────────────────────────────


@main.command()
@click.option("--host", default="0.0.0.0", show_default=True, envvar="MAF_HOST", help="Bind address")  # noqa: S104
@click.option("--port", default=8420, show_default=True, envvar="MAF_PORT", help="Listen port")
@click.option(
    "--config-root",
    default="configs",
    show_default=True,
    envvar="MAF_CONFIG_ROOT",
    help="Config directory root",
)
@click.option("--db", default=None, envvar="MAF_DB_PATH", help="Database path")
@click.option("--workers", default=4, show_default=True, envvar="MAF_MAX_WORKERS", help="Max concurrent workflows")
@click.option("--reload", "dev_reload", is_flag=True, help="Auto-reload on code changes (dev mode)")
def serve(host: str, port: int, config_root: str, db: Optional[str], workers: int, dev_reload: bool) -> None:
    """Start MAF HTTP API server for programmatic workflow execution."""
    try:
        import uvicorn

        from src.dashboard.app import create_app
    except ImportError as e:
        console.print(
            f"[red]Error:[/red] Server dependencies not installed: {e}\n"
            "Install with: pip install 'meta-autonomous-framework[dashboard]'"
        )
        raise SystemExit(1)

    from src.observability.backends import SQLObservabilityBackend
    from src.observability.event_bus import ObservabilityEventBus
    from src.observability.tracker import ExecutionTracker

    # Init database
    db_path = db or DEFAULT_DB_PATH
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        ExecutionTracker.ensure_database(f"sqlite:///{db_path}")
    except (OSError, PermissionError) as e:
        console.print(f"[red]Database error:[/red] {e}")
        raise SystemExit(1)

    backend = SQLObservabilityBackend(buffer=False)
    event_bus = ObservabilityEventBus()
    app = create_app(
        backend=backend,
        event_bus=event_bus,
        mode="server",
        config_root=config_root,
        max_workers=workers,
    )

    console.print(f"\n[cyan]MAF Server[/cyan] listening on http://{host}:{port}")
    console.print("Press Ctrl+C to stop\n")

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")  # noqa: S104  # nosec B104
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped[/yellow]")


# ─── validate command ─────────────────────────────────────────────────


@main.command()
@click.argument("workflow", type=click.Path(exists=True))
@click.option(
    "--config-root",
    default="configs",
    show_default=True,
    envvar="MAF_CONFIG_ROOT",
    help="Config directory root",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format (text or json for CI/CD)",
)
@click.option(
    "--check-refs",
    is_flag=True,
    help="Validate cross-references (stages, agents)",
)
def validate(workflow: str, config_root: str, output_format: str, check_refs: bool) -> None:
    """Validate a workflow config without running it."""
    errors: list[str] = []
    warnings: list[str] = []

    # Schema validation
    try:
        workflow_config = _load_and_validate_workflow(workflow, verbose=(output_format == "text"))
    except SystemExit:
        if output_format == "json":
            console.print(json.dumps({"valid": False, "errors": ["Schema validation failed"], "warnings": []}))
        raise

    # Check stage references (always, plus deep check with --check-refs)
    wf = workflow_config.get("workflow", {})
    workflow_dir = Path(workflow).parent
    for stage in wf.get("stages", []):
        stage_ref = stage.get("stage_ref", "")
        if not stage_ref:
            continue

        # Try resolving relative to CWD first, then relative to workflow dir
        stage_path = Path(stage_ref)
        if not stage_path.exists():
            stage_path = workflow_dir / stage_ref
        if not stage_path.exists():
            stage_path = Path(config_root) / stage_ref
        if not stage_path.exists():
            errors.append(f"Stage file not found: {stage_ref}")
            continue

        if not check_refs:
            continue

        # Load stage and check agent references
        with open(stage_path) as f:
            stage_config = yaml.safe_load(f)

        if not stage_config:
            continue

        for agent_entry in stage_config.get("stage", {}).get("agents", []):
            if isinstance(agent_entry, str):
                agent_name = agent_entry
            elif isinstance(agent_entry, dict):
                agent_name = agent_entry.get("name", "")
            else:
                continue
            if not agent_name:
                continue
            agent_path = Path(config_root) / "agents" / f"{agent_name}.yaml"
            if not agent_path.exists():
                errors.append(f"Agent config not found: {agent_path}")

    is_valid = len(errors) == 0

    if output_format == "json":
        console.print(json.dumps({"valid": is_valid, "errors": errors, "warnings": warnings}))
    else:
        if errors:
            console.print("[red]Reference errors:[/red]")
            for err in errors:
                console.print(f"  - {err}")
        else:
            console.print("[green]All references valid[/green]")

    if not is_valid:
        raise SystemExit(1)


# ─── config group ─────────────────────────────────────────────────────


@main.group("config")
def config_group() -> None:
    """Configuration management commands."""
    pass


@config_group.command("check")
@click.option(
    "--config-root",
    default="configs",
    show_default=True,
    envvar="MAF_CONFIG_ROOT",
    help="Config directory root",
)
@click.option("--fail-on-warning", is_flag=True, help="Exit 1 on warnings too")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def config_check(config_root: str, fail_on_warning: bool, verbose: bool) -> None:
    """Validate all configs: schemas, stage refs, agent refs, tool refs."""
    errors: list[str] = []
    warnings: list[str] = []
    workflows_dir = Path(config_root) / "workflows"

    if not workflows_dir.exists():
        console.print(f"[red]Workflows directory not found:[/red] {workflows_dir}")
        raise SystemExit(1)

    for wf_path in sorted(workflows_dir.glob("*.yaml")):
        try:
            with open(wf_path) as f:
                wf_config = yaml.safe_load(f)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{wf_path.name}: YAML parse error — {exc}")
            continue

        if not wf_config:
            warnings.append(f"{wf_path.name}: empty file")
            continue

        wf = wf_config.get("workflow", {})
        if not wf:
            errors.append(f"{wf_path.name}: missing 'workflow' key")
            continue

        # Validate schema
        try:
            from src.compiler.schemas import WorkflowConfig as WfSchema
            WfSchema(**wf_config)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{wf_path.name}: schema error — {exc}")

        # Check stage references
        for stage in wf.get("stages", []):
            stage_ref = stage.get("stage_ref", "")
            if not stage_ref:
                continue

            stage_path = Path(config_root) / stage_ref
            if not stage_path.exists():
                stage_path = Path(stage_ref)
            if not stage_path.exists():
                errors.append(f"{wf_path.name}: stage not found — {stage_ref}")
                continue

            # Check agent refs inside stage
            try:
                with open(stage_path) as f:
                    stage_config = yaml.safe_load(f)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{stage_ref}: YAML parse error — {exc}")
                continue

            if not stage_config:
                continue

            for agent_entry in stage_config.get("stage", {}).get("agents", []):
                if isinstance(agent_entry, str):
                    agent_name = agent_entry
                elif isinstance(agent_entry, dict):
                    agent_name = agent_entry.get("name", "")
                else:
                    continue
                if not agent_name:
                    continue

                agent_path = Path(config_root) / "agents" / f"{agent_name}.yaml"
                if not agent_path.exists():
                    errors.append(f"{stage_ref}: agent not found — {agent_name}")
                    continue

                # Check tool refs inside agent
                if verbose:
                    try:
                        with open(agent_path) as f:
                            agent_config = yaml.safe_load(f)
                        agent_tools = agent_config.get("agent", {}).get("tools", None)
                        if agent_tools is not None:
                            for tool_entry in agent_tools:
                                tool_name = tool_entry if isinstance(tool_entry, str) else tool_entry.get("name", "")
                                if tool_name:
                                    tool_path = Path(config_root) / "tools" / f"{tool_name}.yaml"
                                    if not tool_path.exists():
                                        warnings.append(f"{agent_name}: tool config not found — {tool_name}")
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"{agent_name}: could not check tools — {exc}")

    # Report results
    if errors:
        console.print(f"\n[red]Errors ({len(errors)}):[/red]")
        for err in errors:
            console.print(f"  ✗ {err}")

    if warnings:
        console.print(f"\n[yellow]Warnings ({len(warnings)}):[/yellow]")
        for warn in warnings:
            console.print(f"  ⚠ {warn}")

    if not errors and not warnings:
        console.print("[green]All configs valid[/green]")
    elif not errors:
        console.print(f"\n[green]No errors[/green] ({len(warnings)} warning(s))")

    if errors or (fail_on_warning and warnings):
        raise SystemExit(1)


# ─── list group ───────────────────────────────────────────────────────


@main.group("list")
def list_group() -> None:
    """List available resources."""
    pass


@list_group.command("workflows")
@click.option("--config-root", default="configs", show_default=True, envvar="MAF_CONFIG_ROOT")
def list_workflows(config_root: str) -> None:
    """List available workflow configs."""
    workflows_dir = Path(config_root) / "workflows"
    if not workflows_dir.exists():
        console.print(f"[red]Directory not found:[/red] {workflows_dir}")
        raise SystemExit(1)

    table = Table(title="Available Workflows")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Stages", style="yellow")

    for path in sorted(workflows_dir.glob("*.yaml")):
        with open(path) as f:
            config = yaml.safe_load(f)
        if not config:
            continue
        wf = config.get("workflow", {})
        stages = [s.get("name", "?") for s in wf.get("stages", [])]
        table.add_row(
            wf.get("name", path.stem),
            wf.get("description", ""),
            ", ".join(stages),
        )

    console.print(table)


@list_group.command("agents")
@click.option("--config-root", default="configs", show_default=True, envvar="MAF_CONFIG_ROOT")
def list_agents(config_root: str) -> None:
    """List available agent configs."""
    agents_dir = Path(config_root) / "agents"
    if not agents_dir.exists():
        console.print(f"[red]Directory not found:[/red] {agents_dir}")
        raise SystemExit(1)

    table = Table(title="Available Agents")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Type", style="yellow")

    for path in sorted(agents_dir.glob("*.yaml")):
        with open(path) as f:
            config = yaml.safe_load(f)
        if not config:
            continue
        agent = config.get("agent", {})
        table.add_row(
            agent.get("name", path.stem),
            agent.get("description", ""),
            agent.get("type", ""),
        )

    console.print(table)


@list_group.command("stages")
@click.option("--config-root", default="configs", show_default=True, envvar="MAF_CONFIG_ROOT")
def list_stages(config_root: str) -> None:
    """List available stage configs."""
    stages_dir = Path(config_root) / "stages"
    if not stages_dir.exists():
        console.print(f"[red]Directory not found:[/red] {stages_dir}")
        raise SystemExit(1)

    table = Table(title="Available Stages")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Agents", style="yellow")

    for path in sorted(stages_dir.glob("*.yaml")):
        with open(path) as f:
            config = yaml.safe_load(f)
        if not config:
            continue
        stage = config.get("stage", {})
        agents = stage.get("agents", [])
        agent_names = []
        for a in agents:
            if isinstance(a, str):
                agent_names.append(a)
            elif isinstance(a, dict):
                agent_names.append(a.get("name", "?"))
        table.add_row(
            stage.get("name", path.stem),
            stage.get("description", ""),
            ", ".join(agent_names),
        )

    console.print(table)


# ─── Mount existing rollback group ────────────────────────────────────

from src.cli.rollback import rollback  # noqa: E402

main.add_command(rollback)


# ─── m5 group ─────────────────────────────────────────────────────────


@main.group()
def m5() -> None:
    """M5 self-improvement commands."""
    pass


def _get_m5_cli() -> Any:
    """Lazy-load M5CLI to avoid import-time side effects."""
    try:
        from src.self_improvement.cli import M5CLI

        return M5CLI()
    except ImportError as e:
        console.print(
            f"[red]Error:[/red] M5 self-improvement module not available: {e}"
        )
        raise SystemExit(1)
    except Exception as e:  # noqa: BLE001 -- CLI init catch-all
        console.print(f"[red]Error:[/red] Failed to initialize M5 CLI: {e}")
        raise SystemExit(1)


@m5.command("run")
@click.argument("agent_name")
@click.option("--config", "config_file", type=click.Path(exists=True), help="Config file")
def m5_run(agent_name: str, config_file: Optional[str]) -> None:
    """Run improvement iteration for an agent."""
    cli = _get_m5_cli()
    code = cli.run_iteration(agent_name, config_file)
    if code:
        raise SystemExit(code)


@m5.command("analyze")
@click.argument("agent_name")
@click.option(
    "--window",
    type=int,
    default=HOURS_PER_WEEK,  # 168 hours = 1 week
    show_default=True,
    help="Analysis window in hours",
)
def m5_analyze(agent_name: str, window: int) -> None:
    """Analyze agent performance."""
    cli = _get_m5_cli()
    code = cli.analyze(agent_name, window)
    if code:
        raise SystemExit(code)


@m5.command("optimize")
@click.argument("agent_name")
@click.option("--config", "config_file", type=click.Path(exists=True), help="Config file")
def m5_optimize(agent_name: str, config_file: Optional[str]) -> None:
    """Optimize agent (alias for run)."""
    cli = _get_m5_cli()
    code = cli.optimize(agent_name, config_file)
    if code:
        raise SystemExit(code)


@m5.command("status")
@click.argument("agent_name")
def m5_status(agent_name: str) -> None:
    """Show loop status for an agent."""
    cli = _get_m5_cli()
    code = cli.status(agent_name)
    if code:
        raise SystemExit(code)


@m5.command("metrics")
@click.argument("agent_name")
def m5_metrics(agent_name: str) -> None:
    """Show metrics for an agent."""
    cli = _get_m5_cli()
    code = cli.metrics(agent_name)
    if code:
        raise SystemExit(code)


@m5.command("pause")
@click.argument("agent_name")
def m5_pause(agent_name: str) -> None:
    """Pause loop for an agent."""
    cli = _get_m5_cli()
    code = cli.pause(agent_name)
    if code:
        raise SystemExit(code)


@m5.command("resume")
@click.argument("agent_name")
def m5_resume(agent_name: str) -> None:
    """Resume loop for an agent."""
    cli = _get_m5_cli()
    code = cli.resume(agent_name)
    if code:
        raise SystemExit(code)


@m5.command("reset")
@click.argument("agent_name")
def m5_reset(agent_name: str) -> None:
    """Reset loop state for an agent."""
    cli = _get_m5_cli()
    code = cli.reset(agent_name)
    if code:
        raise SystemExit(code)


@m5.command("health")
def m5_health() -> None:
    """Check M5 system health."""
    cli = _get_m5_cli()
    code = cli.health()
    if code:
        raise SystemExit(code)


@m5.command("check-experiments")
@click.argument("agent_name")
def m5_check_experiments(agent_name: str) -> None:
    """Check experiment status for an agent."""
    cli = _get_m5_cli()
    code = cli.check_experiments(agent_name)
    if code:
        raise SystemExit(code)


@m5.command("list-agents")
def m5_list_agents() -> None:
    """List all agents with M5 state."""
    cli = _get_m5_cli()
    code = cli.list_agents()
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
