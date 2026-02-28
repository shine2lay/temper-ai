"""Tests for temper_ai/safety/redaction_utils.py."""

import os

from temper_ai.safety.redaction_utils import (
    HASH_PREFIX_LENGTH,
    create_redacted_preview,
    hash_secret,
)


class TestCreateRedactedPreview:
    def test_basic_redaction(self):
        result = create_redacted_preview("AKIAIOSFODNN7EXAMPLE", "aws_access_key")
        assert result == "[AWS_ACCESS_KEY:20_chars]"

    def test_pattern_name_uppercased(self):
        result = create_redacted_preview("sk-proj-abc123def456", "openai_key")
        assert result == "[OPENAI_KEY:20_chars]"

    def test_length_correct(self):
        text = "short"
        result = create_redacted_preview(text, "some_pattern")
        assert f":{len(text)}_chars]" in result

    def test_empty_text(self):
        result = create_redacted_preview("", "pattern")
        assert result == "[PATTERN:0_chars]"


class TestHashSecret:
    def test_deterministic(self):
        key = os.urandom(32)
        h1 = hash_secret("AKIAIOSFODNN7EXAMPLE", key)
        h2 = hash_secret("AKIAIOSFODNN7EXAMPLE", key)
        assert h1 == h2

    def test_different_text_different_hash(self):
        key = os.urandom(32)
        h1 = hash_secret("secret_one", key)
        h2 = hash_secret("secret_two", key)
        assert h1 != h2

    def test_hash_length(self):
        key = os.urandom(32)
        h = hash_secret("any secret value", key)
        assert len(h) == HASH_PREFIX_LENGTH

    def test_different_key_different_hash(self):
        text = "same_secret_value"
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        h1 = hash_secret(text, key1)
        h2 = hash_secret(text, key2)
        assert h1 != h2
