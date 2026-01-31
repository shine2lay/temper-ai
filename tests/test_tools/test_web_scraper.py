"""
Unit tests for WebScraper tool.

Tests web scraping with mocked HTTP responses.
"""
import pytest
import httpx
import socket
from unittest.mock import Mock, patch, MagicMock
from src.tools.web_scraper import WebScraper, RateLimiter
import time


class TestRateLimiter:
    """Test rate limiter."""

    def test_allows_requests_under_limit(self):
        """Test that requests under limit are allowed."""
        limiter = RateLimiter(max_requests=5, time_window=60)

        for _ in range(5):
            assert limiter.can_proceed() is True
            limiter.record_request()

    def test_blocks_requests_over_limit(self):
        """Test that requests over limit are blocked."""
        limiter = RateLimiter(max_requests=3, time_window=60)

        # Use up the limit
        for _ in range(3):
            limiter.record_request()

        # Next request should be blocked
        assert limiter.can_proceed() is False

    def test_allows_requests_after_window(self):
        """Test that requests are allowed after time window expires."""
        limiter = RateLimiter(max_requests=2, time_window=1)  # 1 second window

        # Use up limit
        limiter.record_request()
        limiter.record_request()
        assert limiter.can_proceed() is False

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again
        assert limiter.can_proceed() is True

    def test_wait_time(self):
        """Test wait time calculation."""
        limiter = RateLimiter(max_requests=1, time_window=60)

        limiter.record_request()
        assert limiter.can_proceed() is False

        wait_time = limiter.wait_time()
        assert 0 < wait_time <= 60


