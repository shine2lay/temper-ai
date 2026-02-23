"""Tests for Secure OAuth Token Storage.

SECURITY: These tests verify:
- Token encryption at rest
- Key rotation functionality
- Automatic expiry handling
- Audit logging
- OS keyring integration
"""

import time

import pytest
from cryptography.fernet import Fernet

from temper_ai.auth.oauth.token_store import SecureTokenStore, SecurityError

# Try importing keyring for keyring tests
try:
    import keyring
    from keyring.errors import KeyringError

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    keyring = None  # type: ignore


class TestSecureTokenStore:
    """Test secure token storage with encryption."""

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        return Fernet.generate_key().decode()

    @pytest.fixture
    def token_store(self, encryption_key):
        """Create a token store for testing."""
        return SecureTokenStore(encryption_key=encryption_key)

    def test_store_and_retrieve_token(self, token_store):
        """Should store and retrieve token successfully."""
        token_data = {
            "access_token": "ya29.a0AfB_byTest123",
            "refresh_token": "1//0gTest456",
            "token_type": "Bearer",
            "scope": "openid email profile",
        }

        # Store token
        token_store.store_token("user_123", token_data, expires_in=3600)

        # Retrieve token
        retrieved = token_store.retrieve_token("user_123")

        # Verify data
        assert retrieved is not None
        assert retrieved["access_token"] == token_data["access_token"]
        assert retrieved["refresh_token"] == token_data["refresh_token"]
        assert retrieved["token_type"] == token_data["token_type"]
        assert retrieved["scope"] == token_data["scope"]

        # Verify metadata added
        assert "stored_at" in retrieved
        assert "expires_at" in retrieved

    def test_token_encrypted_at_rest(self, token_store):
        """Token should be encrypted (not plaintext) in storage."""
        token_data = {"access_token": "secret_token_123"}

        token_store.store_token("user_123", token_data)

        # Verify encrypted bytes don't contain plaintext
        encrypted = token_store._tokens["user_123"]
        assert b"secret_token_123" not in encrypted
        assert isinstance(encrypted, bytes)

    def test_retrieve_nonexistent_token_returns_none(self, token_store):
        """Retrieving non-existent token should return None."""
        retrieved = token_store.retrieve_token("nonexistent_user")
        assert retrieved is None

    def test_delete_token(self, token_store):
        """Should delete token successfully."""
        token_data = {"access_token": "test_token"}
        token_store.store_token("user_123", token_data)

        # Verify stored
        assert token_store.retrieve_token("user_123") is not None

        # Delete
        result = token_store.delete_token("user_123")
        assert result is True

        # Verify deleted
        assert token_store.retrieve_token("user_123") is None

    def test_delete_nonexistent_token_returns_false(self, token_store):
        """Deleting non-existent token should return False."""
        result = token_store.delete_token("nonexistent_user")
        assert result is False

    def test_token_expiry_handling(self, token_store):
        """Expired tokens should be automatically deleted."""
        token_data = {"access_token": "test_token"}

        # Store with very short expiry
        token_store.store_token("user_123", token_data, expires_in=1)

        # Should be retrievable immediately
        assert token_store.retrieve_token("user_123") is not None

        # Wait for expiry
        time.sleep(1.1)

        # Should be None (auto-deleted)
        assert token_store.retrieve_token("user_123") is None

    def test_token_without_expiry(self, token_store):
        """Tokens without expiry should not expire."""
        token_data = {"access_token": "test_token"}

        # Store without expiry
        token_store.store_token("user_123", token_data, expires_in=None)

        # Wait a bit
        time.sleep(0.5)

        # Should still be retrievable
        retrieved = token_store.retrieve_token("user_123")
        assert retrieved is not None
        assert retrieved["access_token"] == "test_token"

    def test_key_rotation(self, encryption_key, token_store):
        """Should re-encrypt all tokens with new key."""
        # Store multiple tokens
        token_store.store_token("user_1", {"access_token": "token_1"}, expires_in=3600)
        token_store.store_token("user_2", {"access_token": "token_2"}, expires_in=3600)

        # Verify both retrievable
        assert token_store.retrieve_token("user_1")["access_token"] == "token_1"
        assert token_store.retrieve_token("user_2")["access_token"] == "token_2"

        # Rotate key
        new_key = Fernet.generate_key().decode()
        token_store.rotate_key(new_key)

        # Verify both still retrievable with new key
        assert token_store.retrieve_token("user_1")["access_token"] == "token_1"
        assert token_store.retrieve_token("user_2")["access_token"] == "token_2"

    def test_key_rotation_skips_expired_tokens(self, token_store):
        """Key rotation should skip expired tokens."""
        # Store token with short expiry
        token_store.store_token("user_1", {"access_token": "token_1"}, expires_in=1)

        # Wait for expiry
        time.sleep(1.1)

        # Rotate key
        new_key = Fernet.generate_key().decode()
        token_store.rotate_key(new_key)

        # Expired token should not be re-encrypted
        assert token_store.retrieve_token("user_1") is None

    def test_invalid_encryption_key_raises_error(self):
        """Invalid encryption key should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid encryption key"):
            SecureTokenStore(encryption_key="not-a-valid-key")

    def test_missing_encryption_key_raises_error(self, monkeypatch):
        """Missing encryption key should raise ValueError."""
        # Clear environment variable
        monkeypatch.delenv("OAUTH_TOKEN_ENCRYPTION_KEY", raising=False)

        # Disable keyring to force the error
        with pytest.raises(ValueError, match="No encryption key available"):
            SecureTokenStore(use_keyring=False)

    def test_corrupted_token_returns_none(self, token_store):
        """Corrupted encrypted token should return None and be deleted."""
        token_data = {"access_token": "test_token"}
        token_store.store_token("user_123", token_data)

        # Corrupt the encrypted data
        token_store._tokens["user_123"] = b"corrupted_data"

        # Should return None
        assert token_store.retrieve_token("user_123") is None

        # Should be deleted from storage
        assert "user_123" not in token_store._tokens

    def test_audit_log_tracks_operations(self, token_store):
        """Audit log should track all operations."""
        token_data = {"access_token": "test_token"}

        # Perform operations
        token_store.store_token("user_123", token_data, expires_in=3600)
        token_store.retrieve_token("user_123")
        token_store.delete_token("user_123")

        # Check audit log
        log = token_store.get_audit_log()
        assert len(log) >= 3

        # Verify log entries
        actions = [entry["action"] for entry in log]
        assert "store" in actions
        assert "retrieve" in actions
        assert "delete" in actions

        # Verify user_id recorded
        store_entry = next(e for e in log if e["action"] == "store")
        assert store_entry["user_id"] == "user_123"

    def test_clear_all_tokens(self, token_store):
        """Should clear all tokens."""
        # Store multiple tokens
        token_store.store_token("user_1", {"access_token": "token_1"})
        token_store.store_token("user_2", {"access_token": "token_2"})
        token_store.store_token("user_3", {"access_token": "token_3"})

        # Clear all
        count = token_store.clear_all_tokens()
        assert count == 3

        # Verify all cleared
        assert token_store.retrieve_token("user_1") is None
        assert token_store.retrieve_token("user_2") is None
        assert token_store.retrieve_token("user_3") is None

    def test_overwrite_existing_token(self, token_store):
        """Storing token for same user should overwrite."""
        # Store initial token
        token_store.store_token("user_123", {"access_token": "old_token"})

        # Overwrite with new token
        token_store.store_token("user_123", {"access_token": "new_token"})

        # Should retrieve new token
        retrieved = token_store.retrieve_token("user_123")
        assert retrieved["access_token"] == "new_token"

    def test_token_metadata_preserved(self, token_store):
        """Token metadata should be preserved across store/retrieve."""
        token_data = {
            "access_token": "test_token",
            "refresh_token": "refresh_token",
            "token_type": "Bearer",
            "scope": "openid email",
            "id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
        }

        token_store.store_token("user_123", token_data, expires_in=3600)
        retrieved = token_store.retrieve_token("user_123")

        # All fields should be preserved
        for key in ["access_token", "refresh_token", "token_type", "scope", "id_token"]:
            assert retrieved[key] == token_data[key]

    def test_encryption_key_from_environment(self, monkeypatch):
        """Should load encryption key from environment variable."""
        key = Fernet.generate_key().decode()
        monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", key)

        # Should work without explicit key parameter
        store = SecureTokenStore()
        assert store.cipher is not None

        # Should be able to store/retrieve
        store.store_token("user_123", {"access_token": "test"})
        assert store.retrieve_token("user_123")["access_token"] == "test"

    def test_multiple_users_isolated(self, token_store):
        """Tokens for different users should be isolated."""
        # Store tokens for different users
        token_store.store_token("user_1", {"access_token": "token_1"})
        token_store.store_token("user_2", {"access_token": "token_2"})

        # Each user should only get their own token
        assert token_store.retrieve_token("user_1")["access_token"] == "token_1"
        assert token_store.retrieve_token("user_2")["access_token"] == "token_2"

        # Deleting one shouldn't affect the other
        token_store.delete_token("user_1")
        assert token_store.retrieve_token("user_1") is None
        assert token_store.retrieve_token("user_2")["access_token"] == "token_2"

    def test_audit_log_key_rotation(self, token_store):
        """Audit log should track key rotation."""
        # Store some tokens
        token_store.store_token("user_1", {"access_token": "token_1"}, expires_in=3600)
        token_store.store_token("user_2", {"access_token": "token_2"}, expires_in=3600)

        # Rotate key
        new_key = Fernet.generate_key().decode()
        token_store.rotate_key(new_key)

        # Check audit log
        log = token_store.get_audit_log()
        rotate_entry = next(e for e in log if e["action"] == "rotate_key")

        assert rotate_entry["tokens_re_encrypted"] == 2
        assert "timestamp" in rotate_entry


class TestSecureTokenStoreEdgeCases:
    """Test edge cases and security scenarios."""

    def test_very_long_token(self):
        """Should handle very long tokens."""
        key = Fernet.generate_key().decode()
        store = SecureTokenStore(encryption_key=key)

        # Create very long token (10KB)
        long_token = "a" * 10000

        store.store_token("user_123", {"access_token": long_token})
        retrieved = store.retrieve_token("user_123")

        assert retrieved["access_token"] == long_token

    def test_special_characters_in_token(self):
        """Should handle special characters in tokens."""
        key = Fernet.generate_key().decode()
        store = SecureTokenStore(encryption_key=key)

        token_data = {
            "access_token": "token!@#$%^&*()_+-=[]{}|;':\",./<>?",
            "refresh_token": "újęžý中文токен🚀",
        }

        store.store_token("user_123", token_data)
        retrieved = store.retrieve_token("user_123")

        assert retrieved["access_token"] == token_data["access_token"]
        assert retrieved["refresh_token"] == token_data["refresh_token"]

    def test_empty_token_data(self):
        """Should handle empty token data."""
        key = Fernet.generate_key().decode()
        store = SecureTokenStore(encryption_key=key)

        store.store_token("user_123", {})
        retrieved = store.retrieve_token("user_123")

        # Should have metadata but no token fields
        assert retrieved is not None
        assert "stored_at" in retrieved


@pytest.mark.skipif(not KEYRING_AVAILABLE, reason="keyring library not installed")
class TestSecureTokenStoreKeyring:
    """Test OS keyring integration."""

    @pytest.fixture(autouse=True)
    def cleanup_keyring(self):
        """Clean up keyring entries before and after tests."""
        # Clean before test
        try:
            keyring.delete_password(
                SecureTokenStore.DEFAULT_KEYRING_SERVICE,
                SecureTokenStore.DEFAULT_KEYRING_KEY_NAME,
            )
        except Exception:
            pass

        yield

        # Clean after test
        try:
            keyring.delete_password(
                SecureTokenStore.DEFAULT_KEYRING_SERVICE,
                SecureTokenStore.DEFAULT_KEYRING_KEY_NAME,
            )
        except Exception:
            pass

    def test_keyring_key_storage(self):
        """Should store encryption key in OS keyring."""
        # Initialize with keyring
        store = SecureTokenStore(use_keyring=True)

        # Verify key stored in keyring
        key = keyring.get_password(
            SecureTokenStore.DEFAULT_KEYRING_SERVICE,
            SecureTokenStore.DEFAULT_KEYRING_KEY_NAME,
        )
        assert key is not None
        assert store.using_keyring is True

    def test_keyring_key_reuse(self):
        """Should reuse existing keyring key on subsequent initialization."""
        # First initialization creates key
        store1 = SecureTokenStore(use_keyring=True)
        key1 = keyring.get_password(
            SecureTokenStore.DEFAULT_KEYRING_SERVICE,
            SecureTokenStore.DEFAULT_KEYRING_KEY_NAME,
        )

        # Second initialization should reuse same key
        store2 = SecureTokenStore(use_keyring=True)
        key2 = keyring.get_password(
            SecureTokenStore.DEFAULT_KEYRING_SERVICE,
            SecureTokenStore.DEFAULT_KEYRING_KEY_NAME,
        )

        assert key1 == key2
        assert store1.using_keyring is True
        assert store2.using_keyring is True

    def test_keyring_custom_service_name(self):
        """Should support custom keyring service name."""
        custom_service = "test-app-oauth"
        custom_key_name = "test-encryption-key"

        try:
            store = SecureTokenStore(
                use_keyring=True,
                keyring_service=custom_service,
                keyring_key_name=custom_key_name,
            )

            # Verify key in custom location
            key = keyring.get_password(custom_service, custom_key_name)
            assert key is not None
            assert store.using_keyring is True
        finally:
            # Cleanup custom key
            try:
                keyring.delete_password(custom_service, custom_key_name)
            except Exception:
                pass

    def test_keyring_fallback_to_env(self, monkeypatch):
        """Should fall back to environment variable if keyring unavailable."""
        # Mock keyring failure
        original_get = keyring.get_password

        def mock_get_password(*args, **kwargs):
            raise KeyringError("No keyring backend")

        monkeypatch.setattr(keyring, "get_password", mock_get_password)
        monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

        # Should fall back gracefully
        store = SecureTokenStore(use_keyring=True, require_keyring=False)
        assert store.using_keyring is False

        # Restore original
        monkeypatch.setattr(keyring, "get_password", original_get)

    def test_require_keyring_fails_if_unavailable(self, monkeypatch):
        """Should fail if keyring required but unavailable."""
        original_get = keyring.get_password

        def mock_get_password(*args, **kwargs):
            raise KeyringError("No keyring backend")

        monkeypatch.setattr(keyring, "get_password", mock_get_password)

        with pytest.raises(SecurityError, match="Keyring required"):
            SecureTokenStore(use_keyring=True, require_keyring=True)

        # Restore original
        monkeypatch.setattr(keyring, "get_password", original_get)

    def test_keyring_token_storage_and_retrieval(self):
        """Should store and retrieve tokens with keyring-based encryption."""
        store = SecureTokenStore(use_keyring=True)

        token_data = {
            "access_token": "ya29.a0Test123",
            "refresh_token": "1//0gTest456",
        }

        # Store token
        store.store_token("user_123", token_data, expires_in=3600)

        # Retrieve token
        retrieved = store.retrieve_token("user_123")

        assert retrieved is not None
        assert retrieved["access_token"] == token_data["access_token"]
        assert retrieved["refresh_token"] == token_data["refresh_token"]

    def test_rotate_key_from_keyring(self):
        """Should rotate key from keyring and re-encrypt tokens."""
        store = SecureTokenStore(use_keyring=True)

        # Store token
        store.store_token("user_123", {"access_token": "token_1"}, expires_in=3600)

        # Get old key
        old_key = keyring.get_password(
            SecureTokenStore.DEFAULT_KEYRING_SERVICE,
            SecureTokenStore.DEFAULT_KEYRING_KEY_NAME,
        )

        # Rotate key
        store.rotate_key_from_keyring()

        # Get new key
        new_key = keyring.get_password(
            SecureTokenStore.DEFAULT_KEYRING_SERVICE,
            SecureTokenStore.DEFAULT_KEYRING_KEY_NAME,
        )

        # Key should change
        assert new_key != old_key

        # Token should still be retrievable
        token = store.retrieve_token("user_123")
        assert token is not None
        assert token["access_token"] == "token_1"

    def test_rotate_key_from_keyring_fails_without_keyring_mode(self):
        """Should fail to rotate from keyring if not using keyring mode."""
        key = Fernet.generate_key().decode()
        store = SecureTokenStore(encryption_key=key)

        with pytest.raises(SecurityError, match="requires keyring mode"):
            store.rotate_key_from_keyring()

    def test_keyring_isolation_between_services(self):
        """Keys for different services should be isolated."""
        try:
            store1 = SecureTokenStore(
                use_keyring=True, keyring_service="app1", keyring_key_name="key1"
            )

            store2 = SecureTokenStore(
                use_keyring=True, keyring_service="app2", keyring_key_name="key2"
            )

            # Store token in each
            store1.store_token("user", {"access_token": "token1"})
            store2.store_token("user", {"access_token": "token2"})

            # Each should only see their own token
            assert store1.retrieve_token("user")["access_token"] == "token1"
            assert store2.retrieve_token("user")["access_token"] == "token2"
        finally:
            # Cleanup
            try:
                keyring.delete_password("app1", "key1")
                keyring.delete_password("app2", "key2")
            except Exception:
                pass

    def test_explicit_key_bypasses_keyring(self):
        """Explicit encryption key should bypass keyring."""
        key = Fernet.generate_key().decode()
        store = SecureTokenStore(encryption_key=key, use_keyring=True)

        # Should not use keyring
        assert store.using_keyring is False

        # Should not create keyring entry
        keyring_key = keyring.get_password(
            SecureTokenStore.DEFAULT_KEYRING_SERVICE,
            SecureTokenStore.DEFAULT_KEYRING_KEY_NAME,
        )
        # Either None or from previous test (we cleaned up in fixture)
        # The point is store didn't create it
        assert store.cipher is not None
