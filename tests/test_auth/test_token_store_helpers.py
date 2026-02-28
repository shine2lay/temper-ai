"""Tests for temper_ai/auth/oauth/_token_store_helpers.py."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

import temper_ai.auth.oauth._token_store_helpers as helpers_mod
from temper_ai.auth.constants import FIELD_EXPIRES_AT, FIELD_STORED_AT
from temper_ai.auth.oauth._token_store_helpers import (
    _decrypt_and_parse_token,
    _re_encrypt_single_token,
    _try_env_acquisition,
    _try_keyring_acquisition,
    acquire_encryption_key,
    get_or_create_keyring_key,
    re_encrypt_tokens,
)
from temper_ai.shared.utils.exceptions import SecurityError


@pytest.fixture
def cipher():
    return Fernet(Fernet.generate_key())


@pytest.fixture
def cipher_pair():
    return Fernet(Fernet.generate_key()), Fernet(Fernet.generate_key())


def _encrypt(cipher: Fernet, data: dict) -> bytes:
    return cipher.encrypt(json.dumps(data).encode())


# --- get_or_create_keyring_key ---


def test_get_or_create_keyring_key_raises_when_no_keyring():
    with patch.object(helpers_mod, "KEYRING_AVAILABLE", False):
        with pytest.raises(ImportError, match="Keyring library not installed"):
            get_or_create_keyring_key("svc", "keyname")


def test_get_or_create_keyring_key_returns_existing_key():
    existing = Fernet.generate_key().decode()
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = existing

    with patch.object(helpers_mod, "KEYRING_AVAILABLE", True):
        with patch.object(helpers_mod, "keyring", mock_keyring, create=True):
            result = get_or_create_keyring_key("svc", "key")

    assert result == existing
    mock_keyring.set_password.assert_not_called()


def test_get_or_create_keyring_key_creates_new_when_missing():
    mock_keyring = MagicMock()
    mock_keyring.get_password.return_value = None

    with patch.object(helpers_mod, "KEYRING_AVAILABLE", True):
        with patch.object(helpers_mod, "keyring", mock_keyring, create=True):
            result = get_or_create_keyring_key("svc", "key")

    assert result is not None
    mock_keyring.set_password.assert_called_once()
    # Stored key must match returned key
    stored_key = mock_keyring.set_password.call_args[0][2]
    assert result == stored_key


# --- _try_keyring_acquisition ---


def test_try_keyring_acquisition_returns_key_on_success():
    key = Fernet.generate_key().decode()
    with patch(
        "temper_ai.auth.oauth._token_store_helpers.get_or_create_keyring_key",
        return_value=key,
    ):
        result = _try_keyring_acquisition("svc", "keyname", require_keyring=False)

    assert result == key


def test_try_keyring_acquisition_keyring_error_not_required_returns_none():
    class _KRError(Exception):
        pass

    with patch.object(helpers_mod, "KeyringError", _KRError):
        with patch(
            "temper_ai.auth.oauth._token_store_helpers.get_or_create_keyring_key",
            side_effect=_KRError("no backend"),
        ):
            result = _try_keyring_acquisition("svc", "keyname", require_keyring=False)

    assert result is None


def test_try_keyring_acquisition_keyring_error_required_raises():
    class _KRError(Exception):
        pass

    with patch.object(helpers_mod, "KeyringError", _KRError):
        with patch(
            "temper_ai.auth.oauth._token_store_helpers.get_or_create_keyring_key",
            side_effect=_KRError("no backend"),
        ):
            with pytest.raises(SecurityError):
                _try_keyring_acquisition("svc", "keyname", require_keyring=True)


def test_try_keyring_acquisition_import_error_not_required_returns_none():
    # Ensure KeyringError won't catch ImportError (isolation from keyring tests)
    with patch.object(
        helpers_mod, "KeyringError", type("KeyringError", (Exception,), {})
    ):
        with patch(
            "temper_ai.auth.oauth._token_store_helpers.get_or_create_keyring_key",
            side_effect=ImportError("not installed"),
        ):
            result = _try_keyring_acquisition("svc", "keyname", require_keyring=False)

    assert result is None


def test_try_keyring_acquisition_import_error_required_raises():
    with patch.object(
        helpers_mod, "KeyringError", type("KeyringError", (Exception,), {})
    ):
        with patch(
            "temper_ai.auth.oauth._token_store_helpers.get_or_create_keyring_key",
            side_effect=ImportError("not installed"),
        ):
            with pytest.raises(SecurityError):
                _try_keyring_acquisition("svc", "keyname", require_keyring=True)


def test_try_keyring_acquisition_runtime_error_required_raises():
    with patch.object(
        helpers_mod, "KeyringError", type("KeyringError", (Exception,), {})
    ):
        with patch(
            "temper_ai.auth.oauth._token_store_helpers.get_or_create_keyring_key",
            side_effect=RuntimeError("crash"),
        ):
            with pytest.raises(SecurityError):
                _try_keyring_acquisition("svc", "keyname", require_keyring=True)


def test_try_keyring_acquisition_runtime_error_not_required_returns_none():
    with patch.object(
        helpers_mod, "KeyringError", type("KeyringError", (Exception,), {})
    ):
        with patch(
            "temper_ai.auth.oauth._token_store_helpers.get_or_create_keyring_key",
            side_effect=RuntimeError("crash"),
        ):
            result = _try_keyring_acquisition("svc", "keyname", require_keyring=False)

    assert result is None


# --- _try_env_acquisition ---


def test_try_env_acquisition_returns_key_when_set(monkeypatch):
    test_key = Fernet.generate_key().decode()
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", test_key)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    result = _try_env_acquisition()
    assert result == test_key


def test_try_env_acquisition_returns_none_when_absent(monkeypatch):
    monkeypatch.delenv("OAUTH_TOKEN_ENCRYPTION_KEY", raising=False)
    result = _try_env_acquisition()
    assert result is None


def test_try_env_acquisition_returns_none_for_empty_string(monkeypatch):
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "")
    result = _try_env_acquisition()
    assert result is None


# --- acquire_encryption_key ---


def test_acquire_encryption_key_uses_explicit_key():
    key = Fernet.generate_key().decode()
    result_key, using_kr = acquire_encryption_key(
        encryption_key=key,
        use_keyring=False,
        keyring_service="svc",
        keyring_key_name="kn",
        require_keyring=False,
    )
    assert result_key == key
    assert using_kr is False


def test_acquire_encryption_key_uses_keyring():
    key = Fernet.generate_key().decode()
    with patch(
        "temper_ai.auth.oauth._token_store_helpers._try_keyring_acquisition",
        return_value=key,
    ):
        result_key, using_kr = acquire_encryption_key(
            encryption_key=None,
            use_keyring=True,
            keyring_service="svc",
            keyring_key_name="kn",
            require_keyring=False,
        )
    assert result_key == key
    assert using_kr is True


def test_acquire_encryption_key_falls_back_to_env(monkeypatch):
    env_key = Fernet.generate_key().decode()
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", env_key)
    with patch(
        "temper_ai.auth.oauth._token_store_helpers._try_keyring_acquisition",
        return_value=None,
    ):
        result_key, using_kr = acquire_encryption_key(
            encryption_key=None,
            use_keyring=True,
            keyring_service="svc",
            keyring_key_name="kn",
            require_keyring=False,
        )
    assert result_key == env_key
    assert using_kr is False


def test_acquire_encryption_key_raises_when_no_source(monkeypatch):
    monkeypatch.delenv("OAUTH_TOKEN_ENCRYPTION_KEY", raising=False)
    with patch(
        "temper_ai.auth.oauth._token_store_helpers._try_keyring_acquisition",
        return_value=None,
    ):
        with pytest.raises(ValueError, match="No encryption key available"):
            acquire_encryption_key(
                encryption_key=None,
                use_keyring=True,
                keyring_service="svc",
                keyring_key_name="kn",
                require_keyring=False,
            )


# --- _decrypt_and_parse_token ---


def test_decrypt_and_parse_token_valid(cipher):
    data = {"access_token": "tok123", "token_type": "Bearer"}
    encrypted = _encrypt(cipher, data)
    result = _decrypt_and_parse_token(encrypted, cipher)
    assert result == data


def test_decrypt_and_parse_token_invalid_token(cipher):
    result = _decrypt_and_parse_token(b"corrupt_bytes", cipher)
    assert result is None


def test_decrypt_and_parse_token_bad_json(cipher):
    # Encrypt something that is not valid JSON
    encrypted = cipher.encrypt(b"not valid json")
    result = _decrypt_and_parse_token(encrypted, cipher)
    assert result is None


def test_decrypt_and_parse_token_wrong_cipher():
    cipher1 = Fernet(Fernet.generate_key())
    cipher2 = Fernet(Fernet.generate_key())
    encrypted = _encrypt(cipher1, {"key": "value"})
    result = _decrypt_and_parse_token(encrypted, cipher2)
    assert result is None


# --- _re_encrypt_single_token ---


def test_re_encrypt_single_token_with_future_expiry(cipher):
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    token_data = {
        "access_token": "tok",
        FIELD_EXPIRES_AT: future,
        FIELD_STORED_AT: datetime.now(UTC).isoformat(),
    }
    result = _re_encrypt_single_token(token_data, cipher)
    assert result is not None
    decrypted = json.loads(cipher.decrypt(result).decode())
    assert decrypted["access_token"] == "tok"
    assert FIELD_STORED_AT in decrypted
    assert FIELD_EXPIRES_AT in decrypted


def test_re_encrypt_single_token_expired_returns_none(cipher):
    past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    token_data = {"access_token": "tok", FIELD_EXPIRES_AT: past}
    result = _re_encrypt_single_token(token_data, cipher)
    assert result is None


def test_re_encrypt_single_token_no_expiry(cipher):
    token_data = {
        "access_token": "tok",
        FIELD_STORED_AT: datetime.now(UTC).isoformat(),
    }
    result = _re_encrypt_single_token(token_data, cipher)
    assert result is not None
    decrypted = json.loads(cipher.decrypt(result).decode())
    assert decrypted["access_token"] == "tok"
    assert FIELD_STORED_AT in decrypted
    assert FIELD_EXPIRES_AT not in decrypted


def test_re_encrypt_single_token_updates_stored_at(cipher):
    """stored_at metadata is refreshed during re-encryption."""
    old_stored_at = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    token_data = {"access_token": "tok", FIELD_STORED_AT: old_stored_at}
    result = _re_encrypt_single_token(token_data, cipher)
    assert result is not None
    decrypted = json.loads(cipher.decrypt(result).decode())
    new_stored = datetime.fromisoformat(decrypted[FIELD_STORED_AT])
    old_stored = datetime.fromisoformat(old_stored_at)
    assert new_stored > old_stored


# --- re_encrypt_tokens ---


def test_re_encrypt_tokens_all(cipher_pair):
    old_cipher, new_cipher = cipher_pair
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    data = {"access_token": "tok", FIELD_EXPIRES_AT: future}
    tokens = {
        "user1": _encrypt(old_cipher, data),
        "user2": _encrypt(old_cipher, data),
    }

    result = re_encrypt_tokens(tokens, old_cipher, new_cipher)

    assert set(result.keys()) == {"user1", "user2"}
    for enc in result.values():
        decrypted = json.loads(new_cipher.decrypt(enc).decode())
        assert decrypted["access_token"] == "tok"


def test_re_encrypt_tokens_skips_empty_value(cipher_pair):
    old_cipher, new_cipher = cipher_pair
    tokens: dict = {"user1": b"", "user2": b""}
    result = re_encrypt_tokens(tokens, old_cipher, new_cipher)
    assert result == {}


def test_re_encrypt_tokens_skips_undecryptable(cipher_pair):
    old_cipher, new_cipher = cipher_pair
    tokens = {"user1": b"corrupt_bytes_that_cannot_be_decrypted"}
    result = re_encrypt_tokens(tokens, old_cipher, new_cipher)
    assert result == {}


def test_re_encrypt_tokens_skips_expired(cipher_pair):
    old_cipher, new_cipher = cipher_pair
    past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    data = {"access_token": "tok", FIELD_EXPIRES_AT: past}
    tokens = {"user1": _encrypt(old_cipher, data)}
    result = re_encrypt_tokens(tokens, old_cipher, new_cipher)
    assert result == {}


def test_re_encrypt_tokens_empty_dict(cipher_pair):
    old_cipher, new_cipher = cipher_pair
    result = re_encrypt_tokens({}, old_cipher, new_cipher)
    assert result == {}


def test_re_encrypt_tokens_mixed_valid_and_expired(cipher_pair):
    old_cipher, new_cipher = cipher_pair
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    tokens = {
        "valid_user": _encrypt(
            old_cipher, {"access_token": "ok", FIELD_EXPIRES_AT: future}
        ),
        "expired_user": _encrypt(
            old_cipher, {"access_token": "old", FIELD_EXPIRES_AT: past}
        ),
    }
    result = re_encrypt_tokens(tokens, old_cipher, new_cipher)
    assert set(result.keys()) == {"valid_user"}