class TestWebScraperMetadata:
    """Test web scraper metadata."""

    def test_metadata(self):
        """Test web scraper metadata is correct."""
        scraper = WebScraper()
        assert scraper.name == "WebScraper"
        assert "fetches content" in scraper.description.lower()
        assert scraper.version == "1.0"

    def test_parameters_schema(self):
        """Test parameters schema."""
        scraper = WebScraper()
        schema = scraper.get_parameters_schema()

        assert schema["type"] == "object"
        assert "url" in schema["properties"]
        assert schema["required"] == ["url"]


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx.Client for testing."""
    with patch('src.tools.web_scraper.httpx.Client') as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        yield mock_client


class TestBasicFetching:
    """Test basic URL fetching."""

    def test_fetch_simple_url(self, mock_httpx_client):
        """Test fetching a simple URL."""
        scraper = WebScraper()

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body><p>Hello, world!</p></body></html>"
        mock_response.content = mock_response.text.encode()
        mock_response.headers = {"content-type": "text/html"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="https://example.com")

        assert result.success is True
        assert "Hello, world!" in result.result
        assert result.metadata["status_code"] == 200

    def test_fetch_with_custom_timeout(self, mock_httpx_client):
        """Test fetching with custom timeout."""
        scraper = WebScraper()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Test content"
        mock_response.content = b"Test content"
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(
            url="https://example.com",
            timeout=60
        )

        assert result.success is True

    def test_fetch_with_custom_user_agent(self, mock_httpx_client):
        """Test fetching with custom user agent."""
        scraper = WebScraper()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Test"
        mock_response.content = b"Test"
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(
            url="https://example.com",
            user_agent="CustomBot/1.0"
        )

        assert result.success is True

        # Verify user agent was passed
        call_args = mock_httpx_client.get.call_args
        headers = call_args[1]["headers"]
        assert headers["User-Agent"] == "CustomBot/1.0"


class TestTextExtraction:
    """Test HTML text extraction."""

    def test_extract_text_from_html(self, mock_httpx_client):
        """Test extracting text from HTML."""
        scraper = WebScraper()

        html = """
        <html>
        <head><title>Test Page</title></head>
        <body>
            <h1>Main Title</h1>
            <p>First paragraph.</p>
            <p>Second paragraph.</p>
        </body>
        </html>
        """

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.content = html.encode()
        mock_response.headers = {"content-type": "text/html"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(
            url="https://example.com",
            extract_text=True
        )

        assert result.success is True
        assert "Main Title" in result.result
        assert "First paragraph" in result.result
        assert "Second paragraph" in result.result
        assert "<html>" not in result.result  # HTML tags removed

    def test_remove_script_tags(self, mock_httpx_client):
        """Test that script tags are removed."""
        scraper = WebScraper()

        html = """
        <html>
        <body>
            <p>Visible text</p>
            <script>console.log('hidden');</script>
            <style>.hidden { display: none; }</style>
        </body>
        </html>
        """

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.content = html.encode()
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="https://example.com")

        assert result.success is True
        assert "Visible text" in result.result
        assert "console.log" not in result.result
        assert "display: none" not in result.result

    def test_return_raw_html_when_extract_false(self, mock_httpx_client):
        """Test returning raw HTML when extract_text=False."""
        scraper = WebScraper()

        html = "<html><body><p>Test</p></body></html>"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.content = html.encode()
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(
            url="https://example.com",
            extract_text=False
        )

        assert result.success is True
        assert result.result == html
        assert "<html>" in result.result


class TestErrorHandling:
    """Test error handling."""

    def test_invalid_url(self):
        """Test that invalid URLs are rejected."""
        scraper = WebScraper()

        result = scraper.execute(url="not-a-url")

        assert result.success is False
        assert "http://" in result.error.lower() or "https://" in result.error.lower()

    def test_missing_url(self):
        """Test that missing URL is rejected."""
        scraper = WebScraper()

        result = scraper.execute()

        assert result.success is False
        assert "url" in result.error.lower()

    def test_empty_url(self):
        """Test that empty URL is rejected."""
        scraper = WebScraper()

        result = scraper.execute(url="")

        assert result.success is False

    def test_non_string_url(self):
        """Test that non-string URL is rejected."""
        scraper = WebScraper()

        result = scraper.execute(url=123)

        assert result.success is False

    def test_http_error(self, mock_httpx_client):
        """Test handling of HTTP errors."""
        scraper = WebScraper()

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.reason_phrase = "Not Found"
        mock_httpx_client.get.return_value = mock_response
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=Mock(),
            response=mock_response
        )

        result = scraper.execute(url="https://example.com/nonexistent")

        assert result.success is False
        assert "404" in result.error

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_timeout_error(self, mock_getaddrinfo, mock_httpx_client):
        """Test handling of timeout errors."""
        scraper = WebScraper()

        # Mock DNS to return public IP (pass SSRF check)
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        mock_httpx_client.get.side_effect = httpx.TimeoutException("Timeout")

        result = scraper.execute(url="https://slow.example.com")

        assert result.success is False
        assert "timed out" in result.error.lower()

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_request_error(self, mock_getaddrinfo, mock_httpx_client):
        """Test handling of request errors."""
        scraper = WebScraper()

        # Mock DNS to return public IP (pass SSRF check)
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        mock_httpx_client.get.side_effect = httpx.RequestError("Connection failed")

        result = scraper.execute(url="https://unreachable.example.com")

        assert result.success is False
        assert "request error" in result.error.lower()


class TestRateLimiting:
    """Test rate limiting."""

    def test_rate_limit_enforcement(self, mock_httpx_client):
        """Test that rate limit is enforced."""
        scraper = WebScraper()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Test"
        mock_response.content = b"Test"
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        # Make max requests
        for i in range(scraper.DEFAULT_RATE_LIMIT):
            result = scraper.execute(url=f"https://example.com/{i}")
            assert result.success is True

        # Next request should be rate limited
        result = scraper.execute(url="https://example.com/over-limit")

        assert result.success is False
        assert "rate limit" in result.error.lower()

    def test_rate_limit_message_includes_wait_time(self):
        """Test that rate limit error includes wait time."""
        scraper = WebScraper()

        # Exhaust rate limit
        for _ in range(scraper.DEFAULT_RATE_LIMIT):
            scraper.rate_limiter.record_request()

        result = scraper.execute(url="https://example.com")

        assert result.success is False
        assert "rate limit" in result.error.lower()
        assert "wait" in result.error.lower()


class TestContentSizeLimit:
    """Test content size limits."""

    def test_reject_oversized_content(self, mock_httpx_client):
        """Test that very large content is rejected."""
        scraper = WebScraper()

        # Create response with content larger than 5MB
        large_content = b"x" * (6 * 1024 * 1024)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = large_content
        mock_response.text = large_content.decode()
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="https://example.com/large")

        assert result.success is False
        assert "exceeds maximum" in result.error.lower()

    def test_allow_normal_size(self, mock_httpx_client):
        """Test that normal sized content is allowed."""
        scraper = WebScraper()

        # 1MB content (well under limit)
        content = "x" * (1024 * 1024)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = content
        mock_response.content = content.encode()
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="https://example.com")

        assert result.success is True


class TestMetadata:
    """Test result metadata."""

    def test_metadata_includes_status_code(self, mock_httpx_client):
        """Test that metadata includes status code."""
        scraper = WebScraper()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Test"
        mock_response.content = b"Test"
        mock_response.headers = {"content-type": "text/html"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="https://example.com")

        assert result.success is True
        assert result.metadata["status_code"] == 200
        assert "content_type" in result.metadata
        assert "size_bytes" in result.metadata
        assert "text_extracted" in result.metadata

    def test_metadata_includes_url(self, mock_httpx_client):
        """Test that metadata includes the URL."""
        scraper = WebScraper()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Test"
        mock_response.content = b"Test"
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="https://example.com/path")

        assert result.success is True
        assert result.metadata["url"] == "https://example.com/path"


class TestLLMSchema:
    """Test LLM function calling schema."""

    def test_to_llm_schema(self):
        """Test conversion to LLM schema."""
        scraper = WebScraper()
        schema = scraper.to_llm_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "WebScraper"
        assert "url" in schema["function"]["parameters"]["properties"]


class TestURLValidation:
    """Test URL validation."""

    def test_allow_http_urls(self, mock_httpx_client):
        """Test that http:// URLs are allowed."""
        scraper = WebScraper()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Test"
        mock_response.content = b"Test"
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="http://example.com")

        assert result.success is True

    def test_allow_https_urls(self, mock_httpx_client):
        """Test that https:// URLs are allowed."""
        scraper = WebScraper()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Test"
        mock_response.content = b"Test"
        mock_response.headers = {}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="https://example.com")

        assert result.success is True

    def test_reject_ftp_urls(self):
        """Test that ftp:// URLs are rejected."""
        scraper = WebScraper()

        result = scraper.execute(url="ftp://example.com")

        assert result.success is False

    def test_reject_file_urls(self):
        """Test that file:// URLs are rejected."""
        scraper = WebScraper()

        result = scraper.execute(url="file:///etc/passwd")

        assert result.success is False


