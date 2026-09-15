"""MCP server exposing temper to agents.

Two front doors, one implementation:

  * mounted on the running API server at ``/mcp`` (streamable HTTP), so any
    agent that can reach the server can drive it with no install
  * ``temper mcp``, a stdio bridge for clients that only speak stdio

Tool docstrings are the agent-facing documentation — they say when to reach
for a tool and what it costs, because that is all the model sees.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from temper_ai.mcp.tools import DEFAULT_MAX_CHARS, TemperTools

# The SDK rejects requests whose Host header is not in this list, which is
# what stops a malicious web page from driving a local MCP server through
# a victim's browser (DNS rebinding). The default keeps that protection;
# serving the endpoint under a real hostname means naming it here.
DEFAULT_ALLOWED_HOSTS = [
    "localhost",
    "localhost:8420",
    "127.0.0.1",
    "127.0.0.1:8420",
]


def _security_settings() -> TransportSecuritySettings:
    """Allow the hostnames temper is actually served under.

    Set TEMPER_MCP_ALLOWED_HOSTS to a comma-separated list when the server
    sits behind a gateway or is reached over a tailnet, e.g.

        TEMPER_MCP_ALLOWED_HOSTS=temper-dev.wai2shine.com,spark.tailbb5055.ts.net

    Each entry also becomes an allowed http/https Origin.
    """
    configured = [
        host.strip()
        for host in os.environ.get("TEMPER_MCP_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    ]
    hosts = DEFAULT_ALLOWED_HOSTS + configured
    origins = [f"{scheme}://{host}" for host in hosts for scheme in ("http", "https")]
    return TransportSecuritySettings(
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def build_server() -> FastMCP:
    """Create the MCP server with temper's tools registered."""
    mcp = FastMCP(
        name="temper",
        transport_security=_security_settings(),
        # Served under the /mcp mount in server.py, so the app itself
        # answers at its root.
        streamable_http_path="/",
        instructions=(
            "Run and inspect temper multi-agent workflows.\n\n"
            "Start with list_workflows to see what can be run and which "
            "inputs it declares. run_workflow returns immediately with an "
            "execution_id; use wait_for_run to block until it finishes.\n\n"
            "Inspection is deliberately layered so a run's full transcript "
            "never lands in your context by accident: get_run gives status "
            "and one line per node, get_node_output gives what a single "
            "node produced, and get_llm_call gives the prompt and response "
            "of one call. Reach for the deeper tools only when you need to "
            "explain a result or a failure."
        ),
    )
    tools = TemperTools()

    @mcp.tool()
    def list_workflows() -> dict:
        """List runnable workflows and the inputs each declares.

        Call this first: it tells you the exact workflow names run_workflow
        accepts and which inputs are required.
        """
        return tools.list_workflows()

    @mcp.tool()
    def list_runs(
        workflow: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict:
        """List recent runs, newest first.

        Filter by workflow name, or by status (queued, running, completed,
        failed, cancelled).
        """
        return tools.list_runs(workflow=workflow, status=status, limit=limit)

    @mcp.tool()
    def run_workflow(
        workflow: str,
        inputs: dict[str, Any] | None = None,
        workspace_path: str | None = None,
    ) -> dict:
        """Start a workflow run and return its execution_id immediately.

        Runs can take minutes and cost money, so this does not block and
        does not wait for the result. Follow it with wait_for_run.
        """
        return tools.run_workflow(
            workflow=workflow, inputs=inputs, workspace_path=workspace_path
        )

    @mcp.tool()
    def wait_for_run(execution_id: str, timeout_seconds: float = 120.0) -> dict:
        """Wait for a run to finish, then return its summary.

        Returns early with timed_out=true if the run is still going when the
        timeout expires — call again to keep waiting.
        """
        return tools.wait_for_run(execution_id, timeout_seconds=timeout_seconds)

    @mcp.tool()
    def get_run(execution_id: str, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
        """Status of a run and one line per node.

        Cheap, and the right first look at any run. Omits prompts,
        responses and node outputs by design.
        """
        return tools.get_run(execution_id, max_chars=max_chars)

    @mcp.tool()
    def get_node_output(
        execution_id: str,
        node_name: str,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> dict:
        """What one node produced: its output, structured output and input.

        Use after get_run points at an interesting or failed node. Long
        fields are truncated at max_chars.
        """
        return tools.get_node_output(execution_id, node_name, max_chars=max_chars)

    @mcp.tool()
    def get_llm_call(
        execution_id: str,
        call_id: str,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> dict:
        """The prompt, response and thinking behind one LLM call.

        The most expensive tool here: prompts are often thousands of
        tokens. Get call ids from get_node_output.
        """
        return tools.get_llm_call(execution_id, call_id, max_chars=max_chars)

    @mcp.tool()
    def cancel_run(execution_id: str) -> dict:
        """Ask a running workflow to stop."""
        return tools.cancel_run(execution_id)

    @mcp.tool()
    def list_gates(execution_id: str) -> dict:
        """Approval gates this run is waiting on, if any."""
        return tools.list_gates(execution_id)

    @mcp.tool()
    def approve_gate(execution_id: str, node_name: str) -> dict:
        """Approve a waiting gate so the run continues past it."""
        return tools.approve_gate(execution_id, node_name)

    return mcp
