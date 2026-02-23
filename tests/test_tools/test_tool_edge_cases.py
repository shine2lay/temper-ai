"""Tests for tool execution edge cases.

Comprehensive edge case testing for tools including:
- Parameter validation edge cases
- Security boundary testing
- Resource limit testing
- Error handling validation
"""

import os
import shutil
import tempfile
from unittest.mock import MagicMock, Mock, patch

from temper_ai.tools.base import ToolResult
from temper_ai.tools.calculator import Calculator
from temper_ai.tools.file_writer import FileWriter
from temper_ai.tools.web_scraper import WebScraper, validate_url_safety


class TestCalculatorEdgeCases:
    """Test Calculator tool edge cases and security boundaries."""

    def test_division_by_zero(self):
        """Test division by zero is handled gracefully."""
        calc = Calculator()
        result = calc.execute(expression="10 / 0")

        assert result.success is False
        assert "division by zero" in result.error.lower()

    def test_empty_expression(self):
        """Test empty expression is rejected."""
        calc = Calculator()
        result = calc.execute(expression="")

        assert result.success is False
        assert "non-empty string" in result.error.lower()

    def test_non_string_expression(self):
        """Test non-string expression is rejected."""
        calc = Calculator()
        result = calc.execute(expression=123)  # Pass int instead of string

        assert result.success is False
        assert "non-empty string" in result.error.lower()

    def test_invalid_syntax(self):
        """Test expression with invalid syntax."""
        calc = Calculator()
        # Missing operand after operator
        result = calc.execute(expression="2 + ")

        assert result.success is False
        assert "syntax" in result.error.lower()

    def test_unsupported_function(self):
        """Test calling unsupported function."""
        calc = Calculator()
        # Try to call a dangerous function
        result = calc.execute(expression="exec('print(1)')")

        assert result.success is False
        assert "unsupported" in result.error.lower()

    def test_code_injection_attempt(self):
        """Test code injection attempts are blocked."""
        calc = Calculator()
        malicious_expressions = [
            "__import__('os').system('ls')",
            "eval('print(1)')",
            "compile('print(1)', '<string>', 'exec')",
            "globals()",
            "locals()",
        ]

        for expr in malicious_expressions:
            result = calc.execute(expression=expr)
            assert result.success is False, f"Security bypass with: {expr}"

    def test_extremely_long_expression(self):
        """Test extremely long expression."""
        calc = Calculator()
        # Create long expression: 1+1+1+1+... (keep under Python recursion limit)
        long_expr = "+".join(["1"] * 500)
        result = calc.execute(expression=long_expr)

        # Should either succeed or fail gracefully (not crash)
        assert isinstance(result, ToolResult)
        if result.success:
            assert result.data["result"] == 500
        else:
            assert result.error is not None

    def test_domain_error_math_functions(self):
        """Test math domain errors (e.g., sqrt of negative number)."""
        calc = Calculator()
        result = calc.execute(expression="sqrt(-1)")

        assert result.success is False
        assert "value" in result.error.lower() or "domain" in result.error.lower()

    def test_logarithm_of_zero(self):
        """Test logarithm of zero."""
        calc = Calculator()
        result = calc.execute(expression="log(0)")

        assert result.success is False

    def test_unsupported_ast_node(self):
        """Test expression with unsupported AST node."""
        calc = Calculator()
        # Dictionary literal not supported
        result = calc.execute(expression="{'a': 1}")

        assert result.success is False
        assert "unsupported" in result.error.lower()


