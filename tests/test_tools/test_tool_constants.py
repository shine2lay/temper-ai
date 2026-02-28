"""Tests for tool constants across multiple constant modules.

Covers:
- temper_ai/tools/constants.py (bash, web scraper, DNS, calculator, file, search, SSRF)
- temper_ai/tools/field_names.py (ToolResultFields)
- temper_ai/tools/git_tool_constants.py (allowed ops, blocked flags)
- temper_ai/tools/http_client_constants.py (blocked hosts, allowed methods)
- temper_ai/tools/tool_cache_constants.py (cache defaults)
- temper_ai/tools/workflow_rate_limiter_constants.py (rate limiter defaults)
"""

from temper_ai.tools.constants import (
    DEFAULT_BASH_TIMEOUT,
    DEFAULT_SEARCH_MAX_RESULTS,
    DEFAULT_SEARCH_TIMEOUT,
    DEFAULT_WEB_TIMEOUT,
    DNS_CACHE_MAX_SIZE,
    DNS_CACHE_TTL_SECONDS,
    DNS_RESOLUTION_TIMEOUT_SECONDS,
    ERROR_RESPONSE_TEXT_MAX_LENGTH,
    FILE_ENCODING_UTF8,
    MAX_BASH_OUTPUT_LENGTH,
    MAX_BASH_TIMEOUT,
    MAX_CONTENT_SIZE,
    MAX_EXPONENT,
    MAX_FILE_SIZE,
    MAX_NESTING_DEPTH,
    MAX_REDIRECTS,
    MAX_SEARCH_RESULTS,
    RATE_LIMIT_WINDOW_SECONDS,
    SSRF_ERROR_SUFFIX,
    URL_MAX_LENGTH,
    URL_MIN_LENGTH,
)
from temper_ai.tools.field_names import ToolResultFields
from temper_ai.tools.git_tool_constants import (
    GIT_ALLOWED_OPERATIONS,
    GIT_BLOCKED_FLAGS,
    GIT_DEFAULT_TIMEOUT,
    GIT_MAX_DIFF_SIZE,
)
from temper_ai.tools.http_client_constants import (
    HTTP_ALLOWED_METHODS,
    HTTP_BLOCKED_HOSTS,
    HTTP_DEFAULT_TIMEOUT,
    HTTP_MAX_HEADER_COUNT,
    HTTP_MAX_RESPONSE_SIZE,
)
from temper_ai.tools.tool_cache_constants import (
    CACHE_KEY_SEPARATOR,
    DEFAULT_CACHE_MAX_SIZE,
    DEFAULT_TOOL_CACHE_TTL_SECONDS,
)
from temper_ai.tools.workflow_rate_limiter_constants import (
    DEFAULT_MAX_RPM,
    DEFAULT_MAX_WAIT_SECONDS,
    SLIDING_WINDOW_SECONDS,
)


class TestBashConstants:
    """Bash tool constants are positive and consistent."""

    def test_default_timeout_positive(self):
        assert DEFAULT_BASH_TIMEOUT > 0

    def test_max_timeout_exceeds_default(self):
        assert MAX_BASH_TIMEOUT > DEFAULT_BASH_TIMEOUT

    def test_max_output_length_positive(self):
        assert MAX_BASH_OUTPUT_LENGTH > 0


class TestWebScraperConstants:
    """Web scraper constants are positive and consistent."""

    def test_default_web_timeout_positive(self):
        assert DEFAULT_WEB_TIMEOUT > 0

    def test_max_content_size_positive(self):
        assert MAX_CONTENT_SIZE > 0

    def test_url_min_lt_max(self):
        assert URL_MIN_LENGTH < URL_MAX_LENGTH

    def test_max_redirects_positive(self):
        assert MAX_REDIRECTS > 0

    def test_rate_limit_window_positive(self):
        assert RATE_LIMIT_WINDOW_SECONDS > 0


class TestDnsConstants:
    """DNS constants are reasonable."""

    def test_resolution_timeout_positive(self):
        assert DNS_RESOLUTION_TIMEOUT_SECONDS > 0

    def test_cache_ttl_positive(self):
        assert DNS_CACHE_TTL_SECONDS > 0

    def test_cache_max_size_positive(self):
        assert DNS_CACHE_MAX_SIZE > 0


class TestCalculatorConstants:
    """Calculator tool constants."""

    def test_max_nesting_depth_positive(self):
        assert MAX_NESTING_DEPTH > 0

    def test_max_exponent_positive(self):
        assert MAX_EXPONENT > 0


