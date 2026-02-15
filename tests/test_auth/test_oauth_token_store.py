"""Tests for SecureTokenStore."""
import json
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from cryptography.fernet import Fernet, InvalidToken

from src.auth.oauth.token_store import SecureTokenStore
from src.shared.utils.exceptions import SecurityError


@pytest.fixture
def encryption_key():
    """Generate test encryption key."""
    return Fernet.generate_key().decode()


@pytest.fixture
def token_store(encryption_key):
    """Create token store with test key."""
    return SecureTokenStore(encryption_key=encryption_key)


@pytest.fixture
def sample_token_data():
    """Create sample token data."""
    return {
        "access_token": "ya29.a0Aa4xrXPZaBcDeFgHiJkLmNoPqRsTuVwXyZ",
        "refresh_token": "1//0gL1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0",
        "token_type": "Bearer",
        "scope": "openid email profile",
        "id_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6ImFiYzEyMyJ9...",
    }


class TestSecureTokenStoreInitialization:
    """Test SecureTokenStore initialization."""

    def test_initialization_with_explicit_key(self, encryption_key):
        """Test initialization with explicit encryption key."""
        store = SecureTokenStore(encryption_key=encryption_key)

        assert store.cipher is not None
        assert store.using_keyring is False

    def test_initialization_with_invalid_key(self):
        """Test initialization with invalid encryption key."""
        with pytest.raises(ValueError, match="Invalid encryption key"):
            SecureTokenStore(encryption_key="invalid_key")

    def test_initialization_with_keyring_unavailable(self):
        """Test initialization when keyring unavailable."""
        with patch('src.auth.oauth.token_store.KEYRING_AVAILABLE', False):
            with patch.dict('os.environ', {}, clear=True):
                with pytest.raises(ValueError, match="encryption key"):
                    SecureTokenStore(use_keyring=True, require_keyring=False)

    def test_initialization_require_keyring_unavailable(self):
        """Test initialization fails when keyring required but unavailable."""
        with patch('src.auth.oauth.token_store.KEYRING_AVAILABLE', False):
            with pytest.raises(SecurityError, match="keyring"):
                SecureTokenStore(require_keyring=True)

    def test_initialization_with_env_key(self, encryption_key):
        """Test initialization from environment variable."""
        with patch.dict('os.environ', {'OAUTH_TOKEN_ENCRYPTION_KEY': encryption_key}):
            with patch('src.auth.oauth.token_store.KEYRING_AVAILABLE', False):
                store = SecureTokenStore(use_keyring=False)

                assert store.cipher is not None
                assert store.using_keyring is False

    @pytest.mark.skipif(True, reason="keyring not installed")
    @patch('src.auth.oauth.token_store.KEYRING_AVAILABLE', True)
    @patch('keyring.get_password')
    def test_initialization_with_keyring(self, mock_get_password, encryption_key):
        """Test initialization with keyring."""
        mock_get_password.return_value = encryption_key

        store = SecureTokenStore(use_keyring=True)

        assert store.cipher is not None
        assert store.using_keyring is True
        mock_get_password.assert_called_once()

    @pytest.mark.skipif(True, reason="keyring not installed")
    @patch('src.auth.oauth.token_store.KEYRING_AVAILABLE', True)
    @patch('keyring.get_password')
    @patch('keyring.set_password')
    def test_initialization_generates_new_keyring_key(self, mock_set_password, mock_get_password):
        """Test initialization generates new key if not in keyring."""
        mock_get_password.return_value = None  # No existing key

        store = SecureTokenStore(use_keyring=True)

        assert store.cipher is not None
        assert store.using_keyring is True
        mock_set_password.assert_called_once()

    def test_custom_access_log_size(self, encryption_key):
        """Test initialization with custom access log size."""
        store = SecureTokenStore(encryption_key=encryption_key, max_access_log_size=50)

        assert store._access_log.maxlen == 50


