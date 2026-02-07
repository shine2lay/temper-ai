"""
Unified CLI for Meta-Autonomous Framework.

Entry point: `maf`

Commands:
    maf run <workflow>          Run a workflow from a YAML config
    maf validate <workflow>     Validate workflow config without running
    maf list workflows          List available workflows
    maf list agents             List available agents
    maf list stages             List available stages
    maf rollback ...            Rollback operations
    maf m5 ...                  M5 self-improvement commands
"""
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import click
import yaml
from rich.console import Console
from rich.table import Table

console = Console()
logger = logging.getLogger(__name__)

# Project root for resolving paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = ".meta-autonomous/observability.db"


# ─── Helpers ──────────────────────────────────────────────────────────


def _load_and_validate_workflow(
    workflow_path: str, verbose: bool = False
) -> dict:
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
    except Exception as e:
        console.print(f"[red]Validation error:[/red] {e}")
        raise SystemExit(1)

    return workflow_config


# ─── Root group ───────────────────────────────────────────────────────


@click.group()
@click.version_option(package_name="meta-autonomous-framework", prog_name="maf")
def main() -> None:
    """Meta-Autonomous Framework CLI."""
    pass


# ─── run command ──────────────────────────────────────────────────────


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
    help="Config directory root",
)
@click.option(
    "--show-details",
    "-d",
    is_flag=True,
    help="Show real-time agent progress and detailed post-execution report",
)
def run(
    workflow: str,
    input_file: Optional[str],
    verbose: bool,
    output: Optional[str],
    db: Optional[str],
    config_root: str,
    show_details: bool,
) -> None:
    """Run a workflow from a YAML config file."""
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

    # 1-2. Load and validate workflow YAML
    workflow_config = _load_and_validate_workflow(workflow, verbose=verbose)

    # 3. Load inputs
    inputs: dict = {}
    if input_file:
        with open(input_file) as f:
            inputs = yaml.safe_load(f) or {}

    # 4. Check required inputs
    wf = workflow_config.get("workflow", {})
    required = wf.get("inputs", {}).get("required", [])
    missing = [r for r in required if r not in inputs]
    if missing:
        console.print(
            f"[red]Missing required inputs:[/red] {', '.join(missing)}"
        )
        console.print("Provide them in an input file: --input inputs.yaml")
        raise SystemExit(1)

    try:
        from src.compiler.config_loader import ConfigLoader
        from src.compiler.engine_registry import EngineRegistry
        from src.observability.tracker import ExecutionTracker
        from src.tools.registry import ToolRegistry

        # 5. Init database
        db_path = db or DEFAULT_DB_PATH
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        ExecutionTracker.ensure_database(f"sqlite:///{db_path}")

        # 6. Create infrastructure
        config_loader = ConfigLoader(config_root=config_root)
        tool_registry = ToolRegistry(auto_discover=True)
        tracker = ExecutionTracker()

        # 7. Compile via EngineRegistry
        registry = EngineRegistry()
        engine = registry.get_engine_from_config(
            workflow_config,
            tool_registry=tool_registry,
            config_loader=config_loader,
        )
        compiled = engine.compile(workflow_config)

        # 8. Execute with tracking
        workflow_name = wf.get("name", Path(workflow).stem)
        with tracker.track_workflow(
            workflow_name=workflow_name,
            workflow_config=workflow_config,
            trigger_type="cli",
            environment="local",
        ) as workflow_id:
            state = {
                **inputs,
                "tracker": tracker,
                "config_loader": config_loader,
                "tool_registry": tool_registry,
                "workflow_id": workflow_id,
                "show_details": show_details,
                "detail_console": console if show_details else None,
            }
            result = compiled.invoke(state)

        # 9. Display Rich summary
        _print_run_summary(workflow_name, workflow_id, result)

        # 9b. Display detailed report if --show-details
        if show_details and isinstance(result, dict):
            from src.cli.detail_report import print_detailed_report
            print_detailed_report(result, console)

        # 10. Display hierarchical gantt chart
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
        except Exception as e:
            logger.debug(f"Could not display gantt chart: {e}")

        # 11. Save results if --output
        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(result, f, indent=2, default=str)
            console.print(f"\nResults saved to [cyan]{output}[/cyan]")

        # 12. Cleanup resources
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
            except Exception as e:
                logger.debug(f"Error during tool executor shutdown: {e}")
        else:
            logger.debug("No tool_executor found to cleanup")

    except SystemExit:
        raise
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        # Cleanup on interrupt
        if 'engine' in locals():
            tool_executor = None
            if hasattr(engine, 'tool_executor'):
                tool_executor = engine.tool_executor
            elif hasattr(engine, 'compiler') and hasattr(engine.compiler, 'tool_executor'):
                tool_executor = engine.compiler.tool_executor
            if tool_executor is not None:
                try:
                    tool_executor.shutdown()
                except Exception:
                    pass
        raise SystemExit(130)
    except Exception as e:
        console.print(f"[red]Execution error:[/red] {e}")
        if verbose:
            logger.exception("Workflow execution failed")
        # Cleanup on error
        if 'engine' in locals():
            tool_executor = None
            if hasattr(engine, 'tool_executor'):
                tool_executor = engine.tool_executor
            elif hasattr(engine, 'compiler') and hasattr(engine.compiler, 'tool_executor'):
                tool_executor = engine.compiler.tool_executor
            if tool_executor is not None:
                try:
                    tool_executor.shutdown()
                except Exception:
                    pass
        raise SystemExit(1)


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


# ─── validate command ─────────────────────────────────────────────────


@main.command()
@click.argument("workflow", type=click.Path(exists=True))
@click.option(
    "--config-root",
    default="configs",
    show_default=True,
    help="Config directory root",
)
def validate(workflow: str, config_root: str) -> None:
    """Validate a workflow config without running it."""
    workflow_config = _load_and_validate_workflow(workflow, verbose=True)

    # Check stage references exist
    wf = workflow_config.get("workflow", {})
    workflow_dir = Path(workflow).parent
    errors = []
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

    if errors:
        console.print("[red]Reference errors:[/red]")
        for err in errors:
            console.print(f"  - {err}")
        raise SystemExit(1)

    console.print("[green]All references valid[/green]")


# ─── list group ───────────────────────────────────────────────────────


@main.group("list")
def list_group() -> None:
    """List available resources."""
    pass


@list_group.command("workflows")
@click.option("--config-root", default="configs", show_default=True)
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
@click.option("--config-root", default="configs", show_default=True)
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
@click.option("--config-root", default="configs", show_default=True)
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


def _get_m5_cli():
    """Lazy-load M5CLI to avoid import-time side effects."""
    # Ensure coord service is importable
    coord_path = str(PROJECT_ROOT / ".claude-coord")
    if coord_path not in sys.path:
        sys.path.insert(0, coord_path)

    try:
        from src.self_improvement.cli import M5CLI

        return M5CLI()
    except ImportError as e:
        console.print(
            f"[red]Error:[/red] M5 self-improvement module not available: {e}"
        )
        raise SystemExit(1)
    except Exception as e:
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
    default=168,
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
