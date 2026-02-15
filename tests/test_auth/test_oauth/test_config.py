"""Comprehensive tests for OAuth configuration management.

Tests cover:
- Config validation (required fields, valid URLs)
- Environment variable resolution (${env:VAR})
- Provider configuration loading from YAML
- Multiple provider support
- Invalid config error handling
- Scope validation
"""
import os
import pytest
import tempfile
from pathlib import Path
from typing import Dict, Any

from src.auth.oauth.config import (
    OAuthConfig,
    OAuthProviderConfig,
    OAuthConfigurationError,
    get_provider_endpoints,
    PROVIDER_DEFAULTS,
)


# ==================== FIXTURES ====================


@pytest.fixture
def valid_provider_config() -> Dict[str, Any]:
    """Valid provider configuration dict."""
    return {
        "provider": "google",
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "redirect_uri": "https://app.example.com/auth/callback",
        "scopes": ["openid", "email", "profile"],
    }


@pytest.fixture
def valid_oauth_config() -> Dict[str, Any]:
    """Valid OAuth system configuration dict."""
    return {
        "providers": [
            {
                "provider": "google",
                "client_id": "google_client",
                "client_secret": "google_secret",
                "redirect_uri": "https://app.example.com/auth/callback/google",
                "scopes": ["openid", "email", "profile"],
            },
            {
                "provider": "github",
                "client_id": "github_client",
                "client_secret": "github_secret",
                "redirect_uri": "https://app.example.com/auth/callback/github",
                "scopes": ["user", "email"],
            },
        ],
        "allowed_callback_urls": [
            "https://app.example.com/auth/callback/google",
            "https://app.example.com/auth/callback/github",
        ],
        "token_encryption_key": "test_encryption_key_32_chars",
        "state_secret_key": "test_state_secret_32_chars",
        "token_expiry_seconds": 3600,
    }


@pytest.fixture
def env_vars():
    """Setup environment variables for testing."""
    original_env = os.environ.copy()

    # Set test environment variables
    os.environ["GOOGLE_CLIENT_ID"] = "env_google_client"
    os.environ["GOOGLE_CLIENT_SECRET"] = "env_google_secret"
    os.environ["OAUTH_REDIRECT_URI"] = "https://env.example.com/callback"
    os.environ["OAUTH_TOKEN_KEY"] = "env_token_key_32_characters"
    os.environ["OAUTH_STATE_SECRET"] = "env_state_secret_32_chars"

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


# ==================== PROVIDER CONFIG TESTS ====================


def test_provider_config_valid(valid_provider_config):
    """Test creating valid provider config."""
    config = OAuthProviderConfig(**valid_provider_config)

    assert config.provider == "google"
    assert config.client_id == "test_client_id"
    assert config.client_secret == "test_client_secret"
    assert config.redirect_uri == "https://app.example.com/auth/callback"
    assert config.scopes == ["openid", "email", "profile"]


def test_provider_config_unsupported_provider():
    """Test validation rejects unsupported providers."""
    with pytest.raises(ValueError, match="Unsupported provider 'invalid'"):
        OAuthProviderConfig(
            provider="invalid",
            client_id="test",
            client_secret="test",
            redirect_uri="https://example.com",
            scopes=["openid"],
        )


def test_provider_config_empty_scopes():
    """Test validation rejects empty scopes."""
    with pytest.raises(ValueError, match="At least one scope is required"):
        OAuthProviderConfig(
            provider="google",
            client_id="test",
            client_secret="test",
            redirect_uri="https://example.com",
            scopes=[],
        )


def test_provider_config_missing_required_fields():
    """Test validation rejects missing required fields."""
    with pytest.raises(ValueError):
        OAuthProviderConfig(
            provider="google",
            # Missing client_id, client_secret, redirect_uri, scopes
        )


