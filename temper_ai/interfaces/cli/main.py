"""
Unified CLI for Temper AI.

Entry point: `temper-ai`

Commands:
    temper-ai run <workflow>          Run a workflow from a YAML config
    temper-ai dashboard               Launch dashboard to browse past executions
    temper-ai validate <workflow>     Validate workflow config without running
    temper-ai list workflows          List available workflows
    temper-ai list agents             List available agents
    temper-ai list stages             List available stages
    temper-ai rollback ...            Rollback operations
    temper-ai m5 ...                  M5 self-improvement commands
    temper-ai memory ...              Memory management commands
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import click
import yaml
from rich.console import Console
from rich.table import Table

from temper_ai.interfaces.cli.constants import (
    CLI_OPTION_API_KEY,
    CLI_OPTION_CONFIG_ROOT,
    CLI_OPTION_DB,
    CLI_OPTION_SERVER,
    COLUMN_DESCRIPTION,
    COLUMN_NAME,
    COLUMN_STATUS,
    DEFAULT_CONFIG_ROOT,
    DEFAULT_SERVER_HOST,
    ENV_VAR_API_KEY,
    ENV_VAR_CONFIG_ROOT,
    ENV_VAR_SERVER_URL,
    ERROR_DIR_NOT_FOUND,
    HELP_CONFIG_ROOT,
    SQLITE_URL_PREFIX,
    YAML_FILE_EXTENSION,
    YAML_GLOB_PATTERN,
)
from temper_ai.shared.utils.exceptions import WorkflowStageError

console = Console()
logger = logging.getLogger(__name__)

# Project root for resolving paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = ".meta-autonomous/observability.db"
DEFAULT_DASHBOARD_PORT = 8420
DEFAULT_HOST = "127.0.0.1"  # Secure default: localhost only
DEFAULT_MAX_WORKERS = 4

# Exit codes
EXIT_CODE_KEYBOARD_INTERRUPT = 130  # POSIX standard exit code for SIGINT (Ctrl+C)


# ─── Data Classes ─────────────────────────────────────────────────────


@dataclass
class WorkflowExecutionParams:
    """Parameters for workflow execution (reduces 12 params to 7)."""
    compiled: Any
    workflow_config: Any
    inputs: Any
    tracker: Any
    config_loader: Any
    tool_registry: Any
    workflow_id: str
    show_details: bool
    engine: Any
    verbose: bool
    workspace: Optional[str] = None
    run_id: Optional[str] = None
    workflow_name: str = ""


@dataclass
class WorkflowStateParams:
    """Parameters for building workflow state."""
    inputs: Any
    tracker: Any
    config_loader: Any
    tool_registry: Any
    workflow_id: str
    show_details: bool
    workspace: Optional[str] = None
    run_id: Optional[str] = None
    workflow_name: str = ""


# ─── Helpers ──────────────────────────────────────────────────────────


def _load_and_validate_workflow(
    workflow_path: str, verbose: bool = False
) -> Any:
    """Load a workflow YAML file and validate against schema.

    Returns the parsed workflow config dict.
    Raises SystemExit(1) on validation failure.
    """
    from temper_ai.workflow._schemas import WorkflowConfig as WorkflowConfigSchema

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
@click.version_option(package_name="temper-ai", prog_name="temper-ai")
def main() -> None:
    """Temper AI CLI."""
    pass


# ─── run command ──────────────────────────────────────────────────────


def _setup_logging(verbose: bool, show_details: bool) -> None:
    """Configure logging based on verbosity and detail flags.

    Uses the canonical ``setup_logging()`` from ``temper_ai.shared.utils.logging``
    which attaches the ``ExecutionContextFilter`` to inject workflow/stage/agent
    IDs and optional OTEL trace IDs into every log record.

    Args:
        verbose: Enable DEBUG level logging
        show_details: Attach RichHandler for INFO level streaming logs
    """
    from temper_ai.shared.utils.logging import setup_logging

    if verbose:
        setup_logging(level="DEBUG", format_type="console")
    elif show_details:
        setup_logging(level="INFO", format_type="rich")
    else:
        setup_logging(level="WARNING", format_type="console")


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

        from temper_ai.interfaces.dashboard.app import create_app

        app = create_app(backend=backend, event_bus=event_bus)
        config = uvicorn.Config(app, host=DEFAULT_SERVER_HOST, port=port, log_level="warning")  # nosec B104
        dashboard_server = uvicorn.Server(config)
        thread = threading.Thread(target=dashboard_server.run, daemon=True)
        thread.start()
        console.print(f"\n[cyan]Dashboard:[/cyan] http://localhost:{port}\n")
        return dashboard_server
    except ImportError as e:
        console.print(
            f"[yellow]Warning:[/yellow] Dashboard not available: {e}\n"
            "Install: pip install 'temper-ai[dashboard]'"
        )
        return None


def _import_core_modules(verbose: bool) -> tuple:
    """Import and return core infrastructure modules, exiting on failure.

    Returns:
        Tuple of (ConfigLoader, ExecutionTracker, ToolRegistry) classes.

    Raises:
        SystemExit: If imports fail.
    """
    try:
        from temper_ai.workflow.config_loader import ConfigLoader
        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.tools.registry import ToolRegistry
        return ConfigLoader, ExecutionTracker, ToolRegistry
    except ImportError as e:
        console.print(f"[red]Import error:[/red] {e}")
        if verbose:
            logger.exception("Failed to import required modules")
        raise SystemExit(1)


def _init_database(db_path: str, ensure_database_fn: Any, verbose: bool) -> None:
    """Create the database directory and ensure schema exists.

    Raises:
        SystemExit: On filesystem or database errors.
    """
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        ensure_database_fn(f"{SQLITE_URL_PREFIX}{db_path}")
    except (OSError, PermissionError) as e:
        console.print(f"[red]Database initialization error:[/red] {e}")
        if verbose:
            logger.exception("Failed to initialize database")
        raise SystemExit(1)


def _create_tracker(event_bus: Any, verbose: bool) -> Any:
    """Create an ExecutionTracker with OTEL composite backend if available.

    Returns:
        Configured ExecutionTracker instance.
    """
    from temper_ai.observability.tracker import ExecutionTracker
    from temper_ai.observability.otel_setup import init_otel, create_otel_backend

    init_otel()
    otel_backend = create_otel_backend()

    if otel_backend is not None:
        from temper_ai.observability.backends.composite_backend import CompositeBackend
        from temper_ai.observability.backends import SQLObservabilityBackend as _SQLBackend
        sql_backend = _SQLBackend()
        composite = CompositeBackend(primary=sql_backend, secondaries=[otel_backend])
        tracker = ExecutionTracker(backend=composite, event_bus=event_bus)
        if verbose:
            console.print("[cyan]OTEL[/cyan] backend active (composite mode)")
        return tracker

    return ExecutionTracker(event_bus=event_bus) if event_bus else ExecutionTracker()


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
    ConfigLoader, ExecutionTracker, ToolRegistry = _import_core_modules(verbose)
    _init_database(db_path, ExecutionTracker.ensure_database, verbose)

    config_loader = ConfigLoader(config_root=config_root)
    tool_registry = ToolRegistry(auto_discover=True)

    # Create event bus (needed for dashboard)
    event_bus = None
    if dashboard_port is not None:
        try:
            from temper_ai.observability.event_bus import ObservabilityEventBus
            event_bus = ObservabilityEventBus()
        except ImportError:
            console.print("[yellow]Warning:[/yellow] Event bus not available")

    tracker = _create_tracker(event_bus, verbose)

    # Start dashboard server if requested
    dashboard_server = None
    if dashboard_port is not None and event_bus is not None:
        dashboard_server = _start_dashboard_server(tracker.backend, event_bus, dashboard_port)

    return config_loader, tool_registry, tracker, event_bus, dashboard_server


def _build_workflow_state(params: WorkflowStateParams) -> dict[str, Any]:
    """Build workflow state dict with optional stream display.

    Args:
        params: WorkflowStateParams with all state parameters

    Returns:
        State dict for workflow execution
    """
    stream_display = None
    if params.show_details:
        try:
            from temper_ai.interfaces.cli.stream_display import StreamDisplay
            stream_display = StreamDisplay(console)
        except ImportError:
            pass  # stream_display not available, skip

    state: dict[str, Any] = {
        "workflow_inputs": params.inputs,
        "tracker": params.tracker,
        "config_loader": params.config_loader,
        "tool_registry": params.tool_registry,
        "workflow_id": params.workflow_id,
        "show_details": params.show_details,
        "detail_console": console if params.show_details else None,
        "stream_callback": stream_display,
        "workflow_name": params.workflow_name,
    }
    if params.workspace is not None:
        state["workspace_root"] = params.workspace
    if params.run_id is not None:
        state["run_id"] = params.run_id
    return state


# Keys in workflow state that are infrastructure (non-serializable).
# Everything else (stage_outputs, status, etc.) is data the evaluator needs.
_INFRA_STATE_KEYS = frozenset({
    "tracker", "config_loader", "tool_registry", "detail_console",
    "stream_callback", "show_details",
})


class _CritiqueLLM:
    """Adapter: wraps BaseLLM.complete() as .generate() for OptimizationEngine."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def generate(self, prompt: str) -> str:
        """Generate a text completion."""
        response = self._llm.complete(prompt)
        return str(response.content)


