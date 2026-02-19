#!/usr/bin/env python3
"""
Query and display workflow execution traces from the observability database.

This script allows you to query workflow executions and see the full trace
including all stages, agents, LLM calls, and tool executions.

Usage:
    python examples/query_trace.py                    # Show latest execution
    python examples/query_trace.py <workflow_id>      # Show specific execution
    python examples/query_trace.py --list 10          # List last 10 executions
    python examples/query_trace.py --json <id>        # Export as JSON
"""
import argparse
import json
import sys
from typing import List, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from temper_ai.observability.database import get_session, init_database
from temper_ai.observability.models import (
    AgentExecution,
    LLMCall,
    StageExecution,
    ToolExecution,
    WorkflowExecution,
)

console = Console()


def init_db(db_path: Optional[str] = None):
    """Initialize database connection."""
    if db_path:
        init_database(f"sqlite:///{db_path}")
    else:
        # Default path
        init_database("sqlite:///workflow_execution.db")


def list_executions(limit: int = 10) -> List[WorkflowExecution]:
    """List recent workflow executions."""
    with get_session() as session:
        executions = (
            session.query(WorkflowExecution)
            .order_by(WorkflowExecution.start_time.desc())
            .limit(limit)
            .all()
        )
        return executions


def get_execution(workflow_id: Optional[str] = None) -> Optional[WorkflowExecution]:
    """
    Get workflow execution by ID or latest.

    Args:
        workflow_id: Workflow ID or None for latest

    Returns:
        WorkflowExecution or None
    """
    with get_session() as session:
        if workflow_id:
            return session.query(WorkflowExecution).filter_by(id=workflow_id).first()
        else:
            # Get latest
            return (
                session.query(WorkflowExecution)
                .order_by(WorkflowExecution.start_time.desc())
                .first()
            )


def display_execution_list(executions: List[WorkflowExecution]):
    """Display table of workflow executions."""
    if not executions:
        console.print("[yellow]No executions found[/yellow]")
        return

    table = Table(
        title="Recent Workflow Executions",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan"
    )

    table.add_column("ID", style="dim")
    table.add_column("Workflow", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Duration", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Started", style="dim")

    for exec in executions:
        status_color = {
            "completed": "green",
            "failed": "red",
            "running": "yellow"
        }.get(exec.status, "white")

        table.add_row(
            exec.id[:8] + "...",
            exec.workflow_name,
            f"[{status_color}]{exec.status.upper()}[/{status_color}]",
            f"{exec.duration_seconds:.2f}s" if exec.duration_seconds else "-",
            str(exec.total_tokens),
            f"${exec.total_cost_usd:.6f}",
            exec.start_time.strftime("%Y-%m-%d %H:%M:%S") if exec.start_time else "-"
        )

    console.print()
    console.print(table)
    console.print()