def test_provider_config_custom_endpoints():
    """Test provider config with custom endpoints."""
    config = OAuthProviderConfig(
        provider="google",
        client_id="test",
        client_secret="test",
        redirect_uri="https://example.com",
        scopes=["openid"],
        authorization_endpoint="https://custom.auth.com/authorize",
        token_endpoint="https://custom.auth.com/token",
        revocation_endpoint="https://custom.auth.com/revoke",
    )

    assert config.authorization_endpoint == "https://custom.auth.com/authorize"
    assert config.token_endpoint == "https://custom.auth.com/token"
    assert config.revocation_endpoint == "https://custom.auth.com/revoke"


def test_provider_config_extra_params():
    """Test provider config with extra parameters."""
    config = OAuthProviderConfig(
        provider="google",
        client_id="test",
        client_secret="test",
        redirect_uri="https://example.com",
        scopes=["openid"],
        extra_params={"access_type": "offline", "prompt": "consent"},
    )

    assert config.extra_params == {"access_type": "offline", "prompt": "consent"}


# ==================== ENV RESOLUTION TESTS ====================


def test_provider_config_resolve_env_references(env_vars):
    """Test environment variable resolution in provider config."""
    config = OAuthProviderConfig(
        provider="google",
        client_id="${env:GOOGLE_CLIENT_ID}",
        client_secret="${env:GOOGLE_CLIENT_SECRET}",
        redirect_uri="${env:OAUTH_REDIRECT_URI}",
        scopes=["openid"],
    )

    resolved = config.resolve_env_references()

    assert resolved.client_id == "env_google_client"
    assert resolved.client_secret == "env_google_secret"
    assert resolved.redirect_uri == "https://env.example.com/callback"


def test_provider_config_resolve_env_missing_var():
    """Test error when environment variable not found."""
    config = OAuthProviderConfig(
        provider="google",
        client_id="${env:MISSING_VAR}",
        client_secret="test",
        redirect_uri="https://example.com",
        scopes=["openid"],
    )

    with pytest.raises(OAuthConfigurationError, match="Environment variable 'MISSING_VAR' not found"):
        config.resolve_env_references()


def test_provider_config_resolve_env_custom_endpoints(env_vars):
    """Test env resolution with custom endpoints."""
    config = OAuthProviderConfig(
        provider="google",
        client_id="${env:GOOGLE_CLIENT_ID}",
        client_secret="${env:GOOGLE_CLIENT_SECRET}",
        redirect_uri="${env:OAUTH_REDIRECT_URI}",
        scopes=["openid"],
        authorization_endpoint="${env:OAUTH_REDIRECT_URI}/auth",
        token_endpoint="${env:OAUTH_REDIRECT_URI}/token",
    )

    resolved = config.resolve_env_references()

    assert resolved.authorization_endpoint == "https://env.example.com/callback/auth"
    assert resolved.token_endpoint == "https://env.example.com/callback/token"


def test_provider_config_resolve_env_mixed():
    """Test env resolution with mixed literal and env references."""
    os.environ["TEST_CLIENT_ID"] = "env_client"

    config = OAuthProviderConfig(
        provider="google",
        client_id="${env:TEST_CLIENT_ID}",
        client_secret="literal_secret",  # No env reference
        redirect_uri="https://example.com",
        scopes=["openid"],
    )

    resolved = config.resolve_env_references()

    assert resolved.client_id == "env_client"
    assert resolved.client_secret == "literal_secret"


# ==================== OAUTH CONFIG TESTS ====================


def test_oauth_config_valid(valid_oauth_config):
    """Test creating valid OAuth system config."""
    config = OAuthConfig(**valid_oauth_config)

    assert len(config.providers) == 2
    assert config.providers[0].provider == "google"
    assert config.providers[1].provider == "github"
    assert len(config.allowed_callback_urls) == 2
    assert config.token_expiry_seconds == 3600


def test_oauth_config_multiple_providers(valid_oauth_config):
    """Test config supports multiple providers."""
    config = OAuthConfig(**valid_oauth_config)

    google_config = config.get_provider_config("google")
    github_config = config.get_provider_config("github")

    assert google_config is not None
    assert google_config.provider == "google"
    assert github_config is not None
    assert github_config.provider == "github"