def _create_critique_llm(workflow_config: dict) -> Optional[Any]:
    """Try to create an LLM for optimization critique from the first agent.

    Reads the stage_ref YAML directly, extracts the first agent name,
    then loads the agent config to get the inference provider/model/url.
    """
    try:
        wf = workflow_config.get("workflow", {})
        stages = wf.get("stages", [])
        if not stages:
            return None
        stage_ref = stages[0].get("stage_ref")
        if not stage_ref:
            return None
        with open(stage_ref) as f:
            stage_config = yaml.safe_load(f)
        agents = stage_config.get("stage", {}).get("agents", [])
        if not agents:
            return None
        agent_name = agents[0] if isinstance(agents[0], str) else agents[0].get("name")
        agent_path = Path("configs/agents") / f"{agent_name}.yaml"
        with open(agent_path) as f:
            agent_config = yaml.safe_load(f)
        inference = agent_config.get("agent", {}).get("inference", {})
        provider = inference.get("provider", "vllm")
        model = inference.get("model")
        base_url = inference.get("base_url")
        if not model or not base_url:
            return None
        from temper_ai.llm.providers.vllm_provider import VllmLLM
        raw_llm: Any
        if provider == "ollama":
            from temper_ai.llm.providers.ollama import OllamaLLM
            raw_llm = OllamaLLM(model=model, base_url=base_url)
        else:
            raw_llm = VllmLLM(model=model, base_url=base_url)
        return _CritiqueLLM(raw_llm)
    except Exception:  # noqa: BLE001 -- optional feature, fall back gracefully
        logger.debug("Could not create critique LLM, using fallback")
        return None


def _create_experiment_service() -> Optional[Any]:
    """Create and initialize ExperimentService for optimization tracking."""
    try:
        from temper_ai.experimentation.service import ExperimentService

        service = ExperimentService()
        service.initialize()
        return service
    except Exception:  # noqa: BLE001 -- optional feature, fall back gracefully
        logger.debug("Could not create ExperimentService, optimization tracking disabled")
        return None


def _log_optimization_summary(result: Any) -> None:
    """Log optimization result summary including experiment details."""
    logger.info(
        "Optimization complete: %d iterations, score=%.2f",
        result.iterations,
        result.score,
    )

    if result.experiment_id:
        logger.info("Experiment ID: %s", result.experiment_id)

    if result.experiment_results:
        rec = result.experiment_results.get("recommendation")
        confidence = result.experiment_results.get("confidence", 0.0)
        winner = result.experiment_results.get("recommended_winner")
        logger.info(
            "Experiment: recommendation=%s, confidence=%.2f, winner=%s",
            rec,
            confidence,
            winner,
        )


class _CLIWorkflowRunner:
    """Thin wrapper so OptimizationEngine can re-execute the workflow."""

    def __init__(self, compiled: Any, state_template: dict) -> None:
        self._compiled = compiled
        self._state_template = state_template

    def execute(self, input_data: Any) -> Any:
        """Run the workflow and return only serializable output.

        Shallow-copies the state template (infrastructure objects like tracker,
        config_loader are shared across runs), runs the workflow, then strips
        non-serializable infrastructure keys so the evaluator can json.dumps().
        """
        state = dict(self._state_template)
        if isinstance(input_data, dict):
            state["workflow_inputs"] = dict(input_data)
        result = self._compiled.invoke(state)
        if isinstance(result, dict):
            return {k: v for k, v in result.items() if k not in _INFRA_STATE_KEYS}
        return result