def display_execution_tree(workflow_exec: WorkflowExecution):
    """Display full execution trace as tree."""
    # Create root node
    duration_str = f"{workflow_exec.duration_seconds:.2f}s" if workflow_exec.duration_seconds else "?"
    status_color = {
        "completed": "green",
        "failed": "red",
        "running": "yellow"
    }.get(workflow_exec.status, "white")

    tree = Tree(
        f"[bold cyan]Workflow: {workflow_exec.workflow_name}[/bold cyan] "
        f"[{status_color}]{workflow_exec.status.upper()}[/{status_color}] "
        f"({duration_str})"
    )

    # Query all related records
    with get_session() as session:
        # Get stages
        stages = (
            session.query(StageExecution)
            .filter_by(workflow_execution_id=workflow_exec.id)
            .order_by(StageExecution.start_time)
            .all()
        )

        for stage in stages:
            stage_duration = f"{stage.duration_seconds:.2f}s" if stage.duration_seconds else "?"
            stage_status_color = {
                "completed": "green",
                "failed": "red",
                "running": "yellow"
            }.get(stage.status, "white")

            stage_node = tree.add(
                f"[cyan]Stage: {stage.stage_name}[/cyan] "
                f"[{stage_status_color}]{stage.status.upper()}[/{stage_status_color}] "
                f"({stage_duration})"
            )

            # Get agents for this stage
            agents = (
                session.query(AgentExecution)
                .filter_by(stage_execution_id=stage.id)
                .order_by(AgentExecution.start_time)
                .all()
            )

            for agent in agents:
                agent_duration = f"{agent.duration_seconds:.2f}s" if agent.duration_seconds else "?"
                agent_status_color = {
                    "completed": "green",
                    "failed": "red",
                    "running": "yellow"
                }.get(agent.status, "white")

                agent_node = stage_node.add(
                    f"[yellow]Agent: {agent.agent_name}[/yellow] "
                    f"[{agent_status_color}]{agent.status.upper()}[/{agent_status_color}] "
                    f"({agent_duration}) "
                    f"[dim]{agent.total_tokens} tokens, ${agent.estimated_cost_usd:.6f}[/dim]"
                )

                # Get LLM calls for this agent
                llm_calls = (
                    session.query(LLMCall)
                    .filter_by(agent_execution_id=agent.id)
                    .order_by(LLMCall.start_time)
                    .all()
                )

                if llm_calls:
                    llm_node = agent_node.add("[magenta]LLM Calls[/magenta]")
                    for call in llm_calls:
                        llm_status_color = "green" if call.status == "success" else "red"
                        llm_node.add(
                            f"[{llm_status_color}]{call.provider}/{call.model}[/{llm_status_color}] "
                            f"{call.total_tokens} tokens ({call.latency_ms}ms) "
                            f"[dim]${call.estimated_cost_usd:.6f}[/dim]"
                        )

                # Get tool executions for this agent
                tool_execs = (
                    session.query(ToolExecution)
                    .filter_by(agent_execution_id=agent.id)
                    .order_by(ToolExecution.start_time)
                    .all()
                )

                if tool_execs:
                    tool_node = agent_node.add("[blue]Tool Executions[/blue]")
                    for tool in tool_execs:
                        tool_status_color = "green" if tool.status == "success" else "red"
                        tool_node.add(
                            f"[{tool_status_color}]{tool.tool_name}[/{tool_status_color}] "
                            f"({tool.duration_seconds:.3f}s)"
                        )

    console.print()
    console.print(tree)
    console.print()


def display_execution_summary(workflow_exec: WorkflowExecution):
    """Display execution summary metrics."""
    table = Table(box=box.ROUNDED, show_header=False, title="Summary Metrics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Workflow ID", workflow_exec.id)
    table.add_row("Workflow Name", workflow_exec.workflow_name)
    table.add_row("Version", workflow_exec.workflow_version or "unknown")
    table.add_row("Status", workflow_exec.status.upper())
    table.add_row("Environment", workflow_exec.environment or "unknown")

    if workflow_exec.duration_seconds:
        table.add_row("Duration", f"{workflow_exec.duration_seconds:.2f}s")

    table.add_row("Total LLM Calls", str(workflow_exec.total_llm_calls))
    table.add_row("Total Tool Calls", str(workflow_exec.total_tool_calls))
    table.add_row("Total Tokens", str(workflow_exec.total_tokens))
    table.add_row("Total Cost", f"${workflow_exec.total_cost_usd:.6f}")

    if workflow_exec.trigger_type:
        table.add_row("Trigger Type", workflow_exec.trigger_type)

    if workflow_exec.optimization_target:
        table.add_row("Optimization", workflow_exec.optimization_target)

    if workflow_exec.start_time:
        table.add_row("Started At", workflow_exec.start_time.strftime("%Y-%m-%d %H:%M:%S UTC"))

    if workflow_exec.end_time:
        table.add_row("Ended At", workflow_exec.end_time.strftime("%Y-%m-%d %H:%M:%S UTC"))

    if workflow_exec.error_message:
        table.add_row("Error", f"[red]{workflow_exec.error_message}[/red]")

    console.print()
    console.print(table)
    console.print()


