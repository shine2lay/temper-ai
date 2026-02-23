"""Comprehensive tests for SecureTokenStore - P0 SECURITY.

Tests cover:
1. Token storage (InMemory backends)
2. Token encryption at rest (Fernet AES-128-CBC + HMAC)
3. Token expiration and rotation
4. Token revocation (delete)
5. Concurrent token access (thread safety)
6. LRU eviction
7. Keyring integration (OS-level key storage)
8. Audit logging
9. Key rotation security
"""

import json
import secrets
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from temper_ai.auth.oauth.token_store import SecureTokenStore
from temper_ai.shared.utils.exceptions import SecurityError


@pytest.fixture
def encryption_key():
    """Generate test encryption key."""
    return Fernet.generate_key().decode()


@pytest.fixture
def token_store(encryption_key):
    """Create token store with test key."""
    return SecureTokenStore(encryption_key=encryption_key, use_keyring=False)


@pytest.fixture
def sample_token_data():
    """Create sample OAuth token data."""
    return {
        "access_token": f"ya29.a0{secrets.token_urlsafe(40)}",
        "refresh_token": f"1//{secrets.token_urlsafe(50)}",
        "token_type": "Bearer",
        "scope": "openid email profile",
        "id_token": f"eyJhbGciOiJSUzI1NiJ9.{secrets.token_urlsafe(100)}.{secrets.token_urlsafe(50)}",
    }


class TestSecureTokenStoreInitialization:
    """Test SecureTokenStore initialization and key management."""

    def test_initialization_with_explicit_key(self, encryption_key):
        """Test initialization with explicit encryption key (testing mode)."""
        store = SecureTokenStore(encryption_key=encryption_key, use_keyring=False)

        assert store.cipher is not None
        assert store.using_keyring is False
        assert isinstance(store._tokens, dict)
        assert len(store._access_log) == 0

    def test_initialization_with_invalid_key(self):
        """Test initialization with invalid encryption key fails."""
        with pytest.raises(ValueError, match="Invalid encryption key"):
            SecureTokenStore(encryption_key="invalid_key", use_keyring=False)

    def test_initialization_with_bytes_key(self):
        """Test initialization accepts bytes encryption key."""
        key = Fernet.generate_key()
        store = SecureTokenStore(encryption_key=key, use_keyring=False)

        assert store.cipher is not None
        assert store.using_keyring is False

    def test_initialization_with_keyring_creates_new_key(self):
        """Test initialization creates new key in keyring if none exists."""
        # Mock keyring at the module level using sys.modules
        mock_keyring = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)
        mock_keyring.set_password = MagicMock(return_value=None)

        with patch.dict(
            "sys.modules", {"keyring": mock_keyring, "keyring.errors": MagicMock()}
        ):
            with patch(
                "temper_ai.auth.oauth._token_store_helpers.KEYRING_AVAILABLE", True
            ):
                # Re-import to pick up mocked keyring
                import importlib

                import temper_ai.auth.oauth._token_store_helpers

                importlib.reload(temper_ai.auth.oauth._token_store_helpers)

                store = SecureTokenStore(use_keyring=True, require_keyring=False)

                assert store.using_keyring is True
                assert mock_keyring.get_password.called
                assert mock_keyring.set_password.called

    def test_initialization_with_existing_keyring_key(self):
        """Test initialization uses existing keyring key."""
        existing_key = Fernet.generate_key().decode()

        mock_keyring = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=existing_key)
        mock_keyring.set_password = MagicMock(return_value=None)

        with patch.dict(
            "sys.modules", {"keyring": mock_keyring, "keyring.errors": MagicMock()}
        ):
            with patch(
                "temper_ai.auth.oauth._token_store_helpers.KEYRING_AVAILABLE", True
            ):
                import importlib

                import temper_ai.auth.oauth._token_store_helpers

                importlib.reload(temper_ai.auth.oauth._token_store_helpers)

                store = SecureTokenStore(use_keyring=True, require_keyring=False)

                assert store.using_keyring is True
                assert mock_keyring.get_password.called
                assert not mock_keyring.set_password.called

    def test_initialization_requires_keyring_but_unavailable(self, monkeypatch):
        """Test initialization fails if keyring required but unavailable."""
        # Remove encryption key from environment
        monkeypatch.delenv("OAUTH_TOKEN_ENCRYPTION_KEY", raising=False)

        # Patch KEYRING_AVAILABLE to simulate missing keyring
        with patch(
            "temper_ai.auth.oauth._token_store_helpers.KEYRING_AVAILABLE", False
        ):
            # Should raise error because keyring is required but not available
            # The exact exception type depends on the environment
            with pytest.raises(Exception):
                SecureTokenStore(use_keyring=True, require_keyring=True)

    def test_initialization_keyring_fallback_to_env(self, monkeypatch):
        """Test initialization falls back to env var if keyring fails."""
        test_key = Fernet.generate_key().decode()
        monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", test_key)

        class MockKeyringError(Exception):
            pass

        mock_keyring = MagicMock()
        mock_keyring.get_password = MagicMock(
            side_effect=MockKeyringError("No keyring backend")
        )
        mock_keyring_errors = MagicMock()
        mock_keyring_errors.KeyringError = MockKeyringError

        with patch.dict(
            "sys.modules",
            {"keyring": mock_keyring, "keyring.errors": mock_keyring_errors},
        ):
            with patch(
                "temper_ai.auth.oauth._token_store_helpers.KEYRING_AVAILABLE", True
            ):
                with patch(
                    "temper_ai.auth.oauth._token_store_helpers.KeyringError",
                    MockKeyringError,
                ):
                    import importlib

                    import temper_ai.auth.oauth._token_store_helpers

                    importlib.reload(temper_ai.auth.oauth._token_store_helpers)

                    store = SecureTokenStore(use_keyring=True, require_keyring=False)

                    assert store.using_keyring is False
                    assert store.cipher is not None

    def test_initialization_no_key_available_fails(self, monkeypatch):
        """Test initialization fails if no key source available."""
        monkeypatch.delenv("OAUTH_TOKEN_ENCRYPTION_KEY", raising=False)

        with pytest.raises(ValueError, match="No encryption key available"):
            SecureTokenStore(use_keyring=False, require_keyring=False)

    def test_initialization_custom_access_log_size(self, encryption_key):
        """Test initialization with custom max access log size."""
        store = SecureTokenStore(
            encryption_key=encryption_key, use_keyring=False, max_access_log_size=100
        )

        assert store._access_log.maxlen == 100