class TestStoreToken:
    """Test token storage."""

    def test_store_token_success(self, token_store, sample_token_data):
        """Test storing token successfully."""
        user_id = "user_123"

        token_store.store_token(user_id, sample_token_data, expires_in=3600)

        assert user_id in token_store._tokens
        assert len(token_store._access_log) == 1
        assert token_store._access_log[0]["action"] == "store"

    def test_store_token_with_expiry(self, token_store, sample_token_data):
        """Test storing token with expiry."""
        user_id = "user_123"

        token_store.store_token(user_id, sample_token_data, expires_in=7200)

        # Verify token is encrypted
        encrypted = token_store._tokens[user_id]
        assert isinstance(encrypted, bytes)

        # Verify we can retrieve it
        retrieved = token_store.retrieve_token(user_id)
        assert retrieved is not None
        assert "expires_at" in retrieved

    def test_store_token_without_expiry(self, token_store, sample_token_data):
        """Test storing token without expiry."""
        user_id = "user_123"

        token_store.store_token(user_id, sample_token_data)

        retrieved = token_store.retrieve_token(user_id)
        assert retrieved is not None
        assert retrieved.get("expires_at") is None

    def test_store_token_overwrites_existing(self, token_store, sample_token_data):
        """Test storing token overwrites existing token."""
        user_id = "user_123"

        # Store initial token
        token_store.store_token(user_id, sample_token_data)

        # Store updated token
        updated_data = {**sample_token_data, "access_token": "new_token"}
        token_store.store_token(user_id, updated_data)

        retrieved = token_store.retrieve_token(user_id)
        assert retrieved["access_token"] == "new_token"

    def test_store_token_multiple_users(self, token_store, sample_token_data):
        """Test storing tokens for multiple users."""
        users = ["user_1", "user_2", "user_3"]

        for user_id in users:
            token_store.store_token(user_id, sample_token_data)

        assert len(token_store._tokens) == 3


