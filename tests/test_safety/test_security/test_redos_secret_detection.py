"""
Security tests for ReDoS vulnerability fix in secret detection (code-crit-14).

Ensures that the base64 pattern does not cause catastrophic backtracking
when processing malicious input designed to trigger exponential regex behavior.
"""

import time

import pytest

from temper_ai.shared.utils.secrets import detect_secret_patterns


class TestReDoSPrevention:
    """Test that ReDoS vulnerability is fixed."""

    def test_normal_base64_still_detected(self):
        """Verify legitimate base64 strings are still detected."""
        # Valid base64 string (40+ chars)
        base64_secret = (
            "dGhpc2lzYXZlcnlsb25nYmFzZTY0ZW5jb2RlZHN0cmluZ3RoYXRsb29rc2xpa2Vhc2VjcmV0"
        )

        is_secret, confidence = detect_secret_patterns(base64_secret)
        assert is_secret is True
        assert confidence == "medium"

    def test_base64_with_padding_detected(self):
        """Verify base64 strings with padding are detected."""
        # Base64 with single padding
        base64_with_padding = (
            "SGVsbG9Xb3JsZFRoaXNJc0FMb25nQmFzZTY0U3RyaW5nVGhhdE5lZWRzUGFkZGluZw=="
        )

        is_secret, confidence = detect_secret_patterns(base64_with_padding)
        assert is_secret is True
        assert confidence == "medium"

    def test_short_base64_not_detected(self):
        """Verify short base64 strings (< 40 chars) are not detected."""
        short_base64 = "c2hvcnQ="  # "short" in base64 (< 40 chars)

        is_secret, confidence = detect_secret_patterns(short_base64)
        assert is_secret is False

    def test_long_valid_base64_within_limit(self):
        """Verify base64 strings up to 100 chars are detected."""
        # Create 90-char base64 string (within new limit)
        long_base64 = "A" * 90 + "=="

        is_secret, confidence = detect_secret_patterns(long_base64)
        assert is_secret is True
        assert confidence == "medium"

    def test_redos_attack_completes_quickly(self):
        """Verify malicious input designed to trigger ReDoS completes quickly."""
        # This would cause catastrophic backtracking with unbounded {40,}
        # Pattern tries to match [A-Za-z0-9+/]{40,} but fails at the end
        attack_string = "A" * 100 + "!"  # 100 valid chars + invalid char

        start = time.time()
        is_secret, confidence = detect_secret_patterns(attack_string)
        elapsed = time.time() - start

        # Should complete in < 100ms (would take seconds with ReDoS)
        assert elapsed < 0.1, f"ReDoS detected: took {elapsed:.3f}s"
        # Note: re.search() finds "A"*100 within string, so it matches
        # The key security fix is that it completes quickly

    def test_redos_attack_long_string_completes_quickly(self):
        """Verify very long malicious strings complete quickly."""
        # Even longer attack string
        attack_string = "A" * 1000 + "!"

        start = time.time()
        is_secret, confidence = detect_secret_patterns(attack_string)
        elapsed = time.time() - start

        # Should still complete quickly (< 200ms for safety margin)
        assert elapsed < 0.2, f"ReDoS detected: took {elapsed:.3f}s"
        # The key security fix is preventing exponential time complexity

    def test_redos_attack_alternating_pattern(self):
        """Verify alternating pattern attack completes quickly."""
        # Pattern that maximizes backtracking possibilities
        attack_string = ("A" * 50 + "B" * 50) + "!"

        start = time.time()
        is_secret, confidence = detect_secret_patterns(attack_string)
        elapsed = time.time() - start

        assert elapsed < 0.1, f"ReDoS detected: took {elapsed:.3f}s"
        # The key security fix is preventing exponential time complexity

    def test_exactly_100_chars_detected(self):
        """Verify base64 at upper limit (100 chars) is detected."""
        # Exactly 100-char base64 string (new limit per code-crit-redos-regex-05)
        base64_100 = "A" * 100

        is_secret, confidence = detect_secret_patterns(base64_100)
        assert is_secret is True
        assert confidence == "medium"

    def test_over_100_chars_still_detected(self):
        """Verify base64 over 100 chars still matches within limit."""
        # 150-char base64 string
        base64_150 = "A" * 150

        is_secret, confidence = detect_secret_patterns(base64_150)
        # Pattern matches first 40-100 chars via re.search()
        # This is acceptable - the key fix is preventing ReDoS
        assert is_secret is True
        assert confidence == "medium"

    def test_non_base64_chars_rejected(self):
        """Verify strings with only non-base64 characters are rejected."""
        invalid_strings = [
            "!" * 50,  # Invalid chars only
            "Hello World! " * 10,  # Spaces and punctuation
            "@@@@" * 20,  # Special chars
        ]

        for invalid in invalid_strings:
            is_secret, confidence = detect_secret_patterns(invalid)
            assert is_secret is False, f"Should not detect: {invalid[:30]}"

        # Strings with embedded base64 may match (acceptable)
        mixed_string = "A" * 40 + "@" + "A" * 10
        is_secret, _ = detect_secret_patterns(mixed_string)
        # This may match the "A"*40 portion, which is fine