def export_execution_json(workflow_exec: WorkflowExecution, output_path: str):
    """Export execution trace to JSON."""
    with get_session() as session:
        # Build complete trace
        trace = {
            "workflow": {
                "id": workflow_exec.id,
                "name": workflow_exec.workflow_name,
                "version": workflow_exec.workflow_version,
                "status": workflow_exec.status,
                "duration_seconds": workflow_exec.duration_seconds,
                "total_llm_calls": workflow_exec.total_llm_calls,
                "total_tool_calls": workflow_exec.total_tool_calls,
                "total_tokens": workflow_exec.total_tokens,
                "total_cost_usd": workflow_exec.total_cost_usd,
                "start_time": workflow_exec.start_time.isoformat() if workflow_exec.start_time else None,
                "end_time": workflow_exec.end_time.isoformat() if workflow_exec.end_time else None,
                "error": workflow_exec.error_message,
            },
            "stages": []
        }

        # Get stages
        stages = (
            session.query(StageExecution)
            .filter_by(workflow_execution_id=workflow_exec.id)
            .order_by(StageExecution.start_time)
            .all()
        )

        for stage in stages:
            stage_data = {
                "id": stage.id,
                "name": stage.stage_name,
                "status": stage.status,
                "duration_seconds": stage.duration_seconds,
                "agents": []
            }

            # Get agents
            agents = (
                session.query(AgentExecution)
                .filter_by(stage_execution_id=stage.id)
                .order_by(AgentExecution.start_time)
                .all()
            )

            for agent in agents:
                agent_data = {
                    "id": agent.id,
                    "name": agent.agent_name,
                    "status": agent.status,
                    "duration_seconds": agent.duration_seconds,
                    "total_tokens": agent.total_tokens,
                    "estimated_cost_usd": agent.estimated_cost_usd,
                    "llm_calls": [],
                    "tool_executions": []
                }

                # Get LLM calls
                llm_calls = (
                    session.query(LLMCall)
                    .filter_by(agent_execution_id=agent.id)
                    .order_by(LLMCall.start_time)
                    .all()
                )

                for call in llm_calls:
                    agent_data["llm_calls"].append({
                        "id": call.id,
                        "provider": call.provider,
                        "model": call.model,
                        "total_tokens": call.total_tokens,
                        "latency_ms": call.latency_ms,
                        "status": call.status
                    })

                # Get tool executions
                tool_execs = (
                    session.query(ToolExecution)
                    .filter_by(agent_execution_id=agent.id)
                    .order_by(ToolExecution.start_time)
                    .all()
                )

                for tool in tool_execs:
                    agent_data["tool_executions"].append({
                        "id": tool.id,
                        "tool_name": tool.tool_name,
                        "duration_seconds": tool.duration_seconds,
                        "status": tool.status
                    })

                stage_data["agents"].append(agent_data)

            trace["stages"].append(stage_data)

    # Write to file
    with open(output_path, 'w') as f:
        json.dump(trace, f, indent=2, default=str)

    console.print(f"[green]✓ Exported to {output_path}[/green]")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Query and display workflow execution traces",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python examples/query_trace.py                      # Show latest execution
  python examples/query_trace.py abc123def456         # Show specific execution
  python examples/query_trace.py --list 10            # List last 10 executions
  python examples/query_trace.py --json trace.json    # Export latest as JSON
  python examples/query_trace.py abc123 --json out.json  # Export specific as JSON
        """
    )

    parser.add_argument(
        "workflow_id",
        nargs="?",
        help="Workflow execution ID (default: latest)"
    )
    parser.add_argument(
        "--list",
        "-l",
        type=int,
        metavar="N",
        help="List last N executions"
    )
    parser.add_argument(
        "--json",
        "-j",
        metavar="FILE",
        help="Export trace to JSON file"
    )
    parser.add_argument(
        "--db",
        help="Database path (default: workflow_execution.db)"
    )
    parser.add_argument(
        "--summary",
        "-s",
        action="store_true",
        help="Show summary only (no tree)"
    )

    args = parser.parse_args()

    # Initialize database
    init_db(args.db)

    # List mode
    if args.list:
        executions = list_executions(limit=args.list)
        display_execution_list(executions)
        return 0

    # Get execution
    workflow_exec = get_execution(args.workflow_id)

    if not workflow_exec:
        if args.workflow_id:
            console.print(f"[red]Workflow execution not found: {args.workflow_id}[/red]")
        else:
            console.print("[yellow]No executions found in database[/yellow]")
            console.print("\nRun a workflow first:")
            console.print("  python examples/run_workflow.py simple_research")
        return 1

    # Export JSON mode
    if args.json:
        export_execution_json(workflow_exec, args.json)
        return 0

    # Display header
    console.print()
    console.print(Panel(
        "[bold cyan]Workflow Execution Trace[/bold cyan]",
        border_style="cyan"
    ))

    # Display summary
    display_execution_summary(workflow_exec)

    # Display tree (unless summary-only mode)
    if not args.summary:
        display_execution_tree(workflow_exec)

    return 0


if __name__ == "__main__":
    sys.exit(main())