class TestRetrieveToken:
    """Test token retrieval."""

    def test_retrieve_token_success(self, token_store, sample_token_data):
        """Test retrieving stored token."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data)

        retrieved = token_store.retrieve_token(user_id)

        assert retrieved is not None
        assert retrieved["access_token"] == sample_token_data["access_token"]
        assert retrieved["refresh_token"] == sample_token_data["refresh_token"]
        assert "stored_at" in retrieved

    def test_retrieve_token_not_found(self, token_store):
        """Test retrieving non-existent token."""
        result = token_store.retrieve_token("nonexistent_user")

        assert result is None

    def test_retrieve_token_expired(self, token_store, sample_token_data):
        """Test retrieving expired token."""
        user_id = "user_123"

        # Store token with very short expiry
        token_store.store_token(user_id, sample_token_data, expires_in=-1)

        result = token_store.retrieve_token(user_id)

        # Expired token should be deleted and return None
        assert result is None
        assert user_id not in token_store._tokens

    def test_retrieve_token_corrupted_data(self, token_store, sample_token_data):
        """Test retrieving corrupted token data."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data)

        # Corrupt the encrypted data
        token_store._tokens[user_id] = b"corrupted_data"

        result = token_store.retrieve_token(user_id)

        # Corrupted token should be deleted and return None
        assert result is None
        assert user_id not in token_store._tokens

    def test_retrieve_token_invalid_expiry_format(self, token_store):
        """Test retrieving token with invalid expiry format."""
        user_id = "user_123"
        token_data = {
            "access_token": "test_token",
            "expires_at": "invalid_date",
        }

        # Manually encrypt and store token with invalid expiry
        token_json = json.dumps(token_data)
        encrypted = token_store.cipher.encrypt(token_json.encode())
        token_store._tokens[user_id] = encrypted

        result = token_store.retrieve_token(user_id)

        # Invalid expiry should cause deletion
        assert result is None
        assert user_id not in token_store._tokens

    def test_retrieve_token_creates_audit_log(self, token_store, sample_token_data):
        """Test retrieving token creates audit log entry."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data)

        # Clear access log
        token_store._access_log.clear()

        token_store.retrieve_token(user_id)

        assert len(token_store._access_log) == 1
        assert token_store._access_log[0]["action"] == "retrieve"
        assert token_store._access_log[0]["user_id"] == user_id


class TestDeleteToken:
    """Test token deletion."""

    def test_delete_token_success(self, token_store, sample_token_data):
        """Test deleting existing token."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data)

        result = token_store.delete_token(user_id)

        assert result is True
        assert user_id not in token_store._tokens

    def test_delete_token_not_found(self, token_store):
        """Test deleting non-existent token."""
        result = token_store.delete_token("nonexistent_user")

        assert result is False

    def test_delete_token_creates_audit_log(self, token_store, sample_token_data):
        """Test deleting token creates audit log entry."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data)

        # Clear access log
        token_store._access_log.clear()

        token_store.delete_token(user_id)

        assert len(token_store._access_log) == 1
        assert token_store._access_log[0]["action"] == "delete"


class TestKeyRotation:
    """Test encryption key rotation."""

    def test_rotate_key_success(self, token_store, sample_token_data, encryption_key):
        """Test rotating encryption key."""
        users = ["user_1", "user_2", "user_3"]
        for user_id in users:
            token_store.store_token(user_id, sample_token_data)

        # Generate new key
        new_key = Fernet.generate_key().decode()

        # Rotate key
        token_store.rotate_key(new_key)

        # Verify all tokens can still be retrieved
        for user_id in users:
            retrieved = token_store.retrieve_token(user_id)
            assert retrieved is not None
            assert retrieved["access_token"] == sample_token_data["access_token"]

    def test_rotate_key_invalid_key(self, token_store):
        """Test rotating to invalid key."""
        with pytest.raises(ValueError, match="Invalid new encryption key"):
            token_store.rotate_key("invalid_key")

    def test_rotate_key_creates_audit_log(self, token_store, sample_token_data):
        """Test key rotation creates audit log entry."""
        token_store.store_token("user_123", sample_token_data)
        token_store._access_log.clear()

        new_key = Fernet.generate_key().decode()
        token_store.rotate_key(new_key)

        assert len(token_store._access_log) == 1
        assert token_store._access_log[0]["action"] == "rotate_key"
        assert token_store._access_log[0]["tokens_re_encrypted"] == 1

    @pytest.mark.skipif(True, reason="keyring not installed")
    @patch('src.auth.oauth.token_store.KEYRING_AVAILABLE', True)
    @patch('keyring.set_password')
    @patch('keyring.get_password')
    def test_rotate_key_from_keyring(self, mock_get_password, mock_set_password, encryption_key):
        """Test rotating key from keyring."""
        mock_get_password.return_value = encryption_key

        store = SecureTokenStore(use_keyring=True)
        store.store_token("user_123", {"access_token": "test"})

        store.rotate_key_from_keyring()

        mock_set_password.assert_called()
        assert len(store._tokens) == 1

    def test_rotate_key_from_keyring_not_using_keyring(self, token_store):
        """Test rotating from keyring fails if not using keyring."""
        with pytest.raises(SecurityError, match="keyring mode"):
            token_store.rotate_key_from_keyring()


class TestAuditLog:
    """Test audit logging."""

    def test_audit_log_bounded_size(self, encryption_key):
        """Test audit log respects max size."""
        store = SecureTokenStore(encryption_key=encryption_key, max_access_log_size=5)

        # Generate more operations than max size
        for i in range(10):
            store.store_token(f"user_{i}", {"access_token": "test"})

        # Audit log should be bounded
        assert len(store._access_log) == 5

    def test_get_audit_log(self, token_store, sample_token_data):
        """Test getting audit log."""
        token_store.store_token("user_123", sample_token_data)
        token_store.retrieve_token("user_123")
        token_store.delete_token("user_123")

        audit_log = token_store.get_audit_log()

        assert len(audit_log) == 3
        assert audit_log[0]["action"] == "store"
        assert audit_log[1]["action"] == "retrieve"
        assert audit_log[2]["action"] == "delete"


class TestClearAllTokens:
    """Test clearing all tokens."""

    def test_clear_all_tokens(self, token_store, sample_token_data):
        """Test clearing all stored tokens."""
        users = ["user_1", "user_2", "user_3"]
        for user_id in users:
            token_store.store_token(user_id, sample_token_data)

        count = token_store.clear_all_tokens()

        assert count == 3
        assert len(token_store._tokens) == 0

    def test_clear_all_tokens_empty_store(self, token_store):
        """Test clearing empty token store."""
        count = token_store.clear_all_tokens()

        assert count == 0

    def test_clear_all_tokens_creates_audit_log(self, token_store, sample_token_data):
        """Test clearing all tokens creates audit log entry."""
        token_store.store_token("user_123", sample_token_data)
        token_store._access_log.clear()

        token_store.clear_all_tokens()

        assert len(token_store._access_log) == 1
        assert token_store._access_log[0]["action"] == "clear_all"
        assert token_store._access_log[0]["tokens_deleted"] == 1


class TestThreadSafety:
    """Test thread safety of token store."""

    def test_concurrent_store_operations(self, token_store, sample_token_data):
        """Test concurrent store operations are thread-safe."""
        users = [f"user_{i}" for i in range(20)]
        threads = []

        def store_token(user_id):
            token_store.store_token(user_id, sample_token_data)

        for user_id in users:
            thread = threading.Thread(target=store_token, args=(user_id,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        assert len(token_store._tokens) == 20

    def test_concurrent_retrieve_operations(self, token_store, sample_token_data):
        """Test concurrent retrieve operations are thread-safe."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data)

        results = []
        threads = []

        def retrieve_token():
            result = token_store.retrieve_token(user_id)
            results.append(result is not None)

        for _ in range(20):
            thread = threading.Thread(target=retrieve_token)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        assert all(results)

    def test_concurrent_key_rotation(self, token_store, sample_token_data):
        """Test key rotation is thread-safe."""
        users = [f"user_{i}" for i in range(5)]
        for user_id in users:
            token_store.store_token(user_id, sample_token_data)

        new_key = Fernet.generate_key().decode()

        # Perform rotation while accessing tokens
        results = []
        threads = []

        def rotate():
            token_store.rotate_key(new_key)

        def retrieve():
            for user_id in users:
                result = token_store.retrieve_token(user_id)
                results.append(result is not None)

        rotation_thread = threading.Thread(target=rotate)
        retrieve_threads = [threading.Thread(target=retrieve) for _ in range(3)]

        rotation_thread.start()
        for thread in retrieve_threads:
            thread.start()

        rotation_thread.join()
        for thread in retrieve_threads:
            thread.join()

        # All retrievals should succeed (may have occurred before or after rotation)
        assert all(results)


