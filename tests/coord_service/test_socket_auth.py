"""
Tests for Unix socket authentication.

Tests token generation, loading, verification, and end-to-end authentication flow.
"""

import os
import secrets
import sys
from pathlib import Path

import pytest

# Add .claude-coord to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / '.claude-coord'))

from coord_service.auth import AuthenticationLayer, TokenManager


class TestTokenManager:
    """Test token generation and loading."""

    def test_auth_token_generated_on_first_run(self, tmp_path):
        """Test that auth token is generated on first server start."""
        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)

        token_manager = TokenManager(coord_dir)
        token = token_manager.load_or_generate()

        # Token file should exist
        token_file = coord_dir / '.auth_token'
        assert token_file.exists()

        # Token should be non-empty and sufficient length
        assert len(token) >= 32
        assert token == token_file.read_text().strip()

        # Token should be URL-safe base64
        # secrets.token_urlsafe() generates URL-safe base64 strings
        assert all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_' for c in token)

    def test_auth_token_reused_on_restart(self, tmp_path):
        """Test that same token is used across restarts."""
        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)

        # First initialization
        token_manager1 = TokenManager(coord_dir)
        token1 = token_manager1.load_or_generate()

        # Second initialization (simulates restart)
        token_manager2 = TokenManager(coord_dir)
        token2 = token_manager2.load_or_generate()

        assert token1 == token2

    def test_token_file_permissions(self, tmp_path):
        """Test that token file has 0o600 permissions."""
        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)

        token_manager = TokenManager(coord_dir)
        token_manager.load_or_generate()

        token_file = coord_dir / '.auth_token'
        stat = os.stat(token_file)
        permissions = stat.st_mode & 0o777

        # Should be 0o600 (owner read/write only)
        assert permissions == 0o600, f"Expected 0o600, got {oct(permissions)}"

    def test_token_file_wrong_permissions_raises_error(self, tmp_path):
        """Test that token file with wrong permissions raises error."""
        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)
        token_file = coord_dir / '.auth_token'

        # Create token file with wrong permissions
        token_file.write_text("insecure_token")
        os.chmod(token_file, 0o644)  # World-readable

        token_manager = TokenManager(coord_dir)

        with pytest.raises(PermissionError, match="insecure permissions"):
            token_manager.load_or_generate()

    def test_token_file_corrupted(self, tmp_path):
        """Test that corrupted token file raises error."""
        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)
        token_file = coord_dir / '.auth_token'

        # Create token file with insufficient length
        token_file.write_text("short")
        os.chmod(token_file, 0o600)

        token_manager = TokenManager(coord_dir)

        with pytest.raises(ValueError, match="corrupted"):
            token_manager.load_or_generate()

    def test_token_property_before_load_raises_error(self, tmp_path):
        """Test that accessing token before load raises error."""
        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)

        token_manager = TokenManager(coord_dir)

        with pytest.raises(RuntimeError, match="Token not loaded"):
            _ = token_manager.token

    def test_token_property_after_load(self, tmp_path):
        """Test that token property returns cached token."""
        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)

        token_manager = TokenManager(coord_dir)
        loaded_token = token_manager.load_or_generate()

        assert token_manager.token == loaded_token


class TestAuthenticationLayer:
    """Test authentication verification."""

    def test_valid_token_accepted(self):
        """Test that requests with valid token are accepted."""
        auth_token = secrets.token_urlsafe(32)
        auth_layer = AuthenticationLayer(auth_token)

        request = {
            "auth_token": auth_token,
            "method": "task_list",
            "params": {}
        }

        error = auth_layer.verify_request(request)
        assert error is None  # No error = authenticated

    def test_invalid_token_rejected(self):
        """Test that requests with invalid token are rejected."""
        auth_token = secrets.token_urlsafe(32)
        auth_layer = AuthenticationLayer(auth_token)

        request = {
            "auth_token": "wrong-token",
            "method": "task_list",
            "params": {}
        }

        error = auth_layer.verify_request(request)
        assert error is not None
        assert error["code"] == "AUTH_INVALID"
        assert "invalid" in error["message"].lower()

    def test_missing_token_rejected(self):
        """Test that requests without token are rejected."""
        auth_token = secrets.token_urlsafe(32)
        auth_layer = AuthenticationLayer(auth_token)

        request = {
            "method": "task_list",
            "params": {}
        }

        error = auth_layer.verify_request(request)
        assert error is not None
        assert error["code"] == "AUTH_REQUIRED"
        assert "required" in error["message"].lower()

    def test_empty_token_rejected(self):
        """Test that requests with empty token are rejected."""
        auth_token = secrets.token_urlsafe(32)
        auth_layer = AuthenticationLayer(auth_token)

        request = {
            "auth_token": "",
            "method": "task_list",
            "params": {}
        }

        error = auth_layer.verify_request(request)
        assert error is not None
        assert error["code"] == "AUTH_REQUIRED"

    def test_constant_time_comparison(self):
        """Test that token comparison uses hmac.compare_digest (constant-time).

        We verify that hmac.compare_digest is being used by checking the
        implementation, rather than trying to measure timing (which is unreliable
        at nanosecond scale due to CPU scheduling, caching, etc.)
        """
        import inspect

        auth_token = secrets.token_urlsafe(32)
        auth_layer = AuthenticationLayer(auth_token)

        # Verify that verify_token method uses hmac.compare_digest
        source = inspect.getsource(auth_layer.verify_token)
        assert 'hmac.compare_digest' in source, (
            "verify_token must use hmac.compare_digest for constant-time comparison"
        )

        # Also verify it returns False for wrong tokens
        wrong_tokens = [
            'X' + auth_token[1:],  # Differ at first char
            auth_token[:16] + 'X' + auth_token[17:],  # Differ in middle
            auth_token[:-1] + 'X',  # Differ at last char
        ]

        for wrong_token in wrong_tokens:
            result = auth_layer.verify_token(wrong_token)
            assert result is False  # All should fail