class TestFileWriterEdgeCases:
    """Test FileWriter tool edge cases and security boundaries."""

    def setup_method(self):
        """Set up temp directory for tests."""
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up temp directory."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_path_traversal_attack(self):
        """Test path traversal attack is blocked."""
        writer = FileWriter()
        malicious_paths = [
            "../../../etc/passwd",
            "../../sensitive.txt",
            f"{self.temp_dir}/../../../etc/hosts",
        ]

        for path in malicious_paths:
            result = writer.execute(file_path=path, content="malicious content")
            assert result.success is False, f"Path traversal not blocked: {path}"
            assert "path" in result.error.lower() or "safe" in result.error.lower()

    def test_forbidden_system_paths(self):
        """Test writing to forbidden system paths is blocked."""
        writer = FileWriter()
        forbidden_paths = [
            "/etc/passwd",
            "/sys/kernel/config",
            "/proc/sys/kernel/hostname",
            "/dev/null",
        ]

        for path in forbidden_paths:
            result = writer.execute(file_path=path, content="malicious")
            assert result.success is False, f"Forbidden path not blocked: {path}"

    def test_forbidden_file_extensions(self):
        """Test forbidden file extensions are blocked."""
        writer = FileWriter(config={"allowed_root": self.temp_dir})
        forbidden_extensions = [
            ".exe",
            ".dll",
            ".so",
            ".sh",
            ".bash",
            ".bat",
            ".cmd",
            ".ps1",
        ]

        for ext in forbidden_extensions:
            path = os.path.join(self.temp_dir, f"malicious{ext}")
            result = writer.execute(file_path=path, content="malicious")
            assert result.success is False, f"Forbidden extension not blocked: {ext}"
            assert "forbidden" in result.error.lower()

    def test_content_exceeds_max_size(self):
        """Test content exceeding maximum size is rejected."""
        writer = FileWriter()
        # 11MB content (exceeds 10MB limit)
        large_content = "x" * (11 * 1024 * 1024)

        path = os.path.join(self.temp_dir, "large.txt")
        result = writer.execute(file_path=path, content=large_content)

        assert result.success is False
        assert "exceeds" in result.error.lower() or "size" in result.error.lower()

    def test_overwrite_protection(self):
        """Test overwrite protection works."""
        writer = FileWriter(config={"allowed_root": self.temp_dir})
        path = os.path.join(self.temp_dir, "existing.txt")

        # Create file first
        result1 = writer.execute(file_path=path, content="original content")
        assert result1.success is True

        # Try to overwrite without permission
        result2 = writer.execute(file_path=path, content="new content", overwrite=False)
        assert result2.success is False
        assert "exist" in result2.error.lower() or "overwrite" in result2.error.lower()

        # With overwrite=True should succeed
        result3 = writer.execute(file_path=path, content="new content", overwrite=True)
        assert result3.success is True

    def test_writing_to_directory(self):
        """Test writing to directory path fails."""
        writer = FileWriter()
        dir_path = os.path.join(self.temp_dir, "test_dir")
        os.makedirs(dir_path)

        result = writer.execute(file_path=dir_path, content="content")

        assert result.success is False
        # PathSafetyValidator treats directory as "file exists and overwrite not allowed"
        assert "exist" in result.error.lower() or "directory" in result.error.lower()

    def test_missing_parent_directory_without_create(self):
        """Test missing parent directory fails when create_dirs=False."""
        writer = FileWriter()
        path = os.path.join(self.temp_dir, "nonexistent", "subdir", "file.txt")

        result = writer.execute(file_path=path, content="content", create_dirs=False)

        assert result.success is False
        assert "directory" in result.error.lower() or "exist" in result.error.lower()

    def test_empty_file_path(self):
        """Test empty file path is rejected."""
        writer = FileWriter()
        result = writer.execute(file_path="", content="content")

        assert result.success is False
        assert "file_path" in result.error.lower()

    def test_non_string_content(self):
        """Test non-string content is rejected."""
        writer = FileWriter()
        path = os.path.join(self.temp_dir, "test.txt")

        result = writer.execute(
            file_path=path, content=123  # Pass int instead of string
        )

        assert result.success is False
        assert "content" in result.error.lower() and "string" in result.error.lower()