def test_oauth_config_get_provider_not_found(valid_oauth_config):
    """Test getting non-existent provider returns None."""
    config = OAuthConfig(**valid_oauth_config)

    result = config.get_provider_config("microsoft")

    assert result is None


def test_oauth_config_callback_url_validation(valid_oauth_config):
    """Test callback URL must be in allowed list."""
    # Remove one callback URL from allowed list
    valid_oauth_config["allowed_callback_urls"] = [
        "https://app.example.com/auth/callback/google",
    ]

    with pytest.raises(ValueError, match="redirect_uri.*not in allowed_callback_urls"):
        OAuthConfig(**valid_oauth_config)


def test_oauth_config_callback_url_validation_with_env():
    """Test callback URL validation skips env references."""
    config_data = {
        "providers": [
            {
                "provider": "google",
                "client_id": "test",
                "client_secret": "test",
                "redirect_uri": "${env:OAUTH_CALLBACK}",
                "scopes": ["openid"],
            }
        ],
        "allowed_callback_urls": ["https://example.com/callback"],
        "token_encryption_key": "test_key",
        "state_secret_key": "test_secret",
    }

    # Should not raise error (env references skipped during validation)
    config = OAuthConfig(**config_data)
    assert config is not None


def test_oauth_config_token_expiry_bounds():
    """Test token expiry seconds validation."""
    from src.shared.constants.durations import SECONDS_PER_MINUTE, SECONDS_PER_DAY

    base_config = {
        "providers": [
            {
                "provider": "google",
                "client_id": "test",
                "client_secret": "test",
                "redirect_uri": "https://example.com/callback",
                "scopes": ["openid"],
            }
        ],
        "allowed_callback_urls": ["https://example.com/callback"],
        "token_encryption_key": "test_key",
        "state_secret_key": "test_secret",
    }

    # Test minimum boundary (1 minute = 60 seconds)
    config_min = OAuthConfig(**base_config, token_expiry_seconds=SECONDS_PER_MINUTE)
    assert config_min.token_expiry_seconds == SECONDS_PER_MINUTE

    # Test maximum boundary (24 hours = 86400 seconds)
    config_max = OAuthConfig(**base_config, token_expiry_seconds=SECONDS_PER_DAY)
    assert config_max.token_expiry_seconds == SECONDS_PER_DAY

    # Test below minimum
    with pytest.raises(ValueError):
        OAuthConfig(**base_config, token_expiry_seconds=30)

    # Test above maximum
    with pytest.raises(ValueError):
        OAuthConfig(**base_config, token_expiry_seconds=SECONDS_PER_DAY + 1)


def test_oauth_config_allow_localhost_production():
    """Test localhost disabled in production by default."""
    os.environ["ENVIRONMENT"] = "production"

    config_data = {
        "providers": [
            {
                "provider": "google",
                "client_id": "test",
                "client_secret": "test",
                "redirect_uri": "https://example.com/callback",
                "scopes": ["openid"],
            }
        ],
        "allowed_callback_urls": ["https://example.com/callback"],
        "token_encryption_key": "test_key",
        "state_secret_key": "test_secret",
    }

    config = OAuthConfig(**config_data)
    assert config.allow_localhost is False


def test_oauth_config_allow_localhost_development():
    """Test localhost enabled in development."""
    os.environ["ENVIRONMENT"] = "development"

    config_data = {
        "providers": [
            {
                "provider": "google",
                "client_id": "test",
                "client_secret": "test",
                "redirect_uri": "https://example.com/callback",
                "scopes": ["openid"],
            }
        ],
        "allowed_callback_urls": ["https://example.com/callback"],
        "token_encryption_key": "test_key",
        "state_secret_key": "test_secret",
    }

    config = OAuthConfig(**config_data)
    assert config.allow_localhost is True


# ==================== OAUTH CONFIG ENV RESOLUTION ====================