def _execute_workflow(params: WorkflowExecutionParams) -> Any:
    """Execute the compiled workflow with tracking and error handling.

    Args:
        params: WorkflowExecutionParams bundle containing all needed parameters

    Returns:
        Workflow execution result dict

    Raises:
        SystemExit: On execution failure or interruption
    """
    try:
        state = _build_workflow_state(
            WorkflowStateParams(
                inputs=params.inputs,
                tracker=params.tracker,
                config_loader=params.config_loader,
                tool_registry=params.tool_registry,
                workflow_id=params.workflow_id,
                show_details=params.show_details,
                workspace=params.workspace,
                run_id=params.run_id,
                workflow_name=params.workflow_name,
            )
        )

        # Wire optimization engine if configured
        opt_raw = params.workflow_config.get("workflow", {}).get("optimization")
        if opt_raw and opt_raw.get("enabled", True):
            from temper_ai.improvement import OptimizationConfig, OptimizationEngine

            logger.info("Optimization enabled — running optimization pipeline")
            opt_config = OptimizationConfig.model_validate(opt_raw)
            critique_llm = _create_critique_llm(params.workflow_config)
            experiment_service = _create_experiment_service()
            opt_engine = OptimizationEngine(
                config=opt_config,
                llm=critique_llm,
                experiment_service=experiment_service,
            )
            runner = _CLIWorkflowRunner(params.compiled, state)
            opt_result = opt_engine.run(runner, params.inputs)
            _log_optimization_summary(opt_result)
            return opt_result.output

        return params.compiled.invoke(state)
    except WorkflowStageError as e:
        console.print(f"[red]Stage failure:[/red] {e.stage_name} — {e}")
        if params.verbose:
            logger.exception("Stage failure halted workflow")
        _cleanup_tool_executor(params.engine)
        raise SystemExit(1)
    except (RuntimeError, ValueError) as e:
        console.print(f"[red]Workflow execution error:[/red] {e}")
        if params.verbose:
            logger.exception("Workflow execution failed")
        _cleanup_tool_executor(params.engine)
        raise SystemExit(1)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        _cleanup_tool_executor(params.engine)
        raise SystemExit(EXIT_CODE_KEYBOARD_INTERRUPT)


def _display_detailed_report(result: Any) -> None:
    """Display detailed report if result is a dict."""
    if not isinstance(result, dict):
        return
    try:
        from temper_ai.interfaces.cli.detail_report import print_detailed_report
        print_detailed_report(result, console)
    except ImportError as e:
        logger.debug(f"Could not display detailed report: {e}")
    except Exception as e:  # noqa: BLE001 -- optional feature, non-fatal
        logger.debug(f"Error displaying detailed report: {e}")


def _display_gantt_chart(workflow_id: str) -> None:
    """Display hierarchical gantt chart for the workflow run."""
    try:
        import sys
        from pathlib import Path as ImportPath
        project_root = ImportPath(__file__).parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from examples.export_waterfall import export_waterfall_trace
        from temper_ai.observability.visualize_trace import print_console_gantt

        trace = export_waterfall_trace(workflow_id)
        if "error" not in trace:
            print_console_gantt(trace)
    except ImportError as e:
        logger.debug(f"Could not display gantt chart - module not found: {e}")
    except Exception as e:  # noqa: BLE001 -- optional visualization, non-fatal
        logger.debug(f"Could not display gantt chart: {e}")


def _save_results(output: str, result: Any, verbose: bool) -> None:
    """Save workflow results to a JSON file."""
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


def _run_autonomous_loop(
    workflow_config: dict,
    workflow_id: str,
    workflow_name: str,
    result: Any,
    verbose: bool,
    cli_autonomous: bool = False,
) -> None:
    """Run post-execution autonomous loop if enabled."""
    from temper_ai.autonomy._schemas import AutonomousLoopConfig, WorkflowRunContext
    from temper_ai.autonomy.orchestrator import PostExecutionOrchestrator

    wf = workflow_config.get("workflow", {})
    loop_raw = wf.get("autonomous_loop", {})
    config = AutonomousLoopConfig(**loop_raw)

    # CLI --autonomous flag overrides YAML
    if cli_autonomous:
        config.enabled = True

    if not config.enabled:
        return

    # Build context from result
    result_dict = result if isinstance(result, dict) else {}
    context = WorkflowRunContext(
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        product_type=wf.get("product_type"),
        result=result_dict,
        duration_seconds=result_dict.get("duration", 0.0),
        status=result_dict.get("status", "unknown"),
        cost_usd=result_dict.get("total_cost", 0.0),
        total_tokens=result_dict.get("total_tokens", 0),
    )

    orchestrator = PostExecutionOrchestrator(config)
    report = orchestrator.run(context)

    if verbose or True:  # Always show autonomous loop summary
        _print_autonomous_summary(report)


def _format_subsystem_result(
    label: str, result: Any, errors: list, formatter: Any,
) -> Optional[tuple]:
    """Format a single subsystem row for the autonomous summary table.

    Returns (label, description) or None if nothing to show.
    """
    if result:
        desc = formatter(result)
        return (label, desc) if desc else None
    if result is None and any(label in e for e in errors):
        return (label, "[yellow]error[/yellow]")
    return None


def _print_autonomous_summary(report: Any) -> None:
    """Print summary of autonomous loop results."""
    from rich.table import Table as RichTable

    table = RichTable(title="Autonomous Loop")
    table.add_column("Subsystem", style="cyan")
    table.add_column("Result")

    subsystems = [
        ("Learning", report.learning_result, lambda lr: (
            f"patterns={lr.get('patterns_found', 0)}, "
            f"new={lr.get('patterns_new', 0)}, "
            f"recs={lr.get('recommendations', 0)}"
        )),
        ("Goals", report.goals_result, lambda gr: (
            f"proposals={gr.get('proposals_generated', 0)}"
        )),
        ("Portfolio", report.portfolio_result, lambda pr: (
            "[dim]skipped (no product_type)[/dim]" if pr.get("skipped") else
            f"scorecards={pr.get('scorecards', 0)}, "
            f"recs={pr.get('recommendations', 0)}"
        )),
    ]

    for label, result, formatter in subsystems:
        row = _format_subsystem_result(label, result, report.errors, formatter)
        if row:
            table.add_row(*row)

    table.add_row("Duration", f"{report.duration_ms:.1f}ms")

    if report.errors:
        table.add_row("Errors", str(len(report.errors)))

    console.print()
    console.print(table)


def _handle_post_execution(
    result: Any,
    show_details: bool,
    output: Optional[str],
    workflow_id: str,
    workflow_name: str,
    verbose: bool,
    autonomous_opts: Optional[dict] = None,
) -> None:
    """Handle post-execution tasks: summary, reports, gantt chart, autonomous loop, and output saving.

    ``autonomous_opts``, when provided, must contain ``workflow_config``
    (the raw workflow dict) and ``cli_autonomous`` (bool CLI override).
    """
    _print_run_summary(workflow_name, workflow_id, result)

    if show_details:
        _display_detailed_report(result)

    _display_gantt_chart(workflow_id)

    # Run autonomous loop if enabled
    if autonomous_opts is not None:
        _run_autonomous_loop(
            autonomous_opts["workflow_config"],
            workflow_id, workflow_name, result, verbose,
            cli_autonomous=autonomous_opts.get("cli_autonomous", False),
        )

    if output:
        _save_results(output, result, verbose)


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


