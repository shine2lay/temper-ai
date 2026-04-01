"""HTTP tool — make HTTP requests.

Provides a structured interface for GET/POST/PUT/DELETE requests.
Configurable timeout and URL allowlist for safety.
"""

import logging
from typing import Any

import httpx

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_MAX_RESPONSE_SIZE = 128_000


class Http(BaseTool):
    """Make HTTP requests (GET, POST, PUT, DELETE)."""

    name = "http"
    description = "Make HTTP requests to APIs. Returns status code and response body."
    parameters = {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                "description": "HTTP method",
            },
            "url": {
                "type": "string",
                "description": "Full URL to request",
            },
            "headers": {
                "type": "object",
                "description": "Optional request headers",
            },
            "body": {
                "type": "string",
                "description": "Optional request body (for POST/PUT/PATCH)",
            },
        },
        "required": ["method", "url"],
    }
    modifies_state = False

    def __init__(
        self,
        timeout: int = _DEFAULT_TIMEOUT,
        allowed_domains: list[str] | None = None,
    ):
        self.timeout = timeout
        self.allowed_domains = allowed_domains  # None = allow all

    def execute(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute an HTTP request.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            url: Full URL
            headers: Optional headers dict
            body: Optional request body string
        """
        # Domain allowlist check
        if self.allowed_domains:
            from urllib.parse import urlparse
            domain = urlparse(url).hostname
            if domain and not any(domain.endswith(d) for d in self.allowed_domains):
                return ToolResult(
                    success=False, result="",
                    error=f"Domain '{domain}' not in allowed list: {self.allowed_domains}",
                )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    content=body,
                )

            response_text = response.text
            if len(response_text) > _MAX_RESPONSE_SIZE:
                response_text = response_text[:_MAX_RESPONSE_SIZE] + \
                    f"\n... [truncated, {len(response_text)} chars total]"

            result = f"HTTP {response.status_code}\n{response_text}"

            return ToolResult(
                success=200 <= response.status_code < 400,
                result=result,
                error=None if response.status_code < 400 else f"HTTP {response.status_code}",
            )

        except httpx.TimeoutException:
            return ToolResult(
                success=False, result="",
                error=f"Request to {url} timed out after {self.timeout}s",
            )
        except httpx.ConnectError as e:
            return ToolResult(
                success=False, result="",
                error=f"Connection failed: {e}",
            )
        except Exception as e:
            return ToolResult(
                success=False, result="",
                error=f"HTTP request error: {e}",
            )
