"""WebFetch tool — fetch a URL and return readable text.

Five agents (research_business, research_pm, research_marketing, research_designer,
…) declared `WebFetch` in their tools list for months; no such tool existed, so
`load_tools` logged a warning and dropped it. They only worked because they ran on
provider: claude, where Claude Code supplies its own WebFetch.

The gap it fills next to `http`: `http` returns `response.text` — for a docs page
that is mostly markup, and it is capped at 128KB of it. This strips scripts,
styles, nav and footers and returns the prose, which is the part an agent asked
for. Same shape of saving as Read vs `cat`, on a different axis.

Ported from pi's `fetch_content` (readable mode), which is the one pi extension
tool with no session coupling at all. Deliberately narrower than pi's:

* no `mode: "answer"` — that runs an LLM over the page. temper has its own model
  and its own orchestration; a tool that quietly starts a second inference is the
  wrong shape here.
* no PDF/YouTube/GitHub-repo handling — those are real features of pi's version
  that would each need a dependency. HTML and text are the 90% case; the tool
  says plainly when it meets something it cannot read.

Extraction is stdlib-only (`html.parser`). A real DOM library would handle
malformed markup better, but the job is boilerplate removal, and the container is
better off without another dependency.

Tightened for unattended use: private, loopback and link-local addresses are
refused by default, because an agent following a link into
`http://169.254.169.254/` or an internal service is a different event from an
agent reading a docs page. `allow_private_hosts` is tool CONFIG, not a model
parameter — the model cannot turn it off.
"""

import ipaddress
import json
import logging
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 30_000
MAX_MAX_CHARS = 200_000
_DEFAULT_TIMEOUT = 30
_UA = "temper-ai/WebFetch"

#: Dropped whole, contents included — never the prose a caller wanted.
_DISCARD = {"script", "style", "noscript", "template", "svg", "canvas", "iframe",
            "nav", "header", "footer", "aside", "form", "button"}
#: Force a line break so paragraphs and list items do not run together.
_BREAK = {"p", "br", "div", "section", "article", "li", "tr", "h1", "h2", "h3",
          "h4", "h5", "h6", "blockquote", "pre"}


class _Readable(HTMLParser):
    """Collect visible text, dropping boilerplate elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._suppress = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DISCARD:
            self._suppress += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BREAK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DISCARD:
            self._suppress = max(0, self._suppress - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in _BREAK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()
            return
        if self._suppress:
            return
        if data.strip():
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [" ".join(line.split()) for line in raw.split("\n")]
        out: list[str] = []
        for line in lines:
            if line:
                out.append(line)
            elif out and out[-1]:
                out.append("")  # collapse runs of blank lines to one
        return "\n".join(out).strip()


def extract_readable(html: str) -> tuple[str, str]:
    """(title, text) from an HTML document."""
    parser = _Readable()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — malformed markup must not fail the fetch
        logger.debug("HTML parse ended early; returning what was collected", exc_info=True)
    return parser.title, parser.text()


class WebFetch(BaseTool):
    """Fetch a URL and return its readable text."""

    name = "WebFetch"
    description = (
        "Fetch a web page and return its readable text — scripts, styles, nav and "
        "footers removed. Use this to read documentation, articles and API pages. "
        "JSON responses are returned formatted. Output is capped "
        f"(default {DEFAULT_MAX_CHARS // 1000}k characters) and says so when truncated. "
        "Use the http tool instead when you need the raw body, headers or a non-GET method."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute http(s) URL to fetch."},
            "max_chars": {
                "type": "integer",
                "description": f"Maximum characters to return (default {DEFAULT_MAX_CHARS}, max {MAX_MAX_CHARS}).",
            },
        },
        "required": ["url"],
    }
    modifies_state = False
    # The URL names a page on the internet, not a file in the workspace.
    local_paths = False

    def execute(self, **params: Any) -> ToolResult:
        url = (params.get("url") or "").strip()
        if not url:
            return ToolResult(success=False, result="", error="url is required")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult(success=False, result="", error=f"url must be http(s), got {parsed.scheme or 'no scheme'!r}")
        if not parsed.hostname:
            return ToolResult(success=False, result="", error=f"url has no host: {url}")

        if not self.config.get("allow_private_hosts"):
            blocked = _private_host_reason(parsed.hostname)
            if blocked:
                return ToolResult(
                    success=False, result="",
                    error=(
                        f"Refusing to fetch {parsed.hostname}: {blocked}. WebFetch reaches public "
                        "web pages; use the http tool for internal services."
                    ),
                )

        max_chars = min(max(int(params.get("max_chars") or DEFAULT_MAX_CHARS), 500), MAX_MAX_CHARS)
        timeout = int(self.config.get("timeout") or _DEFAULT_TIMEOUT)

        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(url, headers={"user-agent": _UA, "accept": "text/html,*/*"})
        except httpx.TimeoutException:
            return ToolResult(success=False, result="", error=f"Request to {url} timed out after {timeout}s")
        except httpx.HTTPError as e:
            return ToolResult(success=False, result="", error=f"Fetch failed: {type(e).__name__}: {e}")

        if response.status_code >= 400:
            return ToolResult(
                success=False,
                result=f"HTTP {response.status_code}",
                error=f"HTTP {response.status_code} from {response.url}",
            )

        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        body, kind = _render(response, content_type)
        if body is None:
            return ToolResult(
                success=False, result="",
                error=(
                    f"{content_type or 'unknown content type'} is not readable as text "
                    f"({len(response.content)} bytes at {response.url}). Use the http tool if you need the raw body."
                ),
            )

        truncated = len(body) > max_chars
        if truncated:
            body = body[:max_chars] + f"\n\n[Truncated at {max_chars} characters. Raise max_chars to read more.]"

        return ToolResult(
            success=True,
            result=body,
            metadata={
                "url": str(response.url),
                "status": response.status_code,
                "content_type": content_type,
                "kind": kind,
                "truncated": truncated,
            },
        )


def _render(response: httpx.Response, content_type: str) -> tuple[str | None, str]:
    """(text, kind) for a response; (None, …) when it is not text at all."""
    if content_type in ("application/json", "application/ld+json") or content_type.endswith("+json"):
        try:
            return json.dumps(response.json(), indent=2, ensure_ascii=False), "json"
        except ValueError:
            return response.text, "text"
    if content_type in ("text/html", "application/xhtml+xml"):
        title, text = extract_readable(response.text)
        return (f"# {title}\n\n{text}" if title else text), "html"
    if content_type.startswith("text/") or content_type in ("application/xml", "application/javascript"):
        return response.text, "text"
    if not content_type and response.text:
        return response.text, "text"
    return None, "binary"


def _private_host_reason(hostname: str) -> str | None:
    """Why this host is off-limits, or None when it is a normal public host."""
    if hostname.lower() in ("localhost", "localhost.localdomain"):
        return "loopback address"
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return None  # unresolvable: let the fetch fail with a real network error
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_loopback:
            return "loopback address"
        if ip.is_link_local:
            return "link-local address (cloud metadata lives here)"
        if ip.is_private:
            return "private network address"
        if ip.is_reserved or ip.is_multicast:
            return "reserved address"
    return None