def _setup_event_routing(
    event_bus: Any, events_to: str, event_format: str,
    run_id: Optional[str], verbose: bool,
) -> None:
    """Set up event output routing on the event bus if non-default options are requested."""
    if not event_bus or (events_to == "stderr" and event_format == "text"):
        return
    try:
        from temper_ai.interfaces.cli.event_output import EventOutputHandler
        handler = EventOutputHandler(mode=events_to, fmt=event_format, run_id=run_id)
        event_bus.subscribe(handler.handle_event)
    except ImportError:
        if verbose:
            console.print("[yellow]Warning:[/yellow] Event output routing not available")


def _compile_workflow(
    workflow_config: Any, tool_registry: Any, config_loader: Any, verbose: bool,
) -> tuple:
    """Compile workflow config into an executable graph.

    Returns (engine, compiled) tuple.
    """
    try:
        from temper_ai.workflow.engine_registry import EngineRegistry
        registry = EngineRegistry()
        engine = registry.get_engine_from_config(
            workflow_config,
            tool_registry=tool_registry,
            config_loader=config_loader,
        )
        compiled = engine.compile(workflow_config)
        return engine, compiled
    except (ValueError, KeyError, AttributeError) as e:
        console.print(f"[red]Workflow compilation error:[/red] {e}")
        if verbose:
            logger.exception("Failed to compile workflow")
        raise SystemExit(1)


def _maybe_adapt_lifecycle(
    workflow_config: dict, inputs: dict, config_root: str, verbose: bool
) -> dict:
    """Apply lifecycle adaptation if enabled in workflow config."""
    wf = workflow_config.get("workflow", {})
    lifecycle_cfg = wf.get("lifecycle", {})
    if not lifecycle_cfg.get("enabled", False):
        return workflow_config

    try:
        from temper_ai.lifecycle.adapter import LifecycleAdapter
        from temper_ai.lifecycle.classifier import ProjectClassifier
        from temper_ai.lifecycle.profiles import ProfileRegistry
        from temper_ai.lifecycle.store import LifecycleStore

        store = LifecycleStore()
        registry = ProfileRegistry(
            config_dir=Path(config_root) / "lifecycle", store=store
        )
        classifier = ProjectClassifier()
        adapter = LifecycleAdapter(
            profile_registry=registry,
            classifier=classifier,
            store=store,
        )
        adapted = adapter.adapt(workflow_config, inputs)
        if verbose:
            console.print("[cyan]Lifecycle adaptation applied[/cyan]")
        return adapted
    except Exception as e:  # noqa: BLE001 -- lifecycle is optional
        logger.warning("Lifecycle adaptation failed: %s", e)
        if verbose:
            console.print(f"[yellow]Lifecycle adaptation skipped:[/yellow] {e}")
        return workflow_config


def _handle_server_mode(  # noqa: params — pass-through from Click
    workflow: str,
    input_file: Optional[str],
    server: Optional[str],
    api_key: Optional[str],
    workspace: Optional[str],
    run_id: Optional[str],
    output: Optional[str],
    show_details: bool,
) -> None:
    """Detect a running Temper AI server and delegate the run, or exit with error."""
    from temper_ai.interfaces.cli.server_client import DEFAULT_SERVER_URL
    from temper_ai.interfaces.cli.server_delegation import (
        delegate_to_server,
        detect_server,
    )

    client = detect_server(server or DEFAULT_SERVER_URL, api_key)
    if client is not None:
        inputs: dict = {}
        if input_file:
            with open(input_file) as f:
                inputs = yaml.safe_load(f) or {}
        delegate_to_server(
            client, workflow, inputs, workspace, run_id, output, show_details,
        )
        return

    console.print("[red]Error:[/red] No Temper AI server running.")
    console.print("Start one with: [bold]temper-ai serve[/bold]")
    console.print(
        "Or use [bold]--local[/bold] to run without a server "
        "(no dashboard streaming)."
    )
    raise SystemExit(1)