def test_oauth_config_resolve_env_all_fields(env_vars):
    """Test resolving all environment variables in OAuth config."""
    config_data = {
        "providers": [
            {
                "provider": "google",
                "client_id": "${env:GOOGLE_CLIENT_ID}",
                "client_secret": "${env:GOOGLE_CLIENT_SECRET}",
                "redirect_uri": "${env:OAUTH_REDIRECT_URI}",
                "scopes": ["openid"],
            }
        ],
        "allowed_callback_urls": ["${env:OAUTH_REDIRECT_URI}"],
        "token_encryption_key": "${env:OAUTH_TOKEN_KEY}",
        "state_secret_key": "${env:OAUTH_STATE_SECRET}",
    }

    config = OAuthConfig(**config_data)
    resolved = config.resolve_env_references()

    assert resolved.providers[0].client_id == "env_google_client"
    assert resolved.providers[0].client_secret == "env_google_secret"
    assert resolved.providers[0].redirect_uri == "https://env.example.com/callback"
    assert resolved.token_encryption_key == "env_token_key_32_characters"
    assert resolved.state_secret_key == "env_state_secret_32_chars"
    assert resolved.allowed_callback_urls[0] == "https://env.example.com/callback"


def test_oauth_config_resolve_env_missing_var():
    """Test error when OAuth config env variable missing."""
    config_data = {
        "providers": [
            {
                "provider": "google",
                "client_id": "test",
                "client_secret": "test",
                "redirect_uri": "https://example.com/callback",
                "scopes": ["openid"],
            }
        ],
        "allowed_callback_urls": ["https://example.com/callback"],
        "token_encryption_key": "${env:MISSING_KEY}",
        "state_secret_key": "test_secret",
    }

    config = OAuthConfig(**config_data)

    with pytest.raises(OAuthConfigurationError, match="Environment variable 'MISSING_KEY' not found"):
        config.resolve_env_references()


# ==================== YAML LOADING TESTS ====================


def test_oauth_config_from_yaml_file(env_vars):
    """Test loading OAuth config from YAML file."""
    yaml_content = """
providers:
  - provider: google
    client_id: ${env:GOOGLE_CLIENT_ID}
    client_secret: ${env:GOOGLE_CLIENT_SECRET}
    redirect_uri: ${env:OAUTH_REDIRECT_URI}
    scopes:
      - openid
      - email
      - profile

allowed_callback_urls:
  - ${env:OAUTH_REDIRECT_URI}

token_encryption_key: ${env:OAUTH_TOKEN_KEY}
state_secret_key: ${env:OAUTH_STATE_SECRET}
token_expiry_seconds: 3600
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        config_path = Path(f.name)

    try:
        config = OAuthConfig.from_yaml_file(config_path)

        assert config.providers[0].client_id == "env_google_client"
        assert config.providers[0].client_secret == "env_google_secret"
        assert config.token_encryption_key == "env_token_key_32_characters"
        assert config.token_expiry_seconds == 3600
    finally:
        config_path.unlink()


def test_oauth_config_from_yaml_file_not_found():
    """Test error when YAML file not found."""
    with pytest.raises(FileNotFoundError, match="OAuth config file not found"):
        OAuthConfig.from_yaml_file(Path("/nonexistent/config.yaml"))


def test_oauth_config_from_yaml_invalid_format():
    """Test error when YAML format is invalid."""
    yaml_content = "invalid: yaml: content: ["

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        config_path = Path(f.name)

    try:
        with pytest.raises(OAuthConfigurationError, match="Invalid OAuth config format"):
            OAuthConfig.from_yaml_file(config_path)
    finally:
        config_path.unlink()


def test_oauth_config_from_yaml_missing_required_field():
    """Test error when required field missing in YAML."""
    yaml_content = """
providers:
  - provider: google
    client_id: test
    # Missing client_secret, redirect_uri, scopes
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        config_path = Path(f.name)

    try:
        with pytest.raises(OAuthConfigurationError, match="Invalid OAuth config format"):
            OAuthConfig.from_yaml_file(config_path)
    finally:
        config_path.unlink()