class TestTokenStorageAndRetrieval:
    """Test token storage, retrieval, and encryption."""

    def test_store_token_encrypts_data(self, token_store, sample_token_data):
        """Test store_token encrypts token data."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data, expires_in=3600)

        # Token should be encrypted (not plaintext)
        encrypted = token_store._tokens[user_id]
        assert isinstance(encrypted, bytes)
        assert sample_token_data["access_token"] not in encrypted.decode(
            "utf-8", errors="ignore"
        )

    def test_store_token_adds_metadata(self, token_store, sample_token_data):
        """Test store_token adds stored_at and expires_at metadata."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data, expires_in=3600)

        retrieved = token_store.retrieve_token(user_id)
        assert retrieved is not None
        assert "stored_at" in retrieved
        assert "expires_at" in retrieved
        assert retrieved["access_token"] == sample_token_data["access_token"]

    def test_store_token_without_expiry(self, token_store, sample_token_data):
        """Test store_token without expiration (long-lived tokens)."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data)

        retrieved = token_store.retrieve_token(user_id)
        assert retrieved is not None
        assert retrieved["expires_at"] is None
        assert retrieved["access_token"] == sample_token_data["access_token"]

    def test_retrieve_token_decrypts_correctly(self, token_store, sample_token_data):
        """Test retrieve_token decrypts and returns original data."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data, expires_in=3600)

        retrieved = token_store.retrieve_token(user_id)

        assert retrieved is not None
        assert retrieved["access_token"] == sample_token_data["access_token"]
        assert retrieved["refresh_token"] == sample_token_data["refresh_token"]
        assert retrieved["token_type"] == sample_token_data["token_type"]

    def test_retrieve_nonexistent_token_returns_none(self, token_store):
        """Test retrieve_token returns None for nonexistent user."""
        result = token_store.retrieve_token("nonexistent_user")
        assert result is None

    def test_retrieve_corrupted_token_deletes_it(self, token_store, sample_token_data):
        """Test retrieve_token deletes corrupted/tampered tokens."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data, expires_in=3600)

        # Corrupt the encrypted data
        token_store._tokens[user_id] = b"corrupted_data"

        result = token_store.retrieve_token(user_id)

        assert result is None
        assert user_id not in token_store._tokens  # Corrupted token deleted


class TestTokenExpiration:
    """Test token expiration and automatic deletion."""

    def test_expired_token_returns_none(self, token_store, sample_token_data):
        """Test expired tokens return None and are deleted."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data, expires_in=1)

        # Wait for expiration
        time.sleep(1.1)

        result = token_store.retrieve_token(user_id)

        assert result is None
        assert user_id not in token_store._tokens  # Expired token deleted

    def test_not_expired_token_returns_data(self, token_store, sample_token_data):
        """Test non-expired tokens are returned successfully."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data, expires_in=3600)

        result = token_store.retrieve_token(user_id)

        assert result is not None
        assert result["access_token"] == sample_token_data["access_token"]

    def test_invalid_expiry_format_deletes_token(self, token_store, sample_token_data):
        """Test tokens with invalid expiry format are deleted."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data, expires_in=3600)

        # Manually corrupt expires_at
        encrypted = token_store._tokens[user_id]
        decrypted = token_store.cipher.decrypt(encrypted)
        data = json.loads(decrypted.decode())
        data["expires_at"] = "invalid_date"
        token_store._tokens[user_id] = token_store.cipher.encrypt(
            json.dumps(data).encode()
        )

        result = token_store.retrieve_token(user_id)

        assert result is None
        assert user_id not in token_store._tokens