def _run_local_workflow(  # noqa: params — pass-through from Click
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
    autonomous: bool,
) -> None:
    """Execute a workflow locally with observability and optional dashboard."""
    from temper_ai.observability.tracker import WorkflowTrackingParams

    _setup_logging(verbose, show_details)
    wf_config, inputs = _load_workflow_config(
        workflow, input_file, config_root, verbose,
    )
    wf_config = _maybe_adapt_lifecycle(wf_config, inputs, config_root, verbose)

    needs_bus = dashboard is not None or events_to != "stderr" or event_format != "text"
    dash_port = dashboard if dashboard is not None else (0 if needs_bus else None)
    config_loader, tool_registry, tracker, event_bus, dash_server = (
        _initialize_infrastructure(config_root, db or DEFAULT_DB_PATH, dash_port, verbose)
    )
    _setup_event_routing(event_bus, events_to, event_format, run_id, verbose)
    engine, compiled = _compile_workflow(wf_config, tool_registry, config_loader, verbose)

    wf_name = wf_config.get("workflow", {}).get("name", Path(workflow).stem)
    with tracker.track_workflow(WorkflowTrackingParams(
        workflow_name=wf_name, workflow_config=wf_config,
        trigger_type="cli", environment="local",
    )) as workflow_id:
        result = _execute_workflow(WorkflowExecutionParams(
            compiled=compiled, workflow_config=wf_config, inputs=inputs,
            tracker=tracker, config_loader=config_loader, tool_registry=tool_registry,
            workflow_id=workflow_id, show_details=show_details, engine=engine,
            verbose=verbose, workspace=workspace, run_id=run_id,
            workflow_name=wf_name,
        ))

    _handle_post_execution(
        result, show_details, output, workflow_id, wf_name, verbose,
        autonomous_opts={"workflow_config": wf_config, "cli_autonomous": autonomous},
    )
    if dashboard is not None:
        _handle_dashboard_keepalive(dash_server, dashboard)
    _cleanup_tool_executor(engine)


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
@click.option(CLI_OPTION_DB, type=click.Path(), help="Database path override")
@click.option(
    CLI_OPTION_CONFIG_ROOT,
    default=DEFAULT_CONFIG_ROOT,
    show_default=True,
    envvar=ENV_VAR_CONFIG_ROOT,
    help=HELP_CONFIG_ROOT,
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
@click.option(
    "--autonomous",
    is_flag=True,
    help="Enable post-execution autonomous loop (pattern mining, goals, portfolio)",
)
@click.option(
    "--local",
    is_flag=True,
    help="Force local execution (skip server detection)",
)
@click.option(
    CLI_OPTION_SERVER,
    default=None,
    envvar=ENV_VAR_SERVER_URL,
    help="Server URL for delegation",
)
@click.option(
    CLI_OPTION_API_KEY,
    default=None,
    envvar=ENV_VAR_API_KEY,
    help="API key for server auth",
)
def run(  # noqa: params — Click command, params are CLI args
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
    autonomous: bool,
    local: bool,
    server: Optional[str],
    api_key: Optional[str],
) -> None:
    """Run a workflow from a YAML config file."""
    if not local:
        _handle_server_mode(
            workflow, input_file, server, api_key,
            workspace, run_id, output, show_details,
        )
        return

    _run_local_workflow(
        workflow, input_file, verbose, output, db, config_root,
        show_details, dashboard, workspace, events_to,
        event_format, run_id, autonomous,
    )



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
    table.add_row(COLUMN_STATUS, f"[{style}]{status}[/{style}]")

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
@click.option("--host", default=DEFAULT_HOST, show_default=True, envvar="MAF_HOST", help="Bind address")
@click.option("--port", default=DEFAULT_DASHBOARD_PORT, show_default=True, help="Dashboard port")
@click.option("--db", default=None, help="Database path")
def dashboard(host: str, port: int, db: Optional[str]) -> None:
    """Launch dashboard to browse past workflow executions."""
    try:
        import uvicorn

        from temper_ai.interfaces.dashboard.app import create_app
    except ImportError as e:
        console.print(
            f"[red]Error:[/red] Dashboard dependencies not installed: {e}\n"
            "Install with: pip install 'temper-ai[dashboard]'"
        )
        raise SystemExit(1)

    from temper_ai.observability.backends import SQLObservabilityBackend
    from temper_ai.observability.event_bus import ObservabilityEventBus
    from temper_ai.observability.tracker import ExecutionTracker

    # Init database
    db_path = db or DEFAULT_DB_PATH
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        ExecutionTracker.ensure_database(f"{SQLITE_URL_PREFIX}{db_path}")
    except (OSError, PermissionError) as e:
        console.print(f"[red]Database error:[/red] {e}")
        raise SystemExit(1)

    backend = SQLObservabilityBackend(buffer=False)
    event_bus = ObservabilityEventBus()
    app = create_app(backend=backend, event_bus=event_bus)

    if host == DEFAULT_SERVER_HOST:  # nosec B104
        console.print("[yellow]Warning:[/yellow] Binding to 0.0.0.0 exposes service on all network interfaces")

    console.print(f"\n[cyan]Temper AI Dashboard[/cyan] running at http://{host}:{port}")
    console.print("Press Ctrl+C to stop\n")

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped[/yellow]")


# ─── serve command ────────────────────────────────────────────────────


@main.command()
@click.option("--host", default=DEFAULT_HOST, show_default=True, envvar="MAF_HOST", help="Bind address")
@click.option("--port", default=DEFAULT_DASHBOARD_PORT, show_default=True, envvar="MAF_PORT", help="Listen port")
@click.option(
    CLI_OPTION_CONFIG_ROOT,
    default=DEFAULT_CONFIG_ROOT,
    show_default=True,
    envvar=ENV_VAR_CONFIG_ROOT,
    help=HELP_CONFIG_ROOT,
)
@click.option("--db", default=None, envvar="MAF_DB_PATH", help="Database path")
@click.option("--workers", default=DEFAULT_MAX_WORKERS, show_default=True, envvar="MAF_MAX_WORKERS", help="Max concurrent workflows")
@click.option("--reload", "dev_reload", is_flag=True, help="Auto-reload on code changes (dev mode)")
def serve(host: str, port: int, config_root: str, db: Optional[str], workers: int, dev_reload: bool) -> None:
    """Start Temper AI HTTP API server for programmatic workflow execution."""
    try:
        import uvicorn

        from temper_ai.interfaces.dashboard.app import create_app
    except ImportError as e:
        console.print(
            f"[red]Error:[/red] Server dependencies not installed: {e}\n"
            "Install with: pip install 'temper-ai[dashboard]'"
        )
        raise SystemExit(1)

    from temper_ai.observability.backends import SQLObservabilityBackend
    from temper_ai.observability.event_bus import ObservabilityEventBus
    from temper_ai.observability.tracker import ExecutionTracker

    # Init database
    db_path = db or DEFAULT_DB_PATH
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        ExecutionTracker.ensure_database(f"{SQLITE_URL_PREFIX}{db_path}")
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

    if host == DEFAULT_SERVER_HOST:  # nosec B104
        console.print("[yellow]Warning:[/yellow] Binding to 0.0.0.0 exposes service on all network interfaces")

    console.print(f"\n[cyan]Temper AI Server[/cyan] listening on http://{host}:{port}")
    console.print("Press Ctrl+C to stop\n")

    try:
        uvicorn.run(app, host=host, port=port, log_level="info", reload=dev_reload)
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped[/yellow]")


# ─── validate command ─────────────────────────────────────────────────


def _extract_agent_name(agent_entry: Any) -> str:
    """Extract agent name from a string or dict entry."""
    if isinstance(agent_entry, str):
        return agent_entry
    if isinstance(agent_entry, dict):
        name: str = agent_entry.get("name", "")
        return name
    return ""


def _resolve_stage_path(stage_ref: str, workflow_dir: Path, config_root: str) -> Optional[Path]:
    """Resolve a stage_ref to an existing file path, or return None."""
    for base in [Path(stage_ref), workflow_dir / stage_ref, Path(config_root) / stage_ref]:
        if base.exists():
            return base
    return None


def _check_stage_references(
    stages: list, workflow_dir: Path, config_root: str,
    check_refs: bool, errors: list[str],
) -> None:
    """Check stage file existence and optionally validate agent references."""
    for stage in stages:
        stage_ref = stage.get("stage_ref", "")
        if not stage_ref:
            continue

        stage_path = _resolve_stage_path(stage_ref, workflow_dir, config_root)
        if stage_path is None:
            errors.append(f"Stage file not found: {stage_ref}")
            continue

        if not check_refs:
            continue

        with open(stage_path) as f:
            stage_config = yaml.safe_load(f)
        if not stage_config:
            continue

        for agent_entry in stage_config.get("stage", {}).get("agents", []):
            agent_name = _extract_agent_name(agent_entry)
            if not agent_name:
                continue
            agent_path = Path(config_root) / "agents" / f"{agent_name}{YAML_FILE_EXTENSION}"
            if not agent_path.exists():
                errors.append(f"Agent config not found: {agent_path}")


def _compute_transitive_predecessors(
    predecessors: dict[str, list[str]],
) -> dict[str, set[str]]:
    """Compute transitive predecessors for each stage via BFS.

    Args:
        predecessors: Direct predecessors from DAG.

    Returns:
        Dict mapping stage name to set of all transitive predecessors.
    """
    from collections import deque

    result: dict[str, set[str]] = {name: set() for name in predecessors}
    for stage in predecessors:
        visited: set[str] = set()
        queue: deque[str] = deque(predecessors[stage])
        while queue:
            pred = queue.popleft()
            if pred in visited:
                continue
            visited.add(pred)
            queue.extend(predecessors.get(pred, []))
        result[stage] = visited
    return result


def _load_stage_inputs(
    stage_ref: str, workflow_dir: Path, config_root: str,
) -> Optional[dict]:
    """Load and parse stage input declarations. Returns None on failure."""
    from temper_ai.workflow.context_schemas import parse_stage_inputs

    stage_path = _resolve_stage_path(stage_ref, workflow_dir, config_root)
    if stage_path is None:
        return None

    try:
        with open(stage_path) as f:
            stage_config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return None

    if not stage_config:
        return None

    raw_inputs = stage_config.get("stage", {}).get("inputs")
    return parse_stage_inputs(raw_inputs)


def _validate_stage_sources(
    stage: dict,
    stage_names: list[str],
    trans_preds: dict,
    config_root: str,
    workflow_dir: Path,
    errors: list[str],
) -> None:
    """Validate source references for a single stage."""
    stage_name = stage.get("name", "")
    stage_ref = stage.get("stage_ref", "")
    if not stage_name or not stage_ref:
        return

    parsed = _load_stage_inputs(stage_ref, workflow_dir, config_root)
    if parsed is None:
        return

    stage_name_set = set(stage_names)
    preds = trans_preds.get(stage_name, set())
    for input_name, decl in parsed.items():
        source_prefix = decl.source.split(".")[0]

        if source_prefix == "workflow":
            continue  # workflow.* always valid

        if source_prefix not in stage_name_set:
            errors.append(
                f"Stage '{stage_name}' input '{input_name}': "
                f"source stage '{source_prefix}' not found in workflow"
            )
            continue

        if source_prefix not in preds:
            errors.append(
                f"Stage '{stage_name}' input '{input_name}': "
                f"source '{decl.source}' references stage '{source_prefix}' "
                f"which is not a predecessor"
            )


def _validate_source_references(
    stages: list,
    config_root: str,
    workflow_dir: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validate source references in stage input declarations.

    Checks that:
    1. Source stage exists in the workflow
    2. Source stage is a DAG predecessor (transitive) — no forward refs
    3. workflow.* sources are always valid
    """
    from temper_ai.workflow.dag_builder import build_stage_dag

    stage_names = [s.get("name", "") for s in stages if s.get("name")]
    if not stage_names:
        return

    try:
        dag = build_stage_dag(stage_names, stages)
        trans_preds = _compute_transitive_predecessors(dag.predecessors)
    except (ValueError, KeyError):
        return

    for stage in stages:
        _validate_stage_sources(
            stage, stage_names, trans_preds,
            config_root, workflow_dir, errors,
        )


@main.command()
@click.argument("workflow", type=click.Path(exists=True))
@click.option(
    CLI_OPTION_CONFIG_ROOT,
    default=DEFAULT_CONFIG_ROOT,
    show_default=True,
    envvar=ENV_VAR_CONFIG_ROOT,
    help=HELP_CONFIG_ROOT,
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

    try:
        workflow_config = _load_and_validate_workflow(workflow, verbose=(output_format == "text"))
    except SystemExit:
        if output_format == "json":
            console.print(json.dumps({"valid": False, "errors": ["Schema validation failed"], "warnings": []}))
        raise

    wf = workflow_config.get("workflow", {})
    _check_stage_references(
        wf.get("stages", []), Path(workflow).parent, config_root, check_refs, errors,
    )

    # Validate source references in stage input declarations
    _validate_source_references(
        wf.get("stages", []), config_root, Path(workflow).parent, errors, warnings,
    )

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
        if warnings:
            console.print("[yellow]Warnings:[/yellow]")
            for w in warnings:
                console.print(f"  - {w}")

    if not is_valid:
        raise SystemExit(1)


# ─── config group ─────────────────────────────────────────────────────


@main.group("config")
def config_group() -> None:
    """Configuration management commands."""
    pass


def _check_agent_tools(
    agent_name: str, agent_path: Path, config_root: str, warnings: list[str]
) -> None:
    """Check tool references inside an agent config file."""
    try:
        with open(agent_path) as f:
            agent_config = yaml.safe_load(f)
        agent_tools = agent_config.get("agent", {}).get("tools", None)
        if agent_tools is None:
            return
        for tool_entry in agent_tools:
            tool_name = tool_entry if isinstance(tool_entry, str) else tool_entry.get("name", "")
            if not tool_name:
                continue
            tool_path = Path(config_root) / "tools" / f"{tool_name}{YAML_FILE_EXTENSION}"
            if not tool_path.exists():
                warnings.append(f"{agent_name}: tool config not found — {tool_name}")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"{agent_name}: could not check tools — {exc}")


def _check_agents_in_stage(
    stage_ref: str, stage_path: Path, config_root: str,
    errors: list[str], warnings: list[str], verbose: bool,
) -> None:
    """Check agent and tool references inside a stage config."""
    try:
        with open(stage_path) as f:
            stage_config = yaml.safe_load(f)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{stage_ref}: YAML parse error — {exc}")
        return

    if not stage_config:
        return

    for agent_entry in stage_config.get("stage", {}).get("agents", []):
        agent_name = _extract_agent_name(agent_entry)
        if not agent_name:
            continue
        agent_path = Path(config_root) / "agents" / f"{agent_name}{YAML_FILE_EXTENSION}"
        if not agent_path.exists():
            errors.append(f"{stage_ref}: agent not found — {agent_name}")
            continue
        if verbose:
            _check_agent_tools(agent_name, agent_path, config_root, warnings)


def _check_workflow_file(
    wf_path: Path, config_root: str,
    errors: list[str], warnings: list[str], verbose: bool,
) -> None:
    """Validate a single workflow file: schema, stage refs, agent refs."""
    try:
        with open(wf_path) as f:
            wf_config = yaml.safe_load(f)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{wf_path.name}: YAML parse error — {exc}")
        return

    if not wf_config:
        warnings.append(f"{wf_path.name}: empty file")
        return

    wf = wf_config.get("workflow", {})
    if not wf:
        errors.append(f"{wf_path.name}: missing 'workflow' key")
        return

    try:
        from temper_ai.workflow._schemas import WorkflowConfig as WfSchema
        WfSchema(**wf_config)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{wf_path.name}: schema error — {exc}")

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
        _check_agents_in_stage(stage_ref, stage_path, config_root, errors, warnings, verbose)


def _print_config_issues(errors: list[str], warnings: list[str]) -> None:
    """Print errors and warnings from config check."""
    if errors:
        console.print(f"\n[red]Errors ({len(errors)}):[/red]")
        for err in errors:
            console.print(f"  \u2717 {err}")
    if warnings:
        console.print(f"\n[yellow]Warnings ({len(warnings)}):[/yellow]")
        for warn in warnings:
            console.print(f"  \u26a0 {warn}")


def _report_config_results(
    errors: list[str], warnings: list[str], fail_on_warning: bool
) -> None:
    """Print config check results and exit on errors."""
    _print_config_issues(errors, warnings)

    if not errors and not warnings:
        console.print("[green]All configs valid[/green]")
    elif not errors:
        console.print(f"\n[green]No errors[/green] ({len(warnings)} warning(s))")

    if errors or (fail_on_warning and warnings):
        raise SystemExit(1)


@config_group.command("check")
@click.option(
    CLI_OPTION_CONFIG_ROOT,
    default=DEFAULT_CONFIG_ROOT,
    show_default=True,
    envvar=ENV_VAR_CONFIG_ROOT,
    help=HELP_CONFIG_ROOT,
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

    for wf_path in sorted(workflows_dir.glob(YAML_GLOB_PATTERN)):
        _check_workflow_file(wf_path, config_root, errors, warnings, verbose)

    _report_config_results(errors, warnings, fail_on_warning)


# ─── list group ───────────────────────────────────────────────────────


@main.group("list")
def list_group() -> None:
    """List available resources."""
    pass


@list_group.command("workflows")
@click.option(CLI_OPTION_CONFIG_ROOT, default=DEFAULT_CONFIG_ROOT, show_default=True, envvar=ENV_VAR_CONFIG_ROOT)
def list_workflows(config_root: str) -> None:
    """List available workflow configs."""
    workflows_dir = Path(config_root) / "workflows"
    if not workflows_dir.exists():
        console.print(f"{ERROR_DIR_NOT_FOUND}{workflows_dir}")
        raise SystemExit(1)

    table = Table(title="Available Workflows")
    table.add_column(COLUMN_NAME, style="cyan")
    table.add_column(COLUMN_DESCRIPTION)
    table.add_column("Stages", style="yellow")

    for path in sorted(workflows_dir.glob(YAML_GLOB_PATTERN)):
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
@click.option(CLI_OPTION_CONFIG_ROOT, default=DEFAULT_CONFIG_ROOT, show_default=True, envvar=ENV_VAR_CONFIG_ROOT)
def list_agents(config_root: str) -> None:
    """List available agent configs."""
    agents_dir = Path(config_root) / "agents"
    if not agents_dir.exists():
        console.print(f"{ERROR_DIR_NOT_FOUND}{agents_dir}")
        raise SystemExit(1)

    table = Table(title="Available Agents")
    table.add_column(COLUMN_NAME, style="cyan")
    table.add_column(COLUMN_DESCRIPTION)
    table.add_column("Type", style="yellow")

    for path in sorted(agents_dir.glob(YAML_GLOB_PATTERN)):
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
@click.option(CLI_OPTION_CONFIG_ROOT, default=DEFAULT_CONFIG_ROOT, show_default=True, envvar=ENV_VAR_CONFIG_ROOT)
def list_stages(config_root: str) -> None:
    """List available stage configs."""
    stages_dir = Path(config_root) / "stages"
    if not stages_dir.exists():
        console.print(f"{ERROR_DIR_NOT_FOUND}{stages_dir}")
        raise SystemExit(1)

    table = Table(title="Available Stages")
    table.add_column(COLUMN_NAME, style="cyan")
    table.add_column(COLUMN_DESCRIPTION)
    table.add_column("Agents", style="yellow")

    for path in sorted(stages_dir.glob(YAML_GLOB_PATTERN)):
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


# ─── trigger command ──────────────────────────────────────────────────


@main.command()
@click.argument("workflow")
@click.option("--input", "input_file", type=click.Path(exists=True), help="YAML file with input values")
@click.option(CLI_OPTION_SERVER, default=None, envvar=ENV_VAR_SERVER_URL, help="Server URL (default: http://127.0.0.1:8420)")
@click.option(CLI_OPTION_API_KEY, default=None, envvar=ENV_VAR_API_KEY, help="API key for authentication")
@click.option("--workspace", default=None, help="Restrict file operations to this directory")
@click.option("--wait", is_flag=True, help="Wait for workflow to complete")
def trigger(
    workflow: str,
    input_file: Optional[str],
    server: Optional[str],
    api_key: Optional[str],
    workspace: Optional[str],
    wait: bool,
) -> None:
    """Trigger a workflow on a running Temper AI server."""
    from temper_ai.interfaces.cli.server_client import DEFAULT_SERVER_URL, MAFServerClient

    client = MAFServerClient(
        base_url=server or DEFAULT_SERVER_URL,
        api_key=api_key,
    )

    inputs: dict = {}
    if input_file:
        with open(input_file) as f:
            inputs = yaml.safe_load(f) or {}

    try:
        result = client.trigger_run(workflow, inputs=inputs, workspace=workspace)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    execution_id = result.get("execution_id", "")
    console.print(f"[green]Triggered:[/green] {execution_id}")

    if wait:
        _poll_until_complete(client, execution_id)


def _poll_until_complete(client: Any, execution_id: str) -> None:
    """Poll server until the run reaches a terminal status."""
    import time

    console.print("Waiting for completion...")
    poll_interval = 2  # scanner: skip-magic
    while True:
        time.sleep(poll_interval)  # Intentional polling: wait for workflow completion
        try:
            status_data = client.get_status(execution_id)
        except Exception as exc:
            console.print(f"[yellow]Poll error:[/yellow] {exc}")
            continue
        current = status_data.get("status", "")
        if current in ("completed", "failed", "cancelled"):
            style = "green" if current == "completed" else "red"
            console.print(f"[{style}]{current}[/{style}]")
            if current == "failed":
                err = status_data.get("error_message", "")
                if err:
                    console.print(f"  Error: {err}")
                raise SystemExit(1)
            return


# ─── status command ──────────────────────────────────────────────────


@main.command("status")
@click.argument("run_id", required=False)
@click.option(CLI_OPTION_SERVER, default=None, envvar=ENV_VAR_SERVER_URL, help="Server URL")
@click.option(CLI_OPTION_API_KEY, default=None, envvar=ENV_VAR_API_KEY, help="API key")
@click.option("--all", "show_all", is_flag=True, help="Show all runs (no limit)")
def status(
    run_id: Optional[str],
    server: Optional[str],
    api_key: Optional[str],
    show_all: bool,
) -> None:
    """Show run status. Without RUN_ID, lists recent runs."""
    from temper_ai.interfaces.cli.server_client import DEFAULT_SERVER_URL, MAFServerClient

    client = MAFServerClient(
        base_url=server or DEFAULT_SERVER_URL,
        api_key=api_key,
    )

    try:
        if run_id:
            _display_single_run(client, run_id)
        else:
            _display_run_list(client, show_all)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)


def _display_single_run(client: Any, run_id: str) -> None:
    """Display detailed status for a single run."""
    data = client.get_status(run_id)
    table = Table(title=f"Run: {run_id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    current = data.get("status", "unknown")
    style = "green" if current == "completed" else ("red" if current == "failed" else "yellow")
    table.add_row(COLUMN_STATUS, f"[{style}]{current}[/{style}]")
    table.add_row("Workflow", data.get("workflow_name", ""))
    table.add_row("Path", data.get("workflow_path", ""))
    table.add_row("Workflow ID", data.get("workflow_id", "") or "")
    table.add_row("Started", data.get("started_at", "") or "")
    table.add_row("Completed", data.get("completed_at", "") or "")
    if data.get("error_message"):
        table.add_row("Error", data["error_message"])

    console.print(table)


def _display_run_list(client: Any, show_all: bool) -> None:
    """Display a table of recent runs."""
    limit = 1000 if show_all else 20  # scanner: skip-magic
    data = client.list_runs(limit=limit)
    runs = data.get("runs", [])

    if not runs:
        console.print("[yellow]No runs found[/yellow]")
        return

    table = Table(title="Recent Runs")
    table.add_column("ID", style="cyan")
    table.add_column("Workflow")
    table.add_column(COLUMN_STATUS)
    table.add_column("Started")

    for run in runs:
        current = run.get("status", "unknown")
        style = "green" if current == "completed" else ("red" if current == "failed" else "yellow")
        table.add_row(
            run.get("execution_id", ""),
            run.get("workflow_name", ""),
            f"[{style}]{current}[/{style}]",
            run.get("started_at", "") or "",
        )

    console.print(table)


# ─── logs command ────────────────────────────────────────────────────


@main.command()
@click.argument("run_id")
@click.option(CLI_OPTION_SERVER, default=None, envvar=ENV_VAR_SERVER_URL, help="Server URL")
@click.option(CLI_OPTION_API_KEY, default=None, envvar=ENV_VAR_API_KEY, help="API key")
@click.option("--follow", "-f", is_flag=True, help="Stream events via WebSocket")
def logs(
    run_id: str,
    server: Optional[str],
    api_key: Optional[str],
    follow: bool,
) -> None:
    """Show events/logs for a run."""
    from temper_ai.interfaces.cli.server_client import DEFAULT_SERVER_URL, MAFServerClient

    client = MAFServerClient(
        base_url=server or DEFAULT_SERVER_URL,
        api_key=api_key,
    )

    if follow:
        _stream_logs_ws(client, run_id)
    else:
        _display_logs_http(client, run_id)


def _display_logs_http(client: Any, run_id: str) -> None:
    """Fetch and display run events via HTTP."""
    try:
        # Get run status first to find workflow_id
        status_data = client.get_status(run_id)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    workflow_id = status_data.get("workflow_id")
    if not workflow_id:
        console.print("[yellow]No events available (workflow not started yet)[/yellow]")
        return

    # Fetch events
    try:
        with client._client() as http:
            resp = http.get(f"/api/runs/{run_id}/events", params={"limit": 100})  # scanner: skip-magic
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        console.print(f"[red]Error fetching events:[/red] {exc}")
        raise SystemExit(1)

    events = data.get("events", [])
    if not events:
        console.print("[yellow]No events recorded[/yellow]")
        return

    for evt in events:
        ts = evt.get("timestamp", "")
        etype = evt.get("event_type", "")
        console.print(f"[dim]{ts}[/dim] [{_event_color(etype)}]{etype}[/{_event_color(etype)}]")


def _stream_logs_ws(client: Any, run_id: str) -> None:
    """Stream logs via WebSocket."""
    try:
        import websockets.sync.client as ws_client
    except ImportError:
        console.print("[red]Error:[/red] websockets not installed. Use --follow without -f or install websockets.")
        raise SystemExit(1)

    # Get workflow_id
    try:
        status_data = client.get_status(run_id)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)

    workflow_id = status_data.get("workflow_id")
    if not workflow_id:
        console.print("[yellow]No workflow_id available yet[/yellow]")
        raise SystemExit(1)

    ws_url = client.base_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/ws/{workflow_id}"

    console.print(f"[cyan]Streaming events for {workflow_id}...[/cyan]")
    try:
        with ws_client.connect(ws_url) as ws:
            for message in ws:
                console.print(message)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stream stopped[/yellow]")


def _event_color(event_type: str) -> str:
    """Return Rich color for event type."""
    colors = {
        "workflow_start": "green",
        "workflow_end": "green",
        "stage_start": "cyan",
        "stage_end": "cyan",
        "agent_start": "blue",
        "agent_end": "blue",
        "llm_call": "magenta",
        "tool_call": "yellow",
    }
    return colors.get(event_type, "white")


# ─── Mount existing rollback group ────────────────────────────────────

from temper_ai.interfaces.cli.rollback import rollback  # noqa: E402

main.add_command(rollback)

from temper_ai.interfaces.cli.memory_commands import memory_group  # noqa: E402

main.add_command(memory_group)

from temper_ai.interfaces.cli.learning_commands import learning_group  # noqa: E402

main.add_command(learning_group)

from temper_ai.interfaces.cli.autonomy_commands import autonomy_group  # noqa: E402

main.add_command(autonomy_group)

from temper_ai.interfaces.cli.template_commands import template_group  # noqa: E402

main.add_command(template_group)

from temper_ai.interfaces.cli.lifecycle_commands import lifecycle_group  # noqa: E402

main.add_command(lifecycle_group)

from temper_ai.interfaces.cli.goal_commands import goals_group  # noqa: E402

main.add_command(goals_group)

from temper_ai.interfaces.cli.portfolio_commands import portfolio_group  # noqa: E402

main.add_command(portfolio_group)

from temper_ai.interfaces.cli.experiment_commands import experiment_group  # noqa: E402

main.add_command(experiment_group)


if __name__ == "__main__":
    main()
