"""Pattern compilation, caching, and matching for secret detection.

Encapsulates regex pattern management and provides iterator interface
for processing matches in a clean, composable way.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class PatternMatch:
    """Result of a single pattern match."""

    pattern_name: str  # e.g., "aws_access_key"
    matched_text: str  # Full regex match
    secret_value: str  # Extracted secret (capture group 2 if present, else full match)
    match_position: int  # Character offset in content
    match_length: int  # Length of matched text


class PatternMatcher:
    """Compile, cache, and iterate secret detection patterns.

    Handles:
    - Pattern compilation with caching
    - Case-insensitive matching
    - Capture group extraction
    - Iterator interface for clean processing
    """

    def __init__(self, enabled_patterns: list[str], patterns_dict: dict[str, str]):
        """Initialize pattern matcher.

        Args:
            enabled_patterns: List of pattern names to enable
            patterns_dict: Dict of {pattern_name: regex_string}

        Raises:
            ValueError: If unknown pattern name specified
        """
        self.enabled_patterns = enabled_patterns
        self.patterns_dict = patterns_dict
        self.compiled_patterns = self._compile_patterns()

    def _compile_patterns(self) -> dict[str, re.Pattern]:
        """Compile enabled regex patterns.

        Returns:
            Dict of {pattern_name: compiled_regex}

        SECURITY NOTE: All patterns use bounded quantifiers
        to prevent ReDoS attacks.
        """
        compiled = {}
        for name in self.enabled_patterns:
            if name not in self.patterns_dict:
                raise ValueError(f"Unknown pattern: {name}")
            pattern_str = self.patterns_dict[name]
            compiled[name] = re.compile(pattern_str, re.IGNORECASE)
        return compiled

    def find_matches(self, content: str) -> Iterator[PatternMatch]:
        """Find all pattern matches in content.

        Args:
            content: Text to scan

        Yields:
            PatternMatch for each match

        Example:
            >>> matcher = PatternMatcher(
            ...     ["aws_access_key"],
            ...     {"aws_access_key": r"AKIA[0-9A-Z]{16}"}
            ... )
            >>> for match in matcher.find_matches("AKIAIOSFODNN7EXAMPLE"):
            ...     print(match.pattern_name, match.secret_value)
            aws_access_key AKIAIOSFODNN7EXAMPLE
        """
        for pattern_name, pattern_regex in self.compiled_patterns.items():
            for regex_match in pattern_regex.finditer(content):
                matched_text = regex_match.group(0)

                # Extract secret value from capture group 2 if available
                secret_value = (
                    regex_match.group(2)
                    if regex_match.lastindex and regex_match.lastindex >= 2
                    else matched_text
                )

                yield PatternMatch(
                    pattern_name=pattern_name,
                    matched_text=matched_text,
                    secret_value=secret_value,
                    match_position=regex_match.start(),
                    match_length=len(matched_text),
                )
