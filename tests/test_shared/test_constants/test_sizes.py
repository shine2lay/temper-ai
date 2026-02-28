"""Tests for temper_ai/shared/constants/sizes.py."""

from temper_ai.shared.constants.sizes import (
    BYTES_PER_GB,
    BYTES_PER_KB,
    BYTES_PER_MB,
    BYTES_PER_TB,
    SIZE_1GB,
    SIZE_1KB,
    SIZE_1MB,
    SIZE_4KB,
    SIZE_10KB,
    SIZE_10MB,
    SIZE_100KB,
    SIZE_100MB,
    TOKEN_BYTES_NONCE,
    TOKEN_BYTES_SESSION,
    TOKEN_BYTES_STATE,
    UUID_HEX_SHORT_LENGTH,
)


class TestByteConversions:
    def test_kb(self):
        assert BYTES_PER_KB == 1024

    def test_mb(self):
        assert BYTES_PER_MB == BYTES_PER_KB * 1024

    def test_gb(self):
        assert BYTES_PER_GB == BYTES_PER_MB * 1024

    def test_tb(self):
        assert BYTES_PER_TB == BYTES_PER_GB * 1024


class TestCommonSizes:
    def test_sizes_are_powers_of_two_base(self):
        assert SIZE_1KB == BYTES_PER_KB
        assert SIZE_1MB == BYTES_PER_MB
        assert SIZE_1GB == BYTES_PER_GB

    def test_size_ordering(self):
        sizes = [
            SIZE_1KB,
            SIZE_4KB,
            SIZE_10KB,
            SIZE_100KB,
            SIZE_1MB,
            SIZE_10MB,
            SIZE_100MB,
            SIZE_1GB,
        ]
        assert sizes == sorted(sizes)

    def test_4kb_page_size(self):
        assert SIZE_4KB == 4096


class TestTokenSizes:
    def test_session_token_size(self):
        assert TOKEN_BYTES_SESSION == 32

    def test_state_token_size(self):
        assert TOKEN_BYTES_STATE == 32

    def test_nonce_size(self):
        assert TOKEN_BYTES_NONCE == 64

    def test_nonce_larger_than_session(self):
        assert TOKEN_BYTES_NONCE > TOKEN_BYTES_SESSION


class TestIDLengths:
    def test_uuid_hex_short(self):
        assert UUID_HEX_SHORT_LENGTH == 12
        assert UUID_HEX_SHORT_LENGTH > 0
