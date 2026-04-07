"""WebSearch tool — search the web via SearXNG."""

import logging
import os
from typing import Any
from urllib.parse import quote_plus

import httpx

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_SEARXNG_URL = os.getenv("SEARXNG_URL", "http://172.17.0.1:8888")


class WebSearch(BaseTool):
    """Search the web using SearXNG. Returns top results with titles, URLs, and snippets."""

    name = "WebSearch"
    description = "Search the web. Returns titles, URLs, and snippets for the query."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query",
            },
            "max_results": {
                "type": "number",
                "description": "Max results to return (default 5)",
            },
        },
        "required": ["query"],
    }
    modifies_state = False

    def execute(self, **params: Any) -> ToolResult:
        query = params.get("query", "")
        if not query:
            return ToolResult(success=False, result="", error="query is required")

        max_results = int(params.get("max_results", 5))
        url = f"{_SEARXNG_URL}/search?q={quote_plus(query)}&format=json"

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()

            results = data.get("results", [])[:max_results]
            if not results:
                return ToolResult(success=True, result="No results found.")

            lines = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "No title")
                link = r.get("url", "")
                snippet = r.get("content", "")[:200]
                lines.append(f"{i}. **{title}**\n   {link}\n   {snippet}\n")

            return ToolResult(
                success=True,
                result="\n".join(lines),
                metadata={"result_count": len(results)},
            )
        except Exception as e:
            return ToolResult(success=False, result="", error=f"Search failed: {e}")
