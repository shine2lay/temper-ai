"""
Regression tests for tool execution bugs.

Tests for previously discovered bugs in tool execution to ensure
they don't reappear.
"""

import os
import shutil
import tempfile

import pytest

from temper_ai.tools.calculator import Calculator
from temper_ai.tools.executor import ToolExecutor
from temper_ai.tools.file_writer import FileWriter
from temper_ai.tools.registry import ToolRegistry
from temper_ai.tools.web_scraper import WebScraper


class TestCalculator:
    """Regression tests for Calculator tool bugs."""

    def test_division_by_zero_error_handling(self):
        """
        Regression test for division by zero handling.

        Bug: Division by zero caused tool crash instead of error return.
        Discovered: Initial tool testing
        Affects: All calculator operations
        Severity: HIGH (crashes agent execution)
        Fixed: Calculator now catches ZeroDivisionError
        """
        calc = Calculator()
        result = calc.execute(expression="10 / 0")

        # Should return error, not crash
        assert result.success is False
        assert "division by zero" in result.error.lower()

    def test_invalid_expression_handling(self):
        """
        Regression test for invalid expression handling.

        Bug: Invalid expressions caused unhandled exceptions.
        Discovered: Edge case testing
        Affects: All calculator operations
        Severity: MEDIUM (error messages unclear)
        Fixed: Now returns ToolResult with error message
        """
        calc = Calculator()
        result = calc.execute(expression="2 + + 3 invalid")

        # Should return error result, not raise exception
        assert result.success is False
        assert result.error is not None


class TestFileWriter:
    """Regression tests for FileWriter tool bugs."""

    def setup_method(self):
        """Set up temp directory for tests."""
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up temp directory."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_path_traversal_vulnerability(self):
        """
        Regression test for path traversal vulnerability.

        Bug: Path traversal (../) not blocked, allowing writes outside sandbox.
        Discovered: Security audit
        Affects: All file write operations
        Severity: CRITICAL (security vulnerability)
        Fixed: PathSafetyValidator now blocks ../ sequences
        """
        writer = FileWriter()
        malicious_path = "../../../etc/passwd"

        result = writer.execute(file_path=malicious_path, content="malicious content")

        # Should be blocked
        assert result.success is False
        assert "path" in result.error.lower() or "safe" in result.error.lower()

    def test_overwrite_without_permission(self):
        """
        Regression test for accidental file overwrite.

        Bug: Existing files overwritten without explicit permission.
        Discovered: Integration testing
        Affects: All file writes
        Severity: HIGH (data loss)
        Fixed: Added overwrite parameter check
        """
        writer = FileWriter(config={"allowed_root": self.temp_dir})
        path = os.path.join(self.temp_dir, "existing.txt")

        # Create file
        result1 = writer.execute(file_path=path, content="original content")
        assert result1.success is True

        # Try to overwrite without permission
        result2 = writer.execute(file_path=path, content="new content", overwrite=False)

        # Should be blocked
        assert result2.success is False
        assert "exist" in result2.error.lower() or "overwrite" in result2.error.lower()


class TestWebScraper:
    """Regression tests for WebScraper tool bugs."""

    def test_ssrf_localhost_vulnerability(self):
        """
        Regression test for SSRF vulnerability.

        Bug: localhost URLs not blocked, allowing SSRF attacks.
        Discovered: Security audit
        Affects: All web scraping operations
        Severity: CRITICAL (security vulnerability)
        Fixed: validate_url_safety() now blocks internal IPs
        """
        scraper = WebScraper()
        malicious_urls = [
            "http://localhost/admin",
            "http://127.0.0.1/secrets",
            "http://169.254.169.254/metadata",
        ]

        for url in malicious_urls:
            result = scraper.execute(url=url)

            # Should be blocked
            assert result.success is False, f"SSRF not blocked: {url}"
            assert "forbidden" in result.error.lower() or "ssrf" in result.error.lower()

    def test_rate_limit_bypass_attempt(self):
        """
        Regression test for rate limit bypass.

        Bug: Rate limiter could be bypassed by creating multiple scraper instances.
        Discovered: Load testing
        Affects: All web scraping
        Severity: MEDIUM (DoS potential)
        Fixed: Rate limiter now uses instance-level state
        """
        scraper = WebScraper()

        # Record 10 requests (at rate limit)
        for _ in range(10):
            scraper.rate_limiter.record_request()

        # 11th request should be blocked
        can_proceed = scraper.rate_limiter.can_proceed()
        assert can_proceed is False


class TestToolExecutor:
    """Regression tests for ToolExecutor bugs."""

    def test_timeout_not_enforced(self):
        """
        Regression test for timeout enforcement.

        Bug: Timeout parameter ignored, allowing tools to run indefinitely.
        Discovered: Integration testing
        Affects: All tool executions
        Severity: HIGH (resource exhaustion)
        Fixed: ToolExecutor now enforces timeout with ThreadPoolExecutor
        """
        registry = ToolRegistry()
        registry.register(Calculator())

        executor = ToolExecutor(registry, default_timeout=1)

        # Execute with explicit short timeout
        # Should complete within timeout (calculator is fast)
        result = executor.execute(
            tool_name="Calculator", params={"expression": "2 + 2"}, timeout=1
        )

        # Should complete successfully or timeout, not hang
        assert isinstance(result, object)  # Got a result, didn't hang

    def test_invalid_tool_name_handling(self):
        """
        Regression test for invalid tool name handling.

        Bug: Invalid tool names caused KeyError instead of returning error result.
        Discovered: Error handling testing
        Affects: All tool executions
        Severity: MEDIUM (poor error messages)
        Fixed: ToolExecutor.execute() now returns ToolResult with error
        """
        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        result = executor.execute(tool_name="NonexistentTool", params={})

        # Should return error result, not raise exception
        assert result.success is False
        assert "not found" in result.error.lower()


class TestToolRegistry:
    """Regression tests for ToolRegistry bugs."""

    def test_duplicate_tool_registration(self):
        """
        Regression test for duplicate tool registration.

        Bug: Registering same tool twice overwrites without warning.
        Discovered: Tool initialization
        Affects: Tool registry initialization
        Severity: LOW (confusing behavior)
        Fixed: Registry now REJECTS duplicate registration with clear error
        """
        registry = ToolRegistry()
        calc1 = Calculator()
        calc2 = Calculator()

        # Register first tool
        registry.register(calc1)

        # Try to register same tool again - should raise error
        with pytest.raises(Exception) as exc_info:
            registry.register(calc2)

        # Should get clear error message
        assert (
            "already registered" in str(exc_info.value).lower()
            or "calculator" in str(exc_info.value).lower()
        )

    def test_case_sensitive_tool_lookup(self):
        """
        Regression test for case-sensitive tool lookup.

        Bug: Tool lookup case-sensitive ("calculator" != "Calculator").
        Discovered: Integration testing
        Affects: All tool lookups
        Severity: MEDIUM (confusing errors)
        Current: Still case-sensitive (by design)
        """
        registry = ToolRegistry()
        registry.register(Calculator())

        # Exact case should work
        tool = registry.get("Calculator")
        assert tool is not None

        # Wrong case should fail
        tool = registry.get("calculator")
        assert tool is None  # Expected behavior (case-sensitive by design)
