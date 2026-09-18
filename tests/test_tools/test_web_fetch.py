"""WebFetch — fetch a URL and return readable text.

Runs against a throwaway in-process HTTP server, never the internet: the
pre-commit hook runs pytest, so a test that depends on a third-party site can
block every commit in the repo (that already happened once here with httpbin).
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from temper_ai.tools.web_fetch import DEFAULT_MAX_CHARS, WebFetch, extract_readable

PAGE = """<!doctype html>
<html><head>
  <title>Widget Docs</title>
  <style>body { color: red }</style>
  <script>var tracking = "do not read me";</script>
</head><body>
  <nav><a href="/">Home</a><a href="/pricing">Pricing</a></nav>
  <header>Site banner</header>
  <main>
    <h1>Widgets</h1>
    <p>A widget accepts a <code>size</code> parameter.</p>
    <ul><li>small</li><li>large</li></ul>
  </main>
  <footer>Copyright 2026 &mdash; all rights reserved</footer>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/page":
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif self.path == "/api":
            self._send(200, b'{"b": 2, "a": [1, 2]}', "application/json")
        elif self.path == "/plain":
            self._send(200, b"just text", "text/plain")
        elif self.path == "/binary":
            self._send(200, bytes(range(256)) * 8, "application/octet-stream")
        elif self.path == "/big":
            body = ("<p>" + "word " * 20 + "</p>") * 2000
            self._send(200, f"<html><body>{body}</body></html>".encode(), "text/html")
        elif self.path == "/missing":
            self._send(404, b"nope", "text/plain")
        else:
            self._send(404, b"nope", "text/plain")


@pytest.fixture(scope="module")
def server() -> Any:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    yield f"http://{host}:{port}"
    httpd.shutdown()
    httpd.server_close()


def fetch(**config: Any) -> WebFetch:
    """Loopback is refused by default, so tests opt in the way an operator would."""
    return WebFetch(config={"allow_private_hosts": True, **config})


class TestReadableExtraction:
    def test_strips_boilerplate_and_keeps_prose(self, server):
        r = fetch().execute(url=f"{server}/page")
        assert r.success is True
        assert "A widget accepts a size parameter." in r.result
        assert "small" in r.result and "large" in r.result
        for boilerplate in ("do not read me", "color: red", "Pricing", "Site banner", "Copyright 2026"):
            assert boilerplate not in r.result, f"{boilerplate!r} should have been stripped"

    def test_title_becomes_a_heading(self, server):
        assert fetch().execute(url=f"{server}/page").result.startswith("# Widget Docs")

    def test_entities_are_decoded(self):
        _, text = extract_readable("<p>a &amp; b &mdash; c</p>")
        assert text == "a & b — c"

    def test_malformed_html_does_not_fail_the_fetch(self):
        _, text = extract_readable("<p>one<div><span>two</p></body")
        assert "one" in text and "two" in text

    def test_much_smaller_than_the_raw_markup(self, server):
        r = fetch().execute(url=f"{server}/page")
        assert len(r.result) < len(PAGE) / 2, "readable text should be a fraction of the markup"


class TestContentTypes:
    def test_json_is_formatted(self, server):
        r = fetch().execute(url=f"{server}/api")
        assert r.success is True
        assert r.metadata["kind"] == "json"
        assert '"b": 2' in r.result and "\n" in r.result

    def test_plain_text_passes_through(self, server):
        r = fetch().execute(url=f"{server}/plain")
        assert r.success is True and r.result == "just text"

    def test_binary_is_refused_with_a_pointer_to_the_http_tool(self, server):
        r = fetch().execute(url=f"{server}/binary")
        assert r.success is False
        assert "not readable as text" in r.error
        assert "http tool" in r.error


class TestBounding:
    def test_truncates_and_says_how_to_get_more(self, server):
        r = fetch().execute(url=f"{server}/big")
        assert r.success is True
        assert r.metadata["truncated"] is True
        assert len(r.result) < DEFAULT_MAX_CHARS + 200
        assert "Raise max_chars to read more." in r.result

    def test_max_chars_is_honoured(self, server):
        r = fetch().execute(url=f"{server}/big", max_chars=800)
        assert len(r.result) < 1000
        assert "[Truncated at 800 characters." in r.result


class TestSafety:
    def test_loopback_is_refused_by_default(self, server):
        """The model cannot turn this off — allow_private_hosts is tool config."""
        r = WebFetch().execute(url=f"{server}/page")
        assert r.success is False
        assert "loopback" in r.error
        assert "http tool" in r.error

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("http://169.254.169.254/latest/meta-data/", "link-local"),
            ("http://10.0.0.5/admin", "private network"),
            ("http://127.0.0.1:9/x", "loopback"),
            ("http://localhost:9/x", "loopback"),
        ],
    )
    def test_internal_addresses_are_refused(self, url, expected):
        r = WebFetch().execute(url=url)
        assert r.success is False
        assert expected in r.error

    def test_non_http_schemes_refused(self):
        assert "must be http(s)" in WebFetch().execute(url="file:///etc/passwd").error
        assert "must be http(s)" in WebFetch().execute(url="ftp://example.com/x").error

    def test_url_required(self):
        assert "url is required" in WebFetch().execute().error

    def test_http_error_status_is_a_failure(self, server):
        r = fetch().execute(url=f"{server}/missing")
        assert r.success is False
        assert "404" in r.error

    def test_not_a_workspace_path_tool(self):
        """A URL is not a file here, so the workspace sandbox must not judge it."""
        assert WebFetch.local_paths is False
        assert WebFetch.modifies_state is False
