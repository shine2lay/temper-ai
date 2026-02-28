"""Tests for temper_ai/safety/pattern_matcher.py."""

import pytest

from temper_ai.safety.pattern_matcher import PatternMatch, PatternMatcher


class TestPatternMatch:
    def test_dataclass_field_assignment(self):
        match = PatternMatch(
            pattern_name="aws_access_key",
            matched_text="AKIAIOSFODNN7EXAMPLE",
            secret_value="AKIAIOSFODNN7EXAMPLE",
            match_position=0,
            match_length=20,
        )
        assert match.pattern_name == "aws_access_key"
        assert match.matched_text == "AKIAIOSFODNN7EXAMPLE"
        assert match.secret_value == "AKIAIOSFODNN7EXAMPLE"
        assert match.match_position == 0
        assert match.match_length == 20


class TestPatternMatcher:
    AWS_PATTERN = r"AKIA[0-9A-Z]{16}"
    OPENAI_PATTERN = r"sk-[a-zA-Z0-9]{20}"

    def _make_matcher(self, names, patterns):
        return PatternMatcher(enabled_patterns=names, patterns_dict=patterns)

    def test_compile_patterns_valid(self):
        matcher = self._make_matcher(
            ["aws_access_key"],
            {"aws_access_key": self.AWS_PATTERN},
        )
        assert "aws_access_key" in matcher.compiled_patterns

    def test_compile_unknown_pattern_raises(self):
        with pytest.raises(ValueError, match="Unknown pattern"):
            self._make_matcher(["nonexistent"], {"aws_access_key": self.AWS_PATTERN})

    def test_find_matches_no_matches(self):
        matcher = self._make_matcher(
            ["aws_access_key"],
            {"aws_access_key": self.AWS_PATTERN},
        )
        results = list(matcher.find_matches("no secrets here"))
        assert results == []

    def test_find_matches_single_pattern(self):
        key = "AKIAIOSFODNN7EXAMPLE"
        matcher = self._make_matcher(
            ["aws_access_key"],
            {"aws_access_key": self.AWS_PATTERN},
        )
        results = list(matcher.find_matches(f"key={key}"))
        assert len(results) == 1
        assert results[0].pattern_name == "aws_access_key"
        assert results[0].matched_text == key

    def test_find_matches_multiple_patterns(self):
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        openai_key = "sk-abcdefghijklmnopqrst"
        matcher = self._make_matcher(
            ["aws_access_key", "openai_key"],
            {
                "aws_access_key": self.AWS_PATTERN,
                "openai_key": self.OPENAI_PATTERN,
            },
        )
        content = f"{aws_key} {openai_key}"
        results = list(matcher.find_matches(content))
        names = {r.pattern_name for r in results}
        assert "aws_access_key" in names
        assert "openai_key" in names

    def test_find_matches_capture_group_2(self):
        # Pattern with two groups: group 1 = prefix, group 2 = secret value
        pattern_with_prefix = r"(PREFIX:)([A-Z0-9]{8})"
        matcher = self._make_matcher(
            ["prefixed"],
            {"prefixed": pattern_with_prefix},
        )
        results = list(matcher.find_matches("data PREFIX:ABCD1234 end"))
        assert len(results) == 1
        # secret_value should be group 2 only, not the full match
        assert results[0].secret_value == "ABCD1234"
        assert results[0].matched_text == "PREFIX:ABCD1234"

    def test_find_matches_no_capture_group(self):
        # Pattern with no capture groups — full match used as secret_value
        matcher = self._make_matcher(
            ["aws_access_key"],
            {"aws_access_key": self.AWS_PATTERN},
        )
        key = "AKIAIOSFODNN7EXAMPLE"
        results = list(matcher.find_matches(key))
        assert len(results) == 1
        assert results[0].secret_value == key
        assert results[0].matched_text == key

    def test_find_matches_position_and_length(self):
        key = "AKIAIOSFODNN7EXAMPLE"
        prefix = "prefix "
        content = prefix + key
        matcher = self._make_matcher(
            ["aws_access_key"],
            {"aws_access_key": self.AWS_PATTERN},
        )
        results = list(matcher.find_matches(content))
        assert len(results) == 1
        assert results[0].match_position == len(prefix)
        assert results[0].match_length == len(key)

    def test_case_insensitive_matching(self):
        # Pattern should match regardless of case in the content
        # Use a pattern that can match case-insensitively
        matcher = self._make_matcher(
            ["token"],
            {"token": r"secret[0-9]{4}"},
        )
        results_lower = list(matcher.find_matches("secret1234"))
        results_upper = list(matcher.find_matches("SECRET1234"))
        assert len(results_lower) == 1
        assert len(results_upper) == 1

    def test_empty_content_no_matches(self):
        matcher = self._make_matcher(
            ["aws_access_key"],
            {"aws_access_key": self.AWS_PATTERN},
        )
        results = list(matcher.find_matches(""))
        assert results == []