class TestSecurityFeatures:
    """Test security features of token store."""

    def test_tokens_are_encrypted(self, token_store, sample_token_data):
        """Test that tokens are encrypted in memory."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data)

        encrypted = token_store._tokens[user_id]

        # Encrypted data should not contain plaintext token
        assert sample_token_data["access_token"] not in str(encrypted)
        assert isinstance(encrypted, bytes)

    def test_cannot_decrypt_with_wrong_key(self, sample_token_data):
        """Test that tokens cannot be decrypted with wrong key."""
        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()

        store1 = SecureTokenStore(encryption_key=key1)
        store1.store_token("user_123", sample_token_data)

        # Try to retrieve with different key
        store2 = SecureTokenStore(encryption_key=key2)
        store2._tokens = store1._tokens.copy()

        result = store2.retrieve_token("user_123")

        # Should return None and delete corrupted token
        assert result is None
        assert "user_123" not in store2._tokens

    def test_token_metadata_includes_timestamp(self, token_store, sample_token_data):
        """Test that stored tokens include timestamp metadata."""
        user_id = "user_123"
        token_store.store_token(user_id, sample_token_data)

        retrieved = token_store.retrieve_token(user_id)

        assert "stored_at" in retrieved
        assert isinstance(retrieved["stored_at"], str)

    def test_expiry_enforcement(self, token_store, sample_token_data):
        """Test that expired tokens are automatically deleted."""
        user_id = "user_123"

        # Store token that expires in past
        token_store.store_token(user_id, sample_token_data, expires_in=-3600)

        # Token should be in store
        assert user_id in token_store._tokens

        # Retrieve should delete expired token
        result = token_store.retrieve_token(user_id)

        assert result is None
        assert user_id not in token_store._tokens
