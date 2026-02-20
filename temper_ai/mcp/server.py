"""Temper AI MCP server — exposes workflows as MCP tools."""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_ROOT = "configs"


def create_mcp_server(config_root: str = DEFAULT_CONFIG_ROOT) -> Any:
    """Create a FastMCP server exposing Temper AI workflows.

    Requires the mcp package: pip install 'temper-ai[mcp]'
    """
    from mcp.server.fastmcp import FastMCP

    # Use ToolAnnotations only if available (mcp >= 1.26)
    tool_annotations_cls: Any = None
    try:
        from mcp.server.fastmcp.utilities.types import ToolAnnotations

        tool_annotations_cls = ToolAnnotations
    except ImportError:
        pass  # Fallback: skip annotations

    from temper_ai.mcp._server_helpers import (
        scan_agent_configs,
        scan_workflow_configs,
    )

    mcp = FastMCP("Temper AI")

    _register_list_workflows(mcp, tool_annotations_cls, config_root, scan_workflow_configs)
    _register_list_agents(mcp, tool_annotations_cls, config_root, scan_agent_configs)
    _register_run_workflow(mcp, tool_annotations_cls, config_root)
    _register_get_run_status(mcp, tool_annotations_cls)

    return mcp


def _register_list_workflows(
    mcp: Any,
    tool_annotations_cls: Any,
    config_root: str,
    scan_workflow_configs: Any,
) -> None:
    """Register the list_workflows tool on the MCP server."""
    if tool_annotations_cls is not None:
        @mcp.tool(annotations=tool_annotations_cls(readOnlyHint=True))
        def list_workflows() -> str:
            """List available Temper AI workflows."""
            workflows = scan_workflow_configs(config_root)
            return json.dumps(workflows, indent=2)
    else:
        @mcp.tool()
        def list_workflows() -> str:
            """List available Temper AI workflows."""
            workflows = scan_workflow_configs(config_root)
            return json.dumps(workflows, indent=2)


def _register_list_agents(
    mcp: Any,
    tool_annotations_cls: Any,
    config_root: str,
    scan_agent_configs: Any,
) -> None:
    """Register the list_agents tool on the MCP server."""
    if tool_annotations_cls is not None:
        @mcp.tool(annotations=tool_annotations_cls(readOnlyHint=True))
        def list_agents() -> str:
            """List available Temper AI agents."""
            agents = scan_agent_configs(config_root)
            return json.dumps(agents, indent=2)
    else:
        @mcp.tool()
        def list_agents() -> str:
            """List available Temper AI agents."""
            agents = scan_agent_configs(config_root)
            return json.dumps(agents, indent=2)


def _register_run_workflow(
    mcp: Any, tool_annotations_cls: Any, config_root: str
) -> None:
    """Register the run_workflow tool on the MCP server."""
    if tool_annotations_cls is not None:
        @mcp.tool(annotations=tool_annotations_cls(destructiveHint=True))
        def run_workflow(workflow_path: str, inputs: str = "{}") -> str:
            """Execute a Temper AI workflow with JSON inputs."""
            return _run_workflow_impl(workflow_path, inputs, config_root)
    else:
        @mcp.tool()
        def run_workflow(workflow_path: str, inputs: str = "{}") -> str:
            """Execute a Temper AI workflow with JSON inputs."""
            return _run_workflow_impl(workflow_path, inputs, config_root)


def _register_get_run_status(mcp: Any, tool_annotations_cls: Any) -> None:
    """Register the get_run_status tool on the MCP server."""
    if tool_annotations_cls is not None:
        @mcp.tool(annotations=tool_annotations_cls(readOnlyHint=True))
        def get_run_status(run_id: str) -> str:
            """Check status of a workflow execution."""
            return _get_run_status_impl(run_id)
    else:
        @mcp.tool()
        def get_run_status(run_id: str) -> str:
            """Check status of a workflow execution."""
            return _get_run_status_impl(run_id)


def _run_workflow_impl(workflow_path: str, inputs_json: str, config_root: str) -> str:
    """Run a workflow and return the result as JSON string."""
    from temper_ai.mcp._server_helpers import format_run_result

    try:
        parsed_inputs = json.loads(inputs_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid JSON inputs: {exc}"})

    try:
        import yaml

        from temper_ai.observability.tracker import ExecutionTracker
        from temper_ai.tools.registry import ToolRegistry
        from temper_ai.workflow.config_loader import ConfigLoader
        from temper_ai.workflow.engine_registry import EngineRegistry

        with open(workflow_path) as f:
            workflow_config = yaml.safe_load(f)

        config_loader = ConfigLoader(config_root=config_root)
        tool_registry = ToolRegistry(auto_discover=True)
        tracker = ExecutionTracker()

        registry = EngineRegistry()
        engine = registry.get_engine_from_config(
            workflow_config,
            tool_registry=tool_registry,
            config_loader=config_loader,
        )
        compiled = engine.compile(workflow_config)

        state = {
            "workflow_inputs": parsed_inputs,
            "tracker": tracker,
            "config_loader": config_loader,
            "tool_registry": tool_registry,
            "workflow_id": "mcp-run",
            "show_details": False,
        }
        result = compiled.invoke(state)
        return format_run_result(result)
    except FileNotFoundError:
        return json.dumps({"error": f"Workflow not found: {workflow_path}"})
    except (ValueError, RuntimeError, KeyError) as exc:
        return json.dumps({"error": str(exc)})


def _get_run_status_impl(run_id: str) -> str:
    """Get the status of a workflow run from the run store."""
    try:
        from temper_ai.interfaces.server.run_store import RunStore

        store = RunStore()
        run = store.get_run(run_id)
        if run is None:
            return json.dumps({"error": f"Run not found: {run_id}"})
        return json.dumps(run.model_dump() if hasattr(run, "model_dump") else dict(run), default=str)
    except (ImportError, RuntimeError, ValueError) as exc:
        return json.dumps({"error": f"Could not get run status: {exc}"})
