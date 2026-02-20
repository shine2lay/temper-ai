"""
HTTP client tool for making outbound HTTP requests.

Supports GET, POST, PUT, DELETE, PATCH, HEAD methods with SSRF protection.
"""
import logging
import urllib.parse
from typing import Any, Dict, Optional

import httpx

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.http_client_constants import (
    HTTP_ALLOWED_METHODS,
    HTTP_BLOCKED_HOSTS,
    HTTP_DEFAULT_TIMEOUT,
    HTTP_MAX_HEADER_COUNT,
    HTTP_MAX_RESPONSE_SIZE,
)

logger = logging.getLogger(__name__)


def _validate_method(method: str) -> Optional[str]:
    """Return error string if method is not allowed, else None."""
    if method.upper() not in HTTP_ALLOWED_METHODS:
        return f"Method '{method}' not allowed. Allowed: {sorted(HTTP_ALLOWED_METHODS)}"
    return None


def _validate_url(url: str) -> Optional[str]:
    """Return error string if URL is invalid or blocked (SSRF protection), else None."""
    if not url or not isinstance(url, str):
        return "url must be a non-empty string"

    if not url.startswith(("http://", "https://")):
        return "url must start with http:// or https://"

    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
    except (TypeError, ValueError) as exc:
        return f"Invalid URL format: {exc}"

    if not hostname:
        return "Invalid URL: missing hostname"

    if hostname.lower() in {h.lower() for h in HTTP_BLOCKED_HOSTS}:
        return f"Access to '{hostname}' is blocked (SSRF protection)"

    return None


def _validate_headers(headers: Any) -> Optional[str]:
    """Return error string if headers are invalid, else None."""
    if headers is None:
        return None
    if not isinstance(headers, dict):
        return "headers must be a JSON object"
    if len(headers) > HTTP_MAX_HEADER_COUNT:
        return f"Too many headers (max {HTTP_MAX_HEADER_COUNT})"
    return None


class HTTPClientTool(BaseTool):
    """
    HTTP client tool for making outbound HTTP requests.

    Supports common HTTP methods with SSRF protection (blocks localhost,
    internal IPs, and cloud metadata endpoints).
    """

    def get_metadata(self) -> ToolMetadata:
        """Return HTTP client tool metadata."""
        return ToolMetadata(
            name="HTTPClient",
            description=(
                "Makes HTTP requests to external URLs. Supports GET, POST, PUT, DELETE, "
                "PATCH, and HEAD methods. Includes SSRF protection to block internal hosts."
            ),
            version="1.0",
            category="network",
            requires_network=True,
            requires_credentials=False,
            modifies_state=True,
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Return JSON schema for HTTP client parameters."""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Target URL (must start with http:// or https://)"
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method (GET, POST, PUT, DELETE, PATCH, HEAD)",
                    "default": "GET"
                },
                "headers": {
                    "type": "object",
                    "description": "Optional HTTP headers as key-value pairs"
                },
                "body": {
                    "type": "object",
                    "description": "Optional request body (sent as JSON)"
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Request timeout in seconds (default: {HTTP_DEFAULT_TIMEOUT})",
                    "default": HTTP_DEFAULT_TIMEOUT
                },
            },
            "required": ["url"]
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute an HTTP request.

        Args:
            url: Target URL
            method: HTTP method (default: GET)
            headers: Optional dict of HTTP headers
            body: Optional request body dict (sent as JSON)
            timeout: Request timeout in seconds

        Returns:
            ToolResult with status_code, headers, and response body
        """
        url = kwargs.get("url", "")
        method = str(kwargs.get("method", "GET")).upper()
        headers = kwargs.get("headers")
        body = kwargs.get("body")
        timeout = kwargs.get("timeout", HTTP_DEFAULT_TIMEOUT)

        url_error = _validate_url(url)
        if url_error:
            return ToolResult(success=False, error=url_error)

        method_error = _validate_method(method)
        if method_error:
            return ToolResult(success=False, error=method_error)

        headers_error = _validate_headers(headers)
        if headers_error:
            return ToolResult(success=False, error=headers_error)

        request_headers: Dict[str, str] = dict(headers) if isinstance(headers, dict) else {}

        try:
            with httpx.Client(timeout=httpx.Timeout(timeout=float(timeout), connect=10.0)) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    json=body,
                )

            raw_content = response.text
            truncated = len(raw_content) > HTTP_MAX_RESPONSE_SIZE
            body_text = raw_content[:HTTP_MAX_RESPONSE_SIZE]

            return ToolResult(
                success=True,
                result={
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": body_text,
                    "truncated": truncated,
                },
                metadata={"url": url, "method": method},
            )

        except httpx.TimeoutException:
            return ToolResult(success=False, error=f"Request timed out after {timeout} seconds")
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"HTTP error: {exc}")
        except ValueError as exc:
            return ToolResult(success=False, error=f"Invalid request: {exc}")