class TestFileConstants:
    """File operation constants."""

    def test_max_file_size_positive(self):
        assert MAX_FILE_SIZE > 0

    def test_encoding_is_utf8(self):
        assert FILE_ENCODING_UTF8 == "utf-8"


class TestSearchConstants:
    """Search-related constants."""

    def test_default_search_timeout_positive(self):
        assert DEFAULT_SEARCH_TIMEOUT > 0

    def test_max_results_exceeds_default(self):
        assert MAX_SEARCH_RESULTS > DEFAULT_SEARCH_MAX_RESULTS


class TestSsrfConstants:
    """SSRF protection constants."""

    def test_error_suffix_is_string(self):
        assert isinstance(SSRF_ERROR_SUFFIX, str)
        assert len(SSRF_ERROR_SUFFIX) > 0


class TestErrorFormatConstants:
    """Error formatting constants."""

    def test_error_response_text_max_positive(self):
        assert ERROR_RESPONSE_TEXT_MAX_LENGTH > 0


class TestToolResultFields:
    """ToolResultFields has expected constants as non-empty strings."""

    def test_exit_code(self):
        assert ToolResultFields.EXIT_CODE == "exit_code"

    def test_stdout(self):
        assert ToolResultFields.STDOUT == "stdout"

    def test_stderr(self):
        assert ToolResultFields.STDERR == "stderr"

    def test_command(self):
        assert ToolResultFields.COMMAND == "command"

    def test_duration(self):
        assert ToolResultFields.DURATION_SECONDS == "duration_seconds"

    def test_error(self):
        assert ToolResultFields.ERROR == "error"


class TestGitToolConstants:
    """Git tool constants."""

    def test_allowed_operations_is_frozenset(self):
        assert isinstance(GIT_ALLOWED_OPERATIONS, frozenset)

    def test_allowed_operations_includes_common_ops(self):
        for op in ("status", "diff", "log", "commit", "branch", "add"):
            assert op in GIT_ALLOWED_OPERATIONS

    def test_blocked_flags_is_frozenset(self):
        assert isinstance(GIT_BLOCKED_FLAGS, frozenset)

    def test_blocked_flags_includes_force(self):
        assert "--force" in GIT_BLOCKED_FLAGS
        assert "-f" in GIT_BLOCKED_FLAGS

    def test_blocked_flags_includes_hard(self):
        assert "--hard" in GIT_BLOCKED_FLAGS

    def test_default_timeout_positive(self):
        assert GIT_DEFAULT_TIMEOUT > 0

    def test_max_diff_size_positive(self):
        assert GIT_MAX_DIFF_SIZE > 0


class TestHttpClientConstants:
    """HTTP client constants."""

    def test_blocked_hosts_is_frozenset(self):
        assert isinstance(HTTP_BLOCKED_HOSTS, frozenset)

    def test_blocked_hosts_includes_metadata_endpoints(self):
        assert "169.254.169.254" in HTTP_BLOCKED_HOSTS
        assert "metadata.google.internal" in HTTP_BLOCKED_HOSTS

    def test_blocked_hosts_includes_localhost(self):
        assert "localhost" in HTTP_BLOCKED_HOSTS
        assert "127.0.0.1" in HTTP_BLOCKED_HOSTS

    def test_allowed_methods_is_frozenset(self):
        assert isinstance(HTTP_ALLOWED_METHODS, frozenset)

    def test_allowed_methods_includes_common(self):
        for method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            assert method in HTTP_ALLOWED_METHODS

    def test_default_timeout_positive(self):
        assert HTTP_DEFAULT_TIMEOUT > 0

    def test_max_response_size_positive(self):
        assert HTTP_MAX_RESPONSE_SIZE > 0

    def test_max_header_count_positive(self):
        assert HTTP_MAX_HEADER_COUNT > 0


class TestToolCacheConstants:
    """Tool cache constants."""

    def test_default_cache_max_size_positive(self):
        assert DEFAULT_CACHE_MAX_SIZE > 0

    def test_default_ttl_positive(self):
        assert DEFAULT_TOOL_CACHE_TTL_SECONDS > 0

    def test_cache_key_separator_is_string(self):
        assert isinstance(CACHE_KEY_SEPARATOR, str)
        assert len(CACHE_KEY_SEPARATOR) > 0


class TestWorkflowRateLimiterConstants:
    """Workflow rate limiter constants."""

    def test_default_max_rpm_positive(self):
        assert DEFAULT_MAX_RPM > 0

    def test_default_max_wait_positive(self):
        assert DEFAULT_MAX_WAIT_SECONDS > 0

    def test_sliding_window_positive(self):
        assert SLIDING_WINDOW_SECONDS > 0