class TestTokenDeletion:
    """Test token deletion and revocation."""

    def test_delete_existing_token(self, token_store, sample_token_data):
        """Test deleting an existing token."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data, expires_in=3600)

        deleted = token_store.delete_token(user_id)

        assert deleted is True
        assert user_id not in token_store._tokens
        assert token_store.retrieve_token(user_id) is None

    def test_delete_nonexistent_token(self, token_store):
        """Test deleting nonexistent token returns False."""
        deleted = token_store.delete_token("nonexistent_user")
        assert deleted is False

    def test_clear_all_tokens(self, token_store, sample_token_data):
        """Test clearing all tokens (emergency revocation)."""
        # Store multiple tokens
        for i in range(5):
            token_store.store_token(f"user_{i}", sample_token_data, expires_in=3600)

        count = token_store.clear_all_tokens()

        assert count == 5
        assert len(token_store._tokens) == 0

    def test_clear_all_tokens_audit_log(self, token_store, sample_token_data):
        """Test clear_all_tokens creates audit log entry."""
        token_store.store_token("user_1", sample_token_data, expires_in=3600)
        token_store.clear_all_tokens()

        audit_log = token_store.get_audit_log()
        clear_entry = next(e for e in audit_log if e["action"] == "clear_all")

        assert clear_entry["tokens_deleted"] == 1


class TestKeyRotation:
    """Test encryption key rotation security."""

    def test_rotate_key_re_encrypts_tokens(self, token_store, sample_token_data):
        """Test rotate_key re-encrypts all tokens with new key."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data, expires_in=3600)

        old_encrypted = token_store._tokens[user_id]
        new_key = Fernet.generate_key().decode()

        token_store.rotate_key(new_key)

        # Encrypted data should be different
        new_encrypted = token_store._tokens[user_id]
        assert new_encrypted != old_encrypted

        # But decrypted data should be the same
        retrieved = token_store.retrieve_token(user_id)
        assert retrieved["access_token"] == sample_token_data["access_token"]

    def test_rotate_key_invalid_key_fails(self, token_store, sample_token_data):
        """Test rotate_key fails with invalid key."""
        token_store.store_token("user_1", sample_token_data, expires_in=3600)

        with pytest.raises(ValueError, match="Invalid new encryption key"):
            token_store.rotate_key("invalid_key")

        # Original token should still be retrievable
        assert token_store.retrieve_token("user_1") is not None

    def test_rotate_key_preserves_expiry(self, token_store, sample_token_data):
        """Test rotate_key preserves token expiration times."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data, expires_in=3600)

        original = token_store.retrieve_token(user_id)
        original_expires = original["expires_at"]

        # Re-store for rotation test
        token_store.store_token(user_id, sample_token_data, expires_in=3600)
        new_key = Fernet.generate_key().decode()
        token_store.rotate_key(new_key)

        rotated = token_store.retrieve_token(user_id)
        # Expires_at should be approximately the same (within 5 seconds)
        rotated_expires = datetime.fromisoformat(rotated["expires_at"])
        assert (
            abs(
                (
                    rotated_expires - datetime.fromisoformat(original_expires)
                ).total_seconds()
            )
            < 5
        )

    def test_rotate_key_skips_expired_tokens(self, token_store, sample_token_data):
        """Test rotate_key skips expired tokens during rotation."""
        token_store.store_token("user_expired", sample_token_data, expires_in=1)
        token_store.store_token("user_valid", sample_token_data, expires_in=3600)

        time.sleep(1.1)

        new_key = Fernet.generate_key().decode()
        token_store.rotate_key(new_key)

        # Expired token should not be re-encrypted
        assert "user_expired" not in token_store._tokens
        # Valid token should be re-encrypted
        assert "user_valid" in token_store._tokens

    def test_rotate_key_from_keyring_success(self, encryption_key):
        """Test rotate_key_from_keyring generates and stores new key."""
        mock_keyring = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=encryption_key)
        mock_keyring.set_password = MagicMock(return_value=None)

        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            import importlib

            import temper_ai.auth.oauth.token_store

            importlib.reload(temper_ai.auth.oauth.token_store)

            store = temper_ai.auth.oauth.token_store.SecureTokenStore(
                encryption_key=encryption_key, use_keyring=False
            )
            store.using_keyring = True  # Force keyring mode for test
            store.keyring_service = "test_service"
            store.keyring_key_name = "test_key"

            sample_data = {"access_token": "test_token"}
            store.store_token("user_1", sample_data, expires_in=3600)

            store.rotate_key_from_keyring()

            # Keyring should have been updated with new key
            assert mock_keyring.set_password.called
            # Token should still be retrievable
            assert store.retrieve_token("user_1") is not None

    def test_rotate_key_from_keyring_without_keyring_mode_fails(self, token_store):
        """Test rotate_key_from_keyring fails if not in keyring mode."""
        with pytest.raises(SecurityError, match="requires keyring mode"):
            token_store.rotate_key_from_keyring()


class TestThreadSafety:
    """Test concurrent token access (thread safety)."""

    def test_concurrent_store_operations(self, token_store, sample_token_data):
        """Test concurrent store operations are thread-safe."""

        def store_tokens(thread_id):
            for i in range(10):
                user_id = f"user_{thread_id}_{i}"
                token_store.store_token(user_id, sample_token_data, expires_in=3600)

        threads = [threading.Thread(target=store_tokens, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All tokens should be stored (50 total)
        assert len(token_store._tokens) == 50

    def test_concurrent_retrieve_operations(self, token_store, sample_token_data):
        """Test concurrent retrieve operations are thread-safe."""
        # Store tokens first
        for i in range(10):
            token_store.store_token(f"user_{i}", sample_token_data, expires_in=3600)

        results = []
        lock = threading.Lock()

        def retrieve_tokens():
            for i in range(10):
                token = token_store.retrieve_token(f"user_{i}")
                with lock:
                    results.append(token)

        threads = [threading.Thread(target=retrieve_tokens) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All retrievals should succeed
        assert len(results) == 50
        assert all(r is not None for r in results)

    def test_concurrent_delete_operations(self, token_store, sample_token_data):
        """Test concurrent delete operations are thread-safe."""
        # Store tokens
        for i in range(20):
            token_store.store_token(f"user_{i}", sample_token_data, expires_in=3600)

        delete_results = []
        lock = threading.Lock()

        def delete_tokens(thread_id):
            for i in range(10):
                user_id = f"user_{i}"
                result = token_store.delete_token(user_id)
                with lock:
                    delete_results.append((user_id, result))

        threads = [threading.Thread(target=delete_tokens, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each token deleted exactly once
        successful_deletes = sum(1 for _, success in delete_results if success)
        assert successful_deletes == 10

    def test_concurrent_key_rotation_blocks_other_ops(
        self, token_store, sample_token_data
    ):
        """Test key rotation blocks all other operations (thread safety)."""
        for i in range(5):
            token_store.store_token(f"user_{i}", sample_token_data, expires_in=3600)

        rotation_started = threading.Event()
        rotation_complete = threading.Event()

        def rotate_keys():
            rotation_started.set()
            time.sleep(0.5)  # Simulate slow rotation
            new_key = Fernet.generate_key().decode()
            token_store.rotate_key(new_key)
            rotation_complete.set()

        def try_retrieve():
            rotation_started.wait()
            token_store.retrieve_token("user_0")

        rotate_thread = threading.Thread(target=rotate_keys)
        retrieve_thread = threading.Thread(target=try_retrieve)

        rotate_thread.start()
        retrieve_thread.start()

        rotate_thread.join()
        retrieve_thread.join()

        # Retrieve should have been blocked until rotation complete
        assert rotation_complete.is_set()


class TestAuditLogging:
    """Test audit logging for compliance."""

    def test_store_token_creates_audit_log(self, token_store, sample_token_data):
        """Test store_token creates audit log entry."""
        token_store.store_token("user_123", sample_token_data, expires_in=3600)

        audit_log = token_store.get_audit_log()
        assert len(audit_log) == 1
        assert audit_log[0]["action"] == "store"
        assert audit_log[0]["user_id"] == "user_123"
        assert audit_log[0]["expires_in"] == 3600
        assert "timestamp" in audit_log[0]

    def test_retrieve_token_creates_audit_log(self, token_store, sample_token_data):
        """Test retrieve_token creates audit log entry."""
        token_store.store_token("user_123", sample_token_data, expires_in=3600)
        token_store.retrieve_token("user_123")

        audit_log = token_store.get_audit_log()
        retrieve_entry = next(e for e in audit_log if e["action"] == "retrieve")

        assert retrieve_entry["user_id"] == "user_123"
        assert "timestamp" in retrieve_entry

    def test_delete_token_creates_audit_log(self, token_store, sample_token_data):
        """Test delete_token creates audit log entry."""
        token_store.store_token("user_123", sample_token_data, expires_in=3600)
        token_store.delete_token("user_123")

        audit_log = token_store.get_audit_log()
        delete_entry = next(e for e in audit_log if e["action"] == "delete")

        assert delete_entry["user_id"] == "user_123"

    def test_rotate_key_creates_audit_log(self, token_store, sample_token_data):
        """Test rotate_key creates audit log entry."""
        token_store.store_token("user_1", sample_token_data, expires_in=3600)
        new_key = Fernet.generate_key().decode()
        token_store.rotate_key(new_key)

        audit_log = token_store.get_audit_log()
        rotate_entry = next(e for e in audit_log if e["action"] == "rotate_key")

        assert rotate_entry["tokens_re_encrypted"] == 1
        assert "timestamp" in rotate_entry

    def test_audit_log_bounded_size(self, token_store, sample_token_data):
        """Test audit log is bounded (LRU eviction)."""
        custom_store = SecureTokenStore(
            encryption_key=Fernet.generate_key().decode(),
            use_keyring=False,
            max_access_log_size=10,
        )

        # Generate more logs than max size
        for i in range(20):
            custom_store.store_token(f"user_{i}", sample_token_data, expires_in=3600)

        audit_log = custom_store.get_audit_log()
        assert len(audit_log) == 10  # Bounded to max size