# ==================== PROVIDER ENDPOINTS TESTS ====================


def test_get_provider_endpoints_google():
    """Test getting default endpoints for Google."""
    config = OAuthProviderConfig(
        provider="google",
        client_id="test",
        client_secret="test",
        redirect_uri="https://example.com",
        scopes=["openid"],
    )

    endpoints = get_provider_endpoints(config)

    assert endpoints["authorization_endpoint"] == PROVIDER_DEFAULTS["google"]["authorization_endpoint"]
    assert endpoints["token_endpoint"] == PROVIDER_DEFAULTS["google"]["token_endpoint"]
    assert endpoints["revocation_endpoint"] == PROVIDER_DEFAULTS["google"]["revocation_endpoint"]
    assert endpoints["userinfo_endpoint"] == PROVIDER_DEFAULTS["google"]["userinfo_endpoint"]


def test_get_provider_endpoints_github():
    """Test getting default endpoints for GitHub."""
    config = OAuthProviderConfig(
        provider="github",
        client_id="test",
        client_secret="test",
        redirect_uri="https://example.com",
        scopes=["user"],
    )

    endpoints = get_provider_endpoints(config)

    assert endpoints["authorization_endpoint"] == PROVIDER_DEFAULTS["github"]["authorization_endpoint"]
    assert endpoints["token_endpoint"] == PROVIDER_DEFAULTS["github"]["token_endpoint"]
    assert endpoints["userinfo_endpoint"] == PROVIDER_DEFAULTS["github"]["userinfo_endpoint"]


def test_get_provider_endpoints_custom_override():
    """Test custom endpoints override defaults."""
    config = OAuthProviderConfig(
        provider="google",
        client_id="test",
        client_secret="test",
        redirect_uri="https://example.com",
        scopes=["openid"],
        authorization_endpoint="https://custom.auth.com/authorize",
        token_endpoint="https://custom.auth.com/token",
    )

    endpoints = get_provider_endpoints(config)

    assert endpoints["authorization_endpoint"] == "https://custom.auth.com/authorize"
    assert endpoints["token_endpoint"] == "https://custom.auth.com/token"


def test_get_provider_endpoints_unsupported_no_custom():
    """Test error for unsupported provider without custom endpoints."""
    # Create config with unsupported provider (bypassing validation for testing)
    config = OAuthProviderConfig(
        provider="google",
        client_id="test",
        client_secret="test",
        redirect_uri="https://example.com",
        scopes=["openid"],
    )
    config.provider = "unsupported"  # Bypass validation

    with pytest.raises(OAuthConfigurationError, match="requires custom endpoints"):
        get_provider_endpoints(config)


def test_get_provider_endpoints_unsupported_with_custom():
    """Test unsupported provider works with custom endpoints."""
    config = OAuthProviderConfig(
        provider="google",
        client_id="test",
        client_secret="test",
        redirect_uri="https://example.com",
        scopes=["openid"],
        authorization_endpoint="https://custom.auth.com/authorize",
        token_endpoint="https://custom.auth.com/token",
    )
    config.provider = "custom_provider"  # Bypass validation

    endpoints = get_provider_endpoints(config)

    assert endpoints["authorization_endpoint"] == "https://custom.auth.com/authorize"
    assert endpoints["token_endpoint"] == "https://custom.auth.com/token"


# ==================== ERROR HANDLING TESTS ====================


def test_oauth_configuration_error_with_path():
    """Test OAuthConfigurationError includes config path."""
    error = OAuthConfigurationError(
        "Test error message",
        config_path="oauth.providers.google.client_id"
    )

    assert str(error) == "Test error message"
    assert error.config_path == "oauth.providers.google.client_id"


def test_oauth_configuration_error_without_path():
    """Test OAuthConfigurationError without config path."""
    error = OAuthConfigurationError("Test error message")

    assert str(error) == "Test error message"
    assert error.config_path is None
