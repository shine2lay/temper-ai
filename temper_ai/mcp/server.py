"""Temper AI MCP server -- exposes workflows as MCP tools."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_ROOT = "configs"
_API_KEY_MIN_LENGTH = 7
_HTTP_401_UNAUTHORIZED = 401
_DEFAULT_MCP_PORT = 8421


class BearerAuthMiddleware:
    """ASGI middleware that enforces Bearer token authentication."""

    def __init__(self, app: Any, api_key: str) -> None:
        self._app = app
        self._api_key = api_key

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode("latin-1")
            if (
                not auth.startswith("Bearer ")
                or auth[_API_KEY_MIN_LENGTH:].strip() != self._api_key
            ):
                await self._send_unauthorized(send)
                return
        await self._app(scope, receive, send)

    @staticmethod
    async def _send_unauthorized(send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": _HTTP_401_UNAUTHORIZED,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"Unauthorized",
            }
        )


def create_mcp_server(
    config_root: str = DEFAULT_CONFIG_ROOT,
    execution_service: Any | None = None,
    api_key: str | None = None,
) -> Any:
    """Create a FastMCP server exposing Temper AI workflows.

    Args:
        config_root: Config directory root path.
        execution_service: Optional WorkflowExecutionService for bounded
            concurrency and run tracking.  Falls back to direct
            WorkflowRunner when None (standalone MCP).
        api_key: If provided and using HTTP transport, enforce Bearer auth
            on all requests via BearerAuthMiddleware.

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

    _register_list_workflows(
        mcp, tool_annotations_cls, config_root, scan_workflow_configs
    )
    _register_list_agents(mcp, tool_annotations_cls, config_root, scan_agent_configs)
    _register_run_workflow(mcp, tool_annotations_cls, config_root, execution_service)
    _register_get_run_status(mcp, tool_annotations_cls, execution_service)

    if api_key:
        # Wrap the ASGI app with bearer auth for HTTP transport
        original_run = mcp.run

        def run_with_auth(**kwargs: Any) -> None:
            """Start MCP server with bearer auth middleware on HTTP transport."""
            transport = kwargs.get("transport", "stdio")
            if transport != "stdio":
                try:
                    asgi_app = mcp.http_app()
                    wrapped_app = BearerAuthMiddleware(asgi_app, api_key)
                    import uvicorn

                    host = kwargs.get("host", "127.0.0.1")
                    port = kwargs.get("port", _DEFAULT_MCP_PORT)
                    uvicorn.run(wrapped_app, host=host, port=port)
                    return
                except AttributeError:
                    pass  # Fallback to original run if http_app() not available
            original_run(**kwargs)

        mcp.run = run_with_auth  # type: ignore[method-assign]

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
    mcp: Any,
    tool_annotations_cls: Any,
    config_root: str,
    execution_service: Any | None,
) -> None:
    """Register the run_workflow tool on the MCP server."""
    if tool_annotations_cls is not None:

        @mcp.tool(annotations=tool_annotations_cls(destructiveHint=True))
        def run_workflow(workflow_path: str, inputs: str = "{}") -> str:
            """Execute a Temper AI workflow with JSON inputs."""
            return _run_workflow_impl(
                workflow_path, inputs, config_root, execution_service
            )

    else:

        @mcp.tool()
        def run_workflow(workflow_path: str, inputs: str = "{}") -> str:
            """Execute a Temper AI workflow with JSON inputs."""
            return _run_workflow_impl(
                workflow_path, inputs, config_root, execution_service
            )


def _register_get_run_status(
    mcp: Any,
    tool_annotations_cls: Any,
    execution_service: Any | None,
) -> None:
    """Register the get_run_status tool on the MCP server."""
    if tool_annotations_cls is not None:

        @mcp.tool(annotations=tool_annotations_cls(readOnlyHint=True))
        def get_run_status(run_id: str) -> str:
            """Check status of a workflow execution."""
            return _get_run_status_impl(run_id, execution_service)

    else:

        @mcp.tool()
        def get_run_status(run_id: str) -> str:
            """Check status of a workflow execution."""
            return _get_run_status_impl(run_id, execution_service)


def _run_workflow_impl(  # noqa: long
    workflow_path: str,
    inputs_json: str,
    config_root: str,
    execution_service: Any | None = None,
) -> str:
    """Run a workflow via execution service or direct WorkflowRunner."""
    # Security: prevent path traversal
    config_root_resolved = Path(config_root).resolve()
    workflow_file = (config_root_resolved / workflow_path).resolve()
    try:
        workflow_file.relative_to(config_root_resolved)
    except ValueError:
        return json.dumps(
            {"error": "Invalid workflow path: path traversal not allowed"}
        )

    try:
        parsed_inputs = json.loads(inputs_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid JSON inputs: {exc}"})

    try:
        if execution_service is not None:
            result_dict = execution_service.execute_workflow_sync(
                workflow_path,
                input_data=parsed_inputs,
            )
            if result_dict.get("status") == "failed":
                return json.dumps(
                    {
                        "error": result_dict.get("error_message", "Workflow failed"),
                    }
                )
            from temper_ai.mcp._server_helpers import format_run_result

            return format_run_result(result_dict.get("result") or {})

        # Fallback: direct WorkflowRunner (standalone MCP without server)
        logger.warning(
            "MCP run_workflow: no execution_service configured, "
            "running without concurrency bounds or run tracking"
        )
        from temper_ai.interfaces.server.workflow_runner import (
            WorkflowRunner,
            WorkflowRunnerConfig,
        )
        from temper_ai.mcp._server_helpers import format_run_result

        runner = WorkflowRunner(
            config=WorkflowRunnerConfig(config_root=config_root),
        )
        result = runner.run(workflow_path, input_data=parsed_inputs)
        if result.status == "failed":
            return json.dumps({"error": result.error_message})
        return format_run_result(result.result or {})
    except FileNotFoundError:
        return json.dumps({"error": f"Workflow not found: {workflow_path}"})
    except (ValueError, RuntimeError, KeyError) as exc:
        return json.dumps({"error": str(exc)})


def _get_run_status_impl(
    run_id: str,
    execution_service: Any | None = None,
) -> str:
    """Get the status of a workflow run."""
    if execution_service is not None:
        result = execution_service.get_status_sync(run_id)
        if result is None:
            return json.dumps({"error": f"Run not found: {run_id}"})
        return json.dumps(result, default=str)

    # Fallback: direct RunStore (standalone MCP)
    try:
        from temper_ai.interfaces.server.run_store import RunStore

        store = RunStore()
        run = store.get_run(run_id)
        if run is None:
            return json.dumps({"error": f"Run not found: {run_id}"})
        return json.dumps(
            run.model_dump() if hasattr(run, "model_dump") else dict(run), default=str
        )
    except (ImportError, RuntimeError, ValueError) as exc:
        return json.dumps({"error": f"Could not get run status: {exc}"})
