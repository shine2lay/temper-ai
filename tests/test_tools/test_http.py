"""Tests for HTTP tool."""


from temper_ai.tools.http import Http


class TestHttpBasics:
    def test_get_request(self):
        """Test a real HTTP GET to a known endpoint."""
        http = Http(timeout=10)
        result = http.execute(method="GET", url="https://httpbin.org/get")
        assert result.success
        assert "HTTP 200" in result.result

    def test_post_request(self):
        http = Http(timeout=10)
        result = http.execute(
            method="POST",
            url="https://httpbin.org/post",
            body='{"test": true}',
            headers={"Content-Type": "application/json"},
        )
        assert result.success
        assert "HTTP 200" in result.result

    def test_404_returns_error(self):
        http = Http(timeout=10)
        result = http.execute(method="GET", url="https://httpbin.org/status/404")
        assert not result.success
        assert "HTTP 404" in result.error


class TestHttpSafety:
    def test_domain_allowlist_blocks(self):
        http = Http(allowed_domains=["example.com"])
        result = http.execute(method="GET", url="https://evil.com/steal")
        assert not result.success
        assert "not in allowed" in result.error

    def test_domain_allowlist_allows(self):
        http = Http(allowed_domains=["httpbin.org"], timeout=10)
        result = http.execute(method="GET", url="https://httpbin.org/get")
        assert result.success

    def test_timeout(self):
        http = Http(timeout=1)
        result = http.execute(method="GET", url="https://httpbin.org/delay/5")
        assert not result.success
        assert "timed out" in result.error

    def test_connection_error(self):
        http = Http(timeout=2)
        result = http.execute(method="GET", url="http://localhost:1")
        assert not result.success
        assert "Connection failed" in result.error or "error" in result.error.lower()
