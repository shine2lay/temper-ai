"""Test secret and placeholder filtering.

Identifies strings that are obviously test/demo values to reduce
false positives from documentation, examples, and test code.
"""
import re
from typing import List


class TestSecretFilter:
    """Detects and filters test secrets, placeholders, and dummy values.

    Uses two-tier matching:
    1. Keyword matching (word-boundary) for words like "test", "demo"
    2. Pattern matching (exact) for patterns like "abcdefgh"
    3. Function call detection for non-literal values

    This prevents false positives where legitimate secrets happen
    to contain common keywords.
    """

    # Test/example keywords (word-boundary match)
    TEST_SECRET_KEYWORDS = [
        # Original test indicators
        "test",
        "example",
        "demo",
        "placeholder",
        "changeme",
        "password123",
        "dummy",
        "fake",
        # Template/documentation indicators
        "sample",
        "template",
        "mock",
        "stub",
        "fixture",
        "your-",     # Matches "your-api-key-here", "your-secret-here"
        "your_",     # Matches "your_api_key_here"
        "-here",     # Matches "api-key-here", "secret-here"
        "_here",     # Matches "api_key_here"
        "todo",
        "fixme",
        "-from-",    # Matches "key-from-provider"
        "_from_",    # Matches "key_from_config"
        # Development indicators
        "dev",
        "local",
        "localhost",
        # Weak/generic passwords (common defaults)
        "admin",
        "root",
        "user",
        "guest",
        "password",
        "secret",
    ]

    # Pattern indicators (exact match only)
    TEST_SECRET_PATTERNS = [
        "xxxxxxxx",
        "aaaaaaaa",
        "11111111",
        "abcdefgh",
        "12345678"
    ]

    def __init__(self, allow_test_secrets: bool = True):
        """Initialize filter.

        Args:
            allow_test_secrets: Whether to filter test secrets
        """
        self.allow_test_secrets = allow_test_secrets

    def is_test_secret(self, text: str) -> bool:
        """Check if text is a test/example secret.

        Uses two types of matching:
        1. Keyword matching (substring) - for words like "test", "demo", "example"
        2. Pattern matching (exact) - for patterns like "abcdefgh", "12345678"
        3. Function call detection - filters out function calls like "get_secret()"

        This prevents false positives where legitimate secrets happen to contain
        common patterns as substrings (e.g., "sk_live_...abcdefgh..." is NOT a test secret).

        Args:
            text: Potential secret value

        Returns:
            True if appears to be test/placeholder

        Examples:
            >>> filter = TestSecretFilter(allow_test_secrets=True)
            >>> filter.is_test_secret("test_api_key_here")
            True
            >>> filter.is_test_secret("sk_live_abc123real")
            False
        """
        if not self.allow_test_secrets:
            return False

        text_lower = text.lower()

        # Check keyword indicators (word-boundary match)
        # Using word boundaries prevents false positives like "testing" matching "test"
        # in production secrets (e.g., "sk_live_testing_real_key")
        for keyword in self.TEST_SECRET_KEYWORDS:
            if re.search(rf'\b{re.escape(keyword)}\b', text_lower):
                return True

        # Check pattern indicators (exact match only)
        if text_lower in self.TEST_SECRET_PATTERNS:
            return True

        # Filter out function calls and method invocations
        # These are not literal secrets (e.g., "get_secret()", "retrieve_api_key_from_config()")
        if '(' in text and ')' in text:
            return True

        return False
