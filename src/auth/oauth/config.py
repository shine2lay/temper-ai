"""OAuth configuration management.

Handles OAuth provider configuration with secure credential management
and validation. Supports ${env:VAR} reference resolution.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from pathlib import Path
import os
import re
import yaml


class ConfigurationError(Exception):
    """Raised when OAuth configuration is invalid."""

    def __init__(self, message: str, config_path: Optional[str] = None):
        self.config_path = config_path
        super().__init__(message)


class OAuthProviderConfig(BaseModel):
    """Configuration for a single OAuth provider.

    Example:
        >>> config = OAuthProviderConfig(
        ...     provider="google",
        ...     client_id="${env:GOOGLE_CLIENT_ID}",
        ...     client_secret="${env:GOOGLE_CLIENT_SECRET}",
        ...     redirect_uri="https://app.example.com/auth/callback/google",
        ...     scopes=["openid", "email", "profile"]
        ... )
    """

    provider: str = Field(
        ...,
        description="Provider name (google, github, microsoft, etc.)"
    )

    client_id: str = Field(
        ...,
        description="OAuth client ID (supports ${env:VAR} references)"
    )

    client_secret: str = Field(
        ...,
        description="OAuth client secret (supports ${env:VAR} references)"
    )

    redirect_uri: str = Field(
        ...,
        description="OAuth callback URL (must be whitelisted)"
    )

    scopes: List[str] = Field(
        default_factory=list,
        description="OAuth scopes to request"
    )

    authorization_endpoint: Optional[str] = Field(
        default=None,
        description="Custom authorization endpoint (optional, uses provider default)"
    )

    token_endpoint: Optional[str] = Field(
        default=None,
        description="Custom token endpoint (optional, uses provider default)"
    )

    # Additional provider-specific configuration
    extra_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional provider-specific parameters"
    )

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate provider name."""
        allowed = {'google', 'github', 'microsoft', 'gitlab'}
        if v not in allowed:
            raise ValueError(
                f"Unsupported provider '{v}'. Allowed: {', '.join(allowed)}"
            )
        return v

    @field_validator('scopes')
    @classmethod
    def validate_scopes(cls, v: List[str]) -> List[str]:
        """Validate scopes are non-empty."""
        if not v:
            raise ValueError("At least one scope is required")
        return v

    def resolve_env_references(self) -> 'OAuthProviderConfig':
        """Resolve ${env:VAR} references in configuration.

        Returns:
            New config with resolved environment variables

        Raises:
            ConfigurationError: If environment variable not found
        """
        def resolve_value(value: str) -> str:
            """Resolve ${env:VAR} pattern in a string."""
            if not isinstance(value, str):
                return value

            # Match ${env:VARIABLE_NAME}
            pattern = r'\$\{env:([A-Z_][A-Z0-9_]*)\}'

            def replacer(match):
                var_name = match.group(1)
                env_value = os.getenv(var_name)
                if env_value is None:
                    raise ConfigurationError(
                        f"Environment variable '{var_name}' not found for OAuth config",
                        config_path=f"oauth.{self.provider}.{var_name}"
                    )
                return env_value

            return re.sub(pattern, replacer, value)

        # Create new config with resolved values
        resolved_data = self.model_dump()
        resolved_data['client_id'] = resolve_value(self.client_id)
        resolved_data['client_secret'] = resolve_value(self.client_secret)
        resolved_data['redirect_uri'] = resolve_value(self.redirect_uri)

        if self.authorization_endpoint:
            resolved_data['authorization_endpoint'] = resolve_value(
                self.authorization_endpoint
            )
        if self.token_endpoint:
            resolved_data['token_endpoint'] = resolve_value(self.token_endpoint)

        return OAuthProviderConfig(**resolved_data)


