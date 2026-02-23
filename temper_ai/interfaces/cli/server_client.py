"""HTTP client for Temper AI Server API.

Provides programmatic access to a running Temper AI server,
used as a Python SDK for triggering runs, checking status, and streaming logs.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SERVER_URL = "http://127.0.0.1:8420"
DEFAULT_LIST_LIMIT = 20

# HTTP client timeouts (seconds)
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
HEALTH_PROBE_TIMEOUT = 2  # Fast fail for auto-detection


class MAFServerClient:
    """HTTP client for Temper AI Server API."""

    def __init__(
        self,
        base_url: str = DEFAULT_SERVER_URL,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        """Build request headers including API key if set."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _client(self) -> httpx.Client:
        """Create a configured httpx client."""
        return httpx.Client(
            base_url=self.base_url,
            headers=self._headers(),
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        )

    def health_check(self) -> dict[str, Any]:
        """Check server health."""
        with self._client() as client:
            resp = client.get("/api/health")
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result

    def is_server_running(self) -> bool:
        """Quick health probe to check if server is accepting requests."""
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=httpx.Timeout(
                    HEALTH_PROBE_TIMEOUT, connect=HEALTH_PROBE_TIMEOUT
                ),
            ) as client:
                resp = client.get("/api/health")
                return resp.status_code == httpx.codes.OK
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            return False

    def trigger_run(
        self,
        workflow: str,
        inputs: dict[str, Any] | None = None,
        workspace: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Trigger a workflow execution on the server.

        Args:
            workflow: Workflow path (relative to config_root).
            inputs: Optional input data dict.
            workspace: Optional workspace root.
            run_id: Optional externally-provided run ID.

        Returns:
            Response dict with execution_id and status.
        """
        body: dict[str, Any] = {"workflow": workflow}
        if inputs:
            body["inputs"] = inputs
        if workspace:
            body["workspace"] = workspace
        if run_id:
            body["run_id"] = run_id

        with self._client() as client:
            resp = client.post("/api/runs", json=body)
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result

    def get_status(self, execution_id: str) -> dict[str, Any]:
        """Get status of a specific run."""
        with self._client() as client:
            resp = client.get(f"/api/runs/{execution_id}")
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result

    def list_runs(
        self,
        status: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> dict[str, Any]:
        """List recent runs."""
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status

        with self._client() as client:
            resp = client.get("/api/runs", params=params)
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result

    def cancel_run(self, execution_id: str) -> dict[str, Any]:
        """Cancel a running workflow."""
        with self._client() as client:
            resp = client.post(f"/api/runs/{execution_id}/cancel")
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result