class TestSSRFProtection:
    """Test SSRF (Server-Side Request Forgery) protection."""

    def test_blocks_localhost_hostname(self):
        """Test that localhost hostname is blocked."""
        scraper = WebScraper()

        result = scraper.execute(url="http://localhost:6379")

        assert result.success is False
        assert "forbidden" in result.error.lower()
        assert "ssrf" in result.error.lower()

    def test_blocks_localhost_ip(self):
        """Test that 127.0.0.1 is blocked."""
        scraper = WebScraper()

        result = scraper.execute(url="http://127.0.0.1:8080")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    def test_blocks_localhost_zero_ip(self):
        """Test that 0.0.0.0 is blocked."""
        scraper = WebScraper()

        result = scraper.execute(url="http://0.0.0.0:80")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    def test_blocks_private_ip_10_network(self):
        """Test that 10.0.0.0/8 private network is blocked."""
        scraper = WebScraper()

        dangerous_urls = [
            "http://10.0.0.1/admin",
            "http://10.1.2.3/config",
            "http://10.255.255.254/secrets",
        ]

        for url in dangerous_urls:
            result = scraper.execute(url=url)
            assert result.success is False
            assert "forbidden" in result.error.lower()

    def test_blocks_private_ip_192_network(self):
        """Test that 192.168.0.0/16 private network is blocked."""
        scraper = WebScraper()

        dangerous_urls = [
            "http://192.168.1.1/router",
            "http://192.168.0.1/admin",
            "http://192.168.255.254/config",
        ]

        for url in dangerous_urls:
            result = scraper.execute(url=url)
            assert result.success is False
            assert "forbidden" in result.error.lower()

    def test_blocks_private_ip_172_network(self):
        """Test that 172.16.0.0/12 private network is blocked."""
        scraper = WebScraper()

        dangerous_urls = [
            "http://172.16.0.1/internal",
            "http://172.31.255.254/secrets",
            "http://172.20.10.5/config",
        ]

        for url in dangerous_urls:
            result = scraper.execute(url=url)
            assert result.success is False
            assert "forbidden" in result.error.lower()

    def test_blocks_aws_metadata_ip(self):
        """Test that AWS/Azure metadata endpoint IP is blocked."""
        scraper = WebScraper()

        result = scraper.execute(url="http://169.254.169.254/latest/meta-data")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    def test_blocks_gcp_metadata_hostname(self):
        """Test that GCP metadata endpoint is blocked."""
        scraper = WebScraper()

        result = scraper.execute(url="http://metadata.google.internal/computeMetadata/v1/")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    def test_blocks_ipv6_localhost(self):
        """Test that IPv6 localhost (::1) is blocked."""
        scraper = WebScraper()

        result = scraper.execute(url="http://[::1]:8080")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_blocks_dns_rebinding_to_localhost(self, mock_getaddrinfo):
        """Test DNS rebinding protection - hostname resolves to localhost."""
        scraper = WebScraper()

        # Mock DNS resolution to return localhost IP
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('127.0.0.1', 80)),
        ]

        result = scraper.execute(url="http://evil.example.com")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_blocks_dns_rebinding_to_private_network(self, mock_getaddrinfo):
        """Test DNS rebinding protection - hostname resolves to private IP."""
        scraper = WebScraper()

        # Mock DNS resolution to return private IP
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('192.168.1.1', 80)),
        ]

        result = scraper.execute(url="http://attacker.example.com")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_allows_public_ip(self, mock_getaddrinfo):
        """Test that public IPs are allowed."""
        scraper = WebScraper()

        # Mock DNS resolution to return public IP
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        # Mock the httpx client to avoid actual network call
        with patch('src.tools.web_scraper.httpx.Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "Public content"
            mock_response.content = b"Public content"
            mock_response.headers = {"content-type": "text/html"}
            mock_client.get.return_value = mock_response

            result = scraper.execute(url="http://example.com")

            # Should not be blocked by SSRF protection
            assert result.success is True

    def test_dns_resolution_error_handling(self):
        """Test handling of DNS resolution errors."""
        scraper = WebScraper()

        # Use a hostname that definitely won't resolve
        result = scraper.execute(url="http://this-domain-absolutely-does-not-exist-12345.invalid")

        assert result.success is False
        assert "resolve" in result.error.lower() or "forbidden" in result.error.lower()

    def test_url_parsing_error_handling(self):
        """Test handling of malformed URLs."""
        scraper = WebScraper()

        malformed_urls = [
            "http://",
            "http:///path",
            "http://[invalid-ipv6",
        ]

        for url in malformed_urls:
            result = scraper.execute(url=url)
            assert result.success is False

    def test_case_insensitive_hostname_blocking(self):
        """Test that hostname blocking is case-insensitive."""
        scraper = WebScraper()

        result = scraper.execute(url="http://LOCALHOST:8080")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    def test_ssrf_error_messages_safe(self):
        """Test that error messages don't expose internal information."""
        scraper = WebScraper()

        result = scraper.execute(url="http://127.0.0.1:6379")

        assert result.success is False
        # Error should mention SSRF protection, not leak internal details
        assert "ssrf" in result.error.lower() or "forbidden" in result.error.lower()
        # Should not contain sensitive internal details
        assert "redis" not in result.error.lower()
        assert "database" not in result.error.lower()

    def test_blocks_ipv4_mapped_ipv6_private(self):
        """Test that IPv4-mapped IPv6 private addresses are blocked."""
        scraper = WebScraper()

        result = scraper.execute(url="http://[::ffff:192.168.1.1]:8080")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    def test_blocks_ipv4_mapped_ipv6_localhost(self):
        """Test that IPv4-mapped IPv6 localhost is blocked."""
        scraper = WebScraper()

        result = scraper.execute(url="http://[::ffff:127.0.0.1]:8080")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_blocks_if_any_resolved_ip_is_private(self, mock_getaddrinfo):
        """Test blocking when any resolved IP is in private range (round-robin DNS)."""
        scraper = WebScraper()

        # Simulate hostname resolving to both public and private IPs
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('192.168.1.1', 80)),
        ]

        result = scraper.execute(url="http://mixed.example.com")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    def test_blocks_direct_ip_private(self):
        """Test that direct private IP addresses (not hostnames) are blocked."""
        scraper = WebScraper()

        result = scraper.execute(url="http://10.20.30.40:8080")

        assert result.success is False
        assert "forbidden" in result.error.lower()

    def test_blocks_link_local_range(self):
        """Test that link-local range 169.254.x.x is blocked."""
        scraper = WebScraper()

        dangerous_urls = [
            "http://169.254.1.1:80",
            "http://169.254.100.200:8080",
            "http://169.254.255.255:443",
        ]

        for url in dangerous_urls:
            result = scraper.execute(url=url)
            assert result.success is False
            assert "forbidden" in result.error.lower()

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_allows_hostname_with_multiple_public_ips(self, mock_getaddrinfo):
        """Test allowing hostname that resolves to multiple public IPs."""
        scraper = WebScraper()

        # Simulate hostname resolving to multiple public IPs (e.g., CDN)
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('1.1.1.1', 80)),
            (socket.AF_INET6, socket.SOCK_STREAM, 0, '', ('2606:4700:4700::1111', 80)),
        ]

        # Mock the httpx client to avoid actual network call
        with patch('src.tools.web_scraper.httpx.Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "Public content"
            mock_response.content = b"Public content"
            mock_response.headers = {"content-type": "text/html"}
            mock_client.get.return_value = mock_response

            result = scraper.execute(url="http://cdn.example.com")

            # Should not be blocked
            assert result.success is True


class TestContentTypeValidation:
    """Test Content-Type validation."""

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_rejects_pdf_content(self, mock_getaddrinfo, mock_httpx_client):
        """Test that PDF content is rejected."""
        scraper = WebScraper()

        # Mock DNS to return public IP
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"PDF binary content"
        mock_response.headers = {"content-type": "application/pdf"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="http://example.com/document.pdf")

        assert result.success is False
        assert "unsupported content type" in result.error.lower()
        assert "application/pdf" in result.error.lower()

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_rejects_image_content(self, mock_getaddrinfo, mock_httpx_client):
        """Test that image content is rejected."""
        scraper = WebScraper()

        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"Image binary content"
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="http://example.com/photo.jpg")

        assert result.success is False
        assert "unsupported content type" in result.error.lower()

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_rejects_video_content(self, mock_getaddrinfo, mock_httpx_client):
        """Test that video content is rejected."""
        scraper = WebScraper()

        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"Video binary content"
        mock_response.headers = {"content-type": "video/mp4"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="http://example.com/video.mp4")

        assert result.success is False
        assert "unsupported content type" in result.error.lower()

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_accepts_html_content(self, mock_getaddrinfo, mock_httpx_client):
        """Test that HTML content is accepted."""
        scraper = WebScraper()

        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.content = b"<html><body>Test</body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="http://example.com")

        assert result.success is True

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_accepts_html_with_charset(self, mock_getaddrinfo, mock_httpx_client):
        """Test that HTML with charset parameter is accepted."""
        scraper = WebScraper()

        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.content = b"<html><body>Test</body></html>"
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="http://example.com")

        assert result.success is True

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_accepts_plain_text(self, mock_getaddrinfo, mock_httpx_client):
        """Test that plain text content is accepted."""
        scraper = WebScraper()

        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "Plain text content"
        mock_response.content = b"Plain text content"
        mock_response.headers = {"content-type": "text/plain"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="http://example.com/file.txt")

        assert result.success is True

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_accepts_xml_content(self, mock_getaddrinfo, mock_httpx_client):
        """Test that XML content is accepted."""
        scraper = WebScraper()

        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<?xml version='1.0'?><root>Test</root>"
        mock_response.content = b"<?xml version='1.0'?><root>Test</root>"
        mock_response.headers = {"content-type": "text/xml"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="http://example.com/data.xml")

        assert result.success is True

    @patch('src.tools.web_scraper.socket.getaddrinfo')
    def test_rejects_binary_application(self, mock_getaddrinfo, mock_httpx_client):
        """Test that binary application content is rejected."""
        scraper = WebScraper()

        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, '', ('8.8.8.8', 80)),
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"Binary application content"
        mock_response.headers = {"content-type": "application/octet-stream"}
        mock_httpx_client.get.return_value = mock_response

        result = scraper.execute(url="http://example.com/file.bin")

        assert result.success is False
        assert "unsupported content type" in result.error.lower()