class TestWebScraperEdgeCases:
    """Test WebScraper tool edge cases and security boundaries."""

    def test_ssrf_localhost(self):
        """Test SSRF attack targeting localhost is blocked."""
        scraper = WebScraper()
        malicious_urls = [
            "http://localhost/admin",
            "http://127.0.0.1/secrets",
            "http://0.0.0.0/internal",
        ]

        for url in malicious_urls:
            result = scraper.execute(url=url)
            assert result.success is False, f"SSRF not blocked: {url}"
            assert "forbidden" in result.error.lower() or "ssrf" in result.error.lower()

    def test_ssrf_aws_metadata(self):
        """Test SSRF attack targeting cloud metadata endpoints."""
        scraper = WebScraper()
        metadata_urls = [
            "http://169.254.169.254/latest/meta-data/",  # AWS
            "http://metadata.google.internal/computeMetadata/v1/",  # GCP
        ]

        for url in metadata_urls:
            result = scraper.execute(url=url)
            assert result.success is False, f"Metadata endpoint not blocked: {url}"
            assert "forbidden" in result.error.lower()

    def test_ssrf_private_networks(self):
        """Test SSRF attack targeting private networks."""
        scraper = WebScraper()
        private_ips = [
            "http://10.0.0.1/internal",  # RFC 1918
            "http://172.16.0.1/private",  # RFC 1918
            "http://192.168.1.1/admin",  # RFC 1918
        ]

        for url in private_ips:
            result = scraper.execute(url=url)
            assert result.success is False, f"Private network not blocked: {url}"
            assert (
                "forbidden" in result.error.lower() or "private" in result.error.lower()
            )

    def test_url_validation_ipv6_localhost(self):
        """Test IPv6 localhost is blocked."""
        is_safe, error = validate_url_safety("http://[::1]/admin")
        assert is_safe is False
        assert "forbidden" in error.lower()

    def test_invalid_url_missing_protocol(self):
        """Test URL without protocol is rejected."""
        scraper = WebScraper()
        result = scraper.execute(url="example.com")

        assert result.success is False
        assert "http" in result.error.lower()

    def test_empty_url(self):
        """Test empty URL is rejected."""
        scraper = WebScraper()
        result = scraper.execute(url="")

        assert result.success is False

    def test_rate_limiting(self):
        """Test rate limiting prevents excessive requests."""
        scraper = WebScraper()

        # Mock httpx to avoid actual network calls
        with patch("temper_ai.tools.web_scraper.httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/html"}
            mock_response.content = b"<html>test</html>"
            mock_response.text = "<html>test</html>"

            mock_client.return_value.__enter__.return_value.get.return_value = (
                mock_response
            )

            # Make requests up to rate limit (10 per minute)
            for i in range(11):
                result = scraper.execute(url="http://example.com")

                if i < 10:
                    # First 10 should succeed
                    assert (
                        result.success is True
                        or "rate limit" not in result.error.lower()
                    )
                else:
                    # 11th should be rate limited
                    assert result.success is False
                    assert "rate limit" in result.error.lower()

    def test_timeout_handling(self):
        """Test timeout is handled gracefully."""
        import httpx

        scraper = WebScraper()

        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.TimeoutException("Timeout")

        with (
            patch(
                "temper_ai.tools.web_scraper.validate_url_safety",
                return_value=(True, None),
            ),
            patch.object(scraper, "_get_client", return_value=mock_client),
        ):
            result = scraper.execute(url="http://example.com", timeout=1)

            assert result.success is False
            assert "timed out" in result.error.lower()

    def test_http_error_handling(self):
        """Test HTTP errors are handled gracefully."""
        import httpx

        scraper = WebScraper()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.reason_phrase = "Not Found"
        mock_response.is_redirect = False
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=Mock(), response=mock_response
        )

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with (
            patch(
                "temper_ai.tools.web_scraper.validate_url_safety",
                return_value=(True, None),
            ),
            patch.object(scraper, "_get_client", return_value=mock_client),
        ):
            result = scraper.execute(url="http://example.com/notfound")

            assert result.success is False
            assert "404" in result.error

    def test_unsupported_content_type(self):
        """Test unsupported content type is rejected."""
        scraper = WebScraper()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"PDF binary data"
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with (
            patch(
                "temper_ai.tools.web_scraper.validate_url_safety",
                return_value=(True, None),
            ),
            patch.object(scraper, "_get_client", return_value=mock_client),
        ):
            result = scraper.execute(url="http://example.com/file.pdf")

            assert result.success is False
            assert (
                "unsupported" in result.error.lower()
                or "content type" in result.error.lower()
            )

    def test_content_exceeds_max_size(self):
        """Test content exceeding maximum size is rejected."""
        scraper = WebScraper()

        # Mock SSRF validation to pass for example.com
        with (
            patch(
                "temper_ai.tools.web_scraper.validate_url_safety",
                return_value=(True, None),
            ),
            patch("temper_ai.tools.web_scraper.httpx.Client") as mock_client,
        ):
            # 6MB content (exceeds 5MB limit)
            large_content = b"x" * (6 * 1024 * 1024)

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/html"}
            mock_response.content = large_content
            mock_response.is_redirect = False  # Not a redirect
            mock_response.text = "x" * (6 * 1024 * 1024)  # Add text property

            # Mock the client directly (not as context manager)
            mock_instance = MagicMock()
            mock_instance.get.return_value = mock_response
            mock_instance.is_closed = False
            mock_client.return_value = mock_instance

            result = scraper.execute(url="http://example.com/large.html")

            assert result.success is False
            assert "size" in result.error.lower() or "exceeds" in result.error.lower()


class TestParameterValidationEdgeCases:
    """Test parameter validation edge cases across tools."""

    def test_calculator_none_parameter(self):
        """Test Calculator with None parameter."""
        calc = Calculator()
        result = calc.execute(expression=None)

        assert result.success is False

    def test_file_writer_none_parameters(self):
        """Test FileWriter with None parameters."""
        writer = FileWriter()

        # None file_path
        result1 = writer.execute(file_path=None, content="test")
        assert result1.success is False

        # None content
        temp_dir = tempfile.mkdtemp()
        path = os.path.join(temp_dir, "test.txt")
        result2 = writer.execute(file_path=path, content=None)
        assert result2.success is False
        shutil.rmtree(temp_dir)

    def test_web_scraper_none_url(self):
        """Test WebScraper with None URL."""
        scraper = WebScraper()
        result = scraper.execute(url=None)

        assert result.success is False

    def test_extra_unknown_parameters(self):
        """Test tools handle extra unknown parameters gracefully."""
        calc = Calculator()
        # Extra unknown parameter should be ignored
        result = calc.execute(expression="2 + 2", unknown_param="value")

        # Should succeed (unknown params ignored)
        assert result.success is True

    def test_missing_required_parameters(self):
        """Test tools reject missing required parameters."""
        calc = Calculator()
        # Missing expression parameter
        result = calc.execute()

        assert result.success is False