class OAuthConfig(BaseModel):
    """OAuth system configuration.

    Example:
        >>> config = OAuthConfig(
        ...     providers=[
        ...         OAuthProviderConfig(
        ...             provider="google",
        ...             client_id="${env:GOOGLE_CLIENT_ID}",
        ...             client_secret="${env:GOOGLE_CLIENT_SECRET}",
        ...             redirect_uri="https://app.example.com/auth/callback/google",
        ...             scopes=["openid", "email", "profile"]
        ...         )
        ...     ],
        ...     allowed_callback_urls=[
        ...         "https://app.example.com/auth/callback/google",
        ...         "http://localhost:8000/auth/callback/google"
        ...     ],
        ...     token_encryption_key="${env:OAUTH_TOKEN_ENCRYPTION_KEY}",
        ...     state_secret_key="${env:OAUTH_STATE_SECRET}",
        ...     token_expiry_seconds=3600
        ... )
    """

    providers: List[OAuthProviderConfig] = Field(
        ...,
        description="List of OAuth provider configurations"
    )

    allowed_callback_urls: List[str] = Field(
        ...,
        description="Whitelist of allowed OAuth callback URLs"
    )

    token_encryption_key: str = Field(
        ...,
        description="Encryption key for token storage (supports ${env:VAR})"
    )

    state_secret_key: str = Field(
        ...,
        description="Secret key for CSRF state token generation (supports ${env:VAR})"
    )

    token_expiry_seconds: int = Field(
        default=3600,
        description="Default token expiry in seconds",
        ge=60,  # Minimum 1 minute
        le=86400  # Maximum 24 hours
    )

    allow_localhost: bool = Field(
        default=True,
        description="Allow localhost callback URLs (dev mode)"
    )

    @model_validator(mode='after')
    def validate_callback_urls_match_providers(self) -> 'OAuthConfig':
        """Validate that all provider redirect URIs are in allowed list."""
        allowed_set = set(self.allowed_callback_urls)

        for provider in self.providers:
            # Skip ${env:VAR} references (will be validated after resolution)
            if '${env:' in provider.redirect_uri:
                continue

            if provider.redirect_uri not in allowed_set:
                raise ValueError(
                    f"Provider '{provider.provider}' redirect_uri "
                    f"'{provider.redirect_uri}' not in allowed_callback_urls"
                )

        return self

    def get_provider_config(self, provider: str) -> Optional[OAuthProviderConfig]:
        """Get configuration for a specific provider.

        Args:
            provider: Provider name (google, github, etc.)

        Returns:
            OAuthProviderConfig or None if not found
        """
        for config in self.providers:
            if config.provider == provider:
                return config
        return None

    def resolve_env_references(self) -> 'OAuthConfig':
        """Resolve all ${env:VAR} references in configuration.

        Returns:
            New config with all environment variables resolved

        Raises:
            ConfigurationError: If environment variable not found
        """
        def resolve_value(value: str) -> str:
            """Resolve ${env:VAR} pattern."""
            if not isinstance(value, str):
                return value

            pattern = r'\$\{env:([A-Z_][A-Z0-9_]*)\}'

            def replacer(match):
                var_name = match.group(1)
                env_value = os.getenv(var_name)
                if env_value is None:
                    raise ConfigurationError(
                        f"Environment variable '{var_name}' not found",
                        config_path=f"oauth.{var_name}"
                    )
                return env_value

            return re.sub(pattern, replacer, value)

        # Resolve providers
        resolved_providers = [
            provider.resolve_env_references() for provider in self.providers
        ]

        # Resolve other fields
        resolved_data = self.model_dump()
        resolved_data['providers'] = [p.model_dump() for p in resolved_providers]
        resolved_data['token_encryption_key'] = resolve_value(self.token_encryption_key)
        resolved_data['state_secret_key'] = resolve_value(self.state_secret_key)
        resolved_data['allowed_callback_urls'] = [
            resolve_value(url) for url in self.allowed_callback_urls
        ]

        return OAuthConfig(**resolved_data)

    @classmethod
    def from_yaml_file(cls, config_path: Path) -> 'OAuthConfig':
        """Load OAuth config from YAML file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            OAuthConfig instance with resolved environment variables

        Raises:
            FileNotFoundError: If config file not found
            ConfigurationError: If config validation fails
        """
        if not config_path.exists():
            raise FileNotFoundError(f"OAuth config file not found: {config_path}")

        try:
            with open(config_path, 'r') as f:
                data = yaml.safe_load(f)

            # Create and validate config
            config = cls(**data)

            # Resolve environment variable references
            return config.resolve_env_references()

        except Exception as e:
            raise ConfigurationError(
                f"Failed to load OAuth config: {e}",
                config_path=str(config_path)
            ) from e


# Provider defaults (used when custom endpoints not specified)
PROVIDER_DEFAULTS = {
    'google': {
        'authorization_endpoint': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token_endpoint': 'https://oauth2.googleapis.com/token',
        'userinfo_endpoint': 'https://www.googleapis.com/oauth2/v2/userinfo',
    },
    'github': {
        'authorization_endpoint': 'https://github.com/login/oauth/authorize',
        'token_endpoint': 'https://github.com/login/oauth/access_token',
        'userinfo_endpoint': 'https://api.github.com/user',
    },
    'microsoft': {
        'authorization_endpoint': 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
        'token_endpoint': 'https://login.microsoftonline.com/common/oauth2/v2.0/token',
        'userinfo_endpoint': 'https://graph.microsoft.com/v1.0/me',
    },
}


def get_provider_endpoints(config: OAuthProviderConfig) -> Dict[str, str]:
    """Get OAuth endpoints for a provider (with fallback to defaults).

    Args:
        config: Provider configuration

    Returns:
        Dict with authorization_endpoint, token_endpoint, userinfo_endpoint

    Raises:
        ConfigurationError: If provider not supported and no custom endpoints
    """
    defaults = PROVIDER_DEFAULTS.get(config.provider, {})

    auth_endpoint = config.authorization_endpoint or defaults.get('authorization_endpoint')
    token_endpoint = config.token_endpoint or defaults.get('token_endpoint')
    userinfo_endpoint = defaults.get('userinfo_endpoint')

    if not auth_endpoint or not token_endpoint:
        raise ConfigurationError(
            f"Provider '{config.provider}' requires custom endpoints "
            f"(authorization_endpoint and token_endpoint)",
            config_path=f"oauth.providers.{config.provider}"
        )

    return {
        'authorization_endpoint': auth_endpoint,
        'token_endpoint': token_endpoint,
        'userinfo_endpoint': userinfo_endpoint,
    }