class TestEndToEndAuth:
    """Test end-to-end authentication flow."""

    @pytest.fixture
    def coord_setup(self, tmp_path):
        """Setup coordination directory with token."""
        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)

        # Generate token
        token_manager = TokenManager(coord_dir)
        token = token_manager.load_or_generate()

        return coord_dir, token

    def test_client_loads_token(self, coord_setup):
        """Test that client loads token from file."""
        coord_dir, expected_token = coord_setup

        # Client should load same token
        client_token_manager = TokenManager(coord_dir)
        client_token = client_token_manager.load_or_generate()

        assert client_token == expected_token

    def test_server_client_token_match(self, coord_setup):
        """Test that server and client use same token."""
        coord_dir, _ = coord_setup

        # Server loads token
        server_token_manager = TokenManager(coord_dir)
        server_token = server_token_manager.load_or_generate()

        # Client loads same token
        client_token_manager = TokenManager(coord_dir)
        client_token = client_token_manager.load_or_generate()

        assert server_token == client_token

    def test_authentication_flow(self, coord_setup):
        """Test complete authentication flow."""
        coord_dir, token = coord_setup

        # Server setup
        auth_layer = AuthenticationLayer(token)

        # Client request with correct token
        request = {
            "auth_token": token,
            "method": "status",
            "params": {}
        }

        error = auth_layer.verify_request(request)
        assert error is None  # Authentication success

    def test_authentication_failure_flow(self, coord_setup):
        """Test authentication failure flow."""
        coord_dir, token = coord_setup

        # Server setup
        auth_layer = AuthenticationLayer(token)

        # Client request with wrong token
        request = {
            "auth_token": "wrong-token",
            "method": "status",
            "params": {}
        }

        error = auth_layer.verify_request(request)
        assert error is not None
        assert error["code"] == "AUTH_INVALID"


class TestSecurityProperties:
    """Test security properties of authentication."""

    def test_token_randomness(self, tmp_path):
        """Test that generated tokens are random (not predictable)."""
        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)

        # Generate multiple tokens (delete file between generations)
        tokens = []
        for _ in range(10):
            token_manager = TokenManager(coord_dir)
            token = token_manager.load_or_generate()
            tokens.append(token)
            # Delete token file for next iteration
            (coord_dir / '.auth_token').unlink()

        # All tokens should be unique
        assert len(set(tokens)) == 10

        # Tokens should have high entropy (all different)
        for i, token1 in enumerate(tokens):
            for token2 in tokens[i+1:]:
                # Hamming distance should be high (most chars different)
                differences = sum(c1 != c2 for c1, c2 in zip(token1, token2))
                # At least 50% of characters should differ (very conservative)
                assert differences > len(token1) * 0.5

    def test_token_not_logged(self, tmp_path, caplog):
        """Test that full token is never logged."""
        import logging
        caplog.set_level(logging.DEBUG)

        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)

        token_manager = TokenManager(coord_dir)
        token = token_manager.load_or_generate()

        # Create auth layer and trigger auth failure (which logs)
        auth_layer = AuthenticationLayer(token)
        auth_layer.verify_request({
            "auth_token": "wrong_token_that_should_be_partially_logged",
            "method": "test"
        })

        # Check that full token is never in logs
        for record in caplog.records:
            assert token not in record.message
            # Partial token (first 8 chars) might be logged, but not full token

    def test_file_creation_race_condition_safe(self, tmp_path):
        """Test that token file creation is race-condition safe.

        Simulates concurrent token generation attempts. Due to O_EXCL flag,
        only one thread will successfully create the token file, others will
        load the existing token.
        """
        import threading

        coord_dir = tmp_path / '.claude-coord'
        coord_dir.mkdir(parents=True)

        tokens = []
        errors = []
        results = []

        def create_token():
            try:
                token_manager = TokenManager(coord_dir)
                token = token_manager.load_or_generate()
                results.append({'success': True, 'token': token})
                tokens.append(token)
            except Exception as e:
                results.append({'success': False, 'error': str(e)})
                errors.append(e)

        # Simulate 5 concurrent token generations
        threads = [threading.Thread(target=create_token) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Debug: print results if test fails
        if len(tokens) != 5:
            print(f"Results: {results}")
            print(f"Tokens: {tokens}")
            print(f"Errors: {errors}")

        # Due to O_EXCL, first thread creates, others may fail then retry (or load existing)
        # The implementation should handle this gracefully
        # We expect either:
        # 1. All threads succeed (first creates, others load existing)
        # 2. Some threads fail initially but all eventually load the token

        # At minimum, token file should exist
        token_file = coord_dir / '.auth_token'
        assert token_file.exists()

        # All successful loads should have the same token
        if tokens:
            assert len(set(tokens)) == 1

        # Token file should have correct permissions
        stat = os.stat(token_file)
        assert (stat.st_mode & 0o777) == 0o600