class TestBackwardCompatibility:
    """Test that legitimate secret detection still works."""

    def test_openai_keys_still_detected(self):
        """Verify OpenAI API keys are still detected."""
        openai_key = "sk-proj-abc123def456ghi789jkl012mno345pqr678"

        is_secret, confidence = detect_secret_patterns(openai_key)
        assert is_secret is True
        assert confidence == "high"

    def test_aws_keys_still_detected(self):
        """Verify AWS access keys are still detected."""
        aws_key = "AKIAIOSFODNN7EXAMPLE"

        is_secret, confidence = detect_secret_patterns(aws_key)
        assert is_secret is True
        assert confidence == "high"

    def test_md5_hashes_still_detected(self):
        """Verify MD5 hashes are still detected."""
        md5_hash = "5d41402abc4b2a76b9719d911017c592"

        is_secret, confidence = detect_secret_patterns(md5_hash)
        assert is_secret is True
        assert confidence == "medium"

    def test_sha1_hashes_still_detected(self):
        """Verify SHA1 hashes are still detected."""
        sha1_hash = "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"

        is_secret, confidence = detect_secret_patterns(sha1_hash)
        assert is_secret is True
        assert confidence == "medium"

    def test_github_tokens_still_detected(self):
        """Verify GitHub tokens are still detected."""
        github_token = "ghp_1234567890abcdefghijklmnopqrst"

        is_secret, confidence = detect_secret_patterns(github_token)
        assert is_secret is True
        assert confidence == "high"

    def test_normal_text_not_detected(self):
        """Verify normal text is not detected as secret."""
        normal_texts = [
            "Hello, world!",
            "This is a normal sentence.",
            "Email: user@example.com",
            "Phone: 555-123-4567",
        ]

        for text in normal_texts:
            is_secret, confidence = detect_secret_patterns(text)
            assert is_secret is False, f"Should not detect: {text}"


class TestPerformance:
    """Test performance of pattern matching after ReDoS fix."""

    def test_batch_processing_performance(self):
        """Verify batch processing of multiple strings is fast."""
        test_strings = [
            "A" * 100 + "!",  # Potential ReDoS trigger
            "sk-proj-abc123def456ghi789",  # OpenAI key
            "normal text here",  # Clean text
            "AKIAIOSFODNN7EXAMPLE",  # AWS key
            "B" * 200 + "@",  # Another ReDoS trigger
        ] * 20  # 100 strings total

        start = time.time()
        for text in test_strings:
            detect_secret_patterns(text)
        elapsed = time.time() - start

        # Should process 100 strings in < 1 second
        assert (
            elapsed < 1.0
        ), f"Batch processing too slow: {elapsed:.3f}s for 100 strings"

    def test_worst_case_performance(self):
        """Verify worst-case scenario completes in reasonable time."""
        # Worst case: long string that almost matches but fails at end
        worst_case = "A" * 499 + "!"  # 499 valid chars + fail

        start = time.time()
        detect_secret_patterns(worst_case)
        elapsed = time.time() - start

        # Should complete in < 50ms even in worst case
        assert elapsed < 0.05, f"Worst case too slow: {elapsed:.3f}s"


class TestAdditionalReDoSPatterns:
    """Test ReDoS protection for Anthropic and Google OAuth patterns (code-crit-redos-regex-05)."""

    def test_anthropic_key_redos_prevented(self):
        """Verify Anthropic API key pattern doesn't cause ReDoS."""
        # Attack payload: valid prefix + many digits + long key + invalid char
        attack = "sk-ant-api" + "9" * 10 + "-" + "A" * 150 + "!"

        start = time.time()
        result = detect_secret_patterns(attack)
        elapsed = time.time() - start

        # Should complete quickly (bounded quantifiers prevent catastrophic backtracking)
        assert elapsed < 0.01, f"Anthropic pattern ReDoS: {elapsed:.3f}s"

    def test_google_oauth_redos_prevented(self):
        """Verify Google OAuth pattern doesn't cause ReDoS."""
        # Attack payload: valid prefix + many valid chars + invalid char
        attack = "ya29." + "A" * 600 + "!"

        start = time.time()
        result = detect_secret_patterns(attack)
        elapsed = time.time() - start

        # Should complete quickly (bounded quantifiers prevent catastrophic backtracking)
        assert elapsed < 0.01, f"Google OAuth pattern ReDoS: {elapsed:.3f}s"

    def test_legitimate_anthropic_key_detected(self):
        """Verify legitimate Anthropic keys are still detected."""
        # Valid Anthropic API key format
        valid_key = "sk-ant-api03-" + "A" * 50

        is_secret, confidence = detect_secret_patterns(valid_key)
        assert is_secret is True
        assert confidence == "high"

    def test_legitimate_google_oauth_detected(self):
        """Verify legitimate Google OAuth tokens are still detected."""
        # Valid Google OAuth token format
        valid_token = "ya29." + "a" * 100

        is_secret, confidence = detect_secret_patterns(valid_token)
        assert is_secret is True
        assert confidence == "high"


class TestInputValidation:
    """Test input length validation (defense in depth).

    The limit was raised from 10KB to 100KB (SIZE_100KB = 102400) to support
    multi-stage workflows with accumulated context while still preventing ReDoS.
    """

    def test_oversized_input_rejected(self):
        """Verify inputs over 100KB are rejected."""
        huge_input = "A" * 103000  # Over 100KB (102400)

        with pytest.raises(ValueError, match="too long"):
            detect_secret_patterns(huge_input)

    def test_exactly_100kb_accepted(self):
        """Verify 100KB input is accepted."""
        max_input = "A" * (100 * 1024)  # Exactly 100KB (102400)

        # Should not raise ValueError
        is_secret, confidence = detect_secret_patterns(max_input)
        assert isinstance(is_secret, bool)
        assert isinstance(confidence, str)

    def test_input_validation_error_message(self):
        """Verify error message is clear and informative."""
        huge_input = "A" * 110000  # Over 100KB

        try:
            detect_secret_patterns(huge_input)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            error_msg = str(e)
            assert "110000" in error_msg  # Actual size
            assert "102400" in error_msg  # Max size (SIZE_100KB)
            assert "ReDoS" in error_msg  # Explains why
