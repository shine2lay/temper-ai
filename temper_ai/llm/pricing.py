"""LLM pricing management system.

Provides centralized pricing configuration for LLM cost estimation.
Supports per-model pricing, runtime updates, and graceful fallbacks.
"""

import logging
import threading
from datetime import date
from pathlib import Path
from typing import Any, Optional, Self

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from temper_ai.llm.constants import PRICING_DEFAULT_KEY
from temper_ai.shared.constants.limits import MULTIPLIER_VERY_LARGE, THRESHOLD_MIN_COUNT
from temper_ai.shared.constants.sizes import SIZE_1MB

logger = logging.getLogger(__name__)


# Consolidated: canonical definition in src/utils/exceptions.py
from temper_ai.shared.utils.exceptions import (  # noqa: F401
    ConfigurationError,
    ErrorCode,
    SecurityError,
)

# Pricing constants
TOKENS_PER_MILLION = MULTIPLIER_VERY_LARGE * MULTIPLIER_VERY_LARGE  # 1,000,000
MAX_REASONABLE_PRICE_PER_MILLION = MULTIPLIER_VERY_LARGE  # $1000 per 1M tokens

# Default fallback pricing (emergency when config missing/invalid)
DEFAULT_FALLBACK_INPUT_PRICE = 3.0  # USD per 1M input tokens
DEFAULT_FALLBACK_OUTPUT_PRICE = 15.0  # USD per 1M output tokens
FALLBACK_PRICING_YEAR = 2026  # Year for fallback pricing effective date


class PricingConfigNotFoundError(ConfigurationError):
    """Raised when pricing configuration file is not found."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message=message, error_code=ErrorCode.CONFIG_NOT_FOUND, **kwargs
        )


class PricingConfigInvalidError(ConfigurationError):
    """Raised when pricing configuration is invalid."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message=message, error_code=ErrorCode.CONFIG_INVALID, **kwargs)


class ModelPricing(BaseModel):
    """Pricing information for a specific LLM model.

    Attributes:
        input_price: USD cost per 1M input tokens
        output_price: USD cost per 1M output tokens
        effective_date: Date when pricing became effective
        source_url: Optional URL to pricing documentation
        notes: Optional notes about pricing
    """

    input_price: float = Field(ge=0, description="USD per 1M input tokens")
    output_price: float = Field(ge=0, description="USD per 1M output tokens")
    effective_date: date
    source_url: str | None = Field(None, description="URL to pricing documentation")
    notes: str | None = None

    @field_validator("input_price", "output_price")
    @classmethod
    def validate_reasonable_price(cls, v: float) -> float:
        """Validate that prices are reasonable (< $1000 per 1M tokens).

        This is a sanity check to catch configuration errors.
        """
        if v > MAX_REASONABLE_PRICE_PER_MILLION:
            raise ValueError(
                f"Price {v} unreasonably high (>${MAX_REASONABLE_PRICE_PER_MILLION}/1M tokens)"
            )
        return v


class PricingConfig(BaseModel):
    """Root pricing configuration schema.

    Attributes:
        schema_version: Configuration schema version
        last_updated: Date configuration was last updated
        models: Dictionary mapping model names to pricing
        default: Default pricing for unknown models
    """

    schema_version: str = "1.0"
    last_updated: date
    models: dict[str, ModelPricing]
    default: ModelPricing


class PricingManager:
    """Thread-safe singleton manager for LLM pricing.

    Loads pricing from configuration file and provides cost estimation.
    Uses singleton pattern to ensure single source of truth across application.

    Example:
        >>> pricing = get_pricing_manager()
        >>> cost = pricing.get_cost("claude-3-opus", 1_000_000, 500_000)
        >>> print(f"Cost: ${cost:.4f}")
        Cost: $52.5000
    """

    _instance: Optional["PricingManager"] = None
    _lock = threading.RLock()

    # Security constant
    MAX_CONFIG_SIZE = SIZE_1MB

    # Supported schema versions
    SUPPORTED_SCHEMA_VERSIONS = {"1.0"}

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        """Thread-safe singleton instantiation."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance  # type: ignore[return-value]

    def __init__(self, config_path: str = "configs/model_pricing.yaml"):
        """Initialize pricing manager.

        Args:
            config_path: Path to pricing configuration file

        Raises:
            SecurityError: If config path is outside project or file too large
            PricingConfigInvalidError: If config file is invalid
        """
        # Only initialize once (singleton pattern)
        if hasattr(self, "_initialized"):
            return

        self.config_path = Path(config_path).resolve()
        self.pricing: dict[str, ModelPricing] = {}
        self._config_mtime: float | None = None

        # Validate config path security
        self._validate_config_path()

        # Load pricing configuration
        self._load_pricing()

        self._initialized = True

    def _validate_config_path(self) -> None:
        """Validate that config path is secure.

        Raises:
            SecurityError: If path is outside project or file is too large
        """
        # Get project root (3 levels up from temper_ai/llm/pricing.py)
        project_root = Path(__file__).parent.parent.parent.resolve()

        # Ensure config path is within project directory (prevent path traversal)
        try:
            self.config_path.relative_to(project_root)
        except ValueError:
            raise SecurityError(
                f"Config path outside project: {self.config_path}"
            ) from None

        # Check file size if it exists (prevent DoS)
        if self.config_path.exists():
            file_size = self.config_path.stat().st_size
            if file_size > self.MAX_CONFIG_SIZE:
                raise SecurityError(
                    f"Config file too large: {file_size} bytes (max {self.MAX_CONFIG_SIZE})"
                )

    def _load_pricing(self) -> None:
        """Load pricing from configuration file.

        Falls back to hardcoded defaults if config not found.

        Raises:
            PricingConfigInvalidError: If config file is invalid
        """
        try:
            # Check if file has changed (for caching)
            if self.config_path.exists():
                current_mtime = self.config_path.stat().st_mtime
                if self._config_mtime == current_mtime and self.pricing:
                    # Config unchanged, use cached data
                    return

            # Try to load from config file
            if not self.config_path.exists():
                logger.warning(
                    f"Pricing config not found: {self.config_path}. Using hardcoded defaults."
                )
                self.pricing = self._get_hardcoded_defaults()
                return

            # Load and validate config
            logger.info(f"Loading pricing from {self.config_path}")

            with open(self.config_path) as f:
                # Use safe_load to prevent YAML code execution attacks
                raw_config = yaml.safe_load(f)

            # Validate schema with Pydantic
            config = PricingConfig(**raw_config)

            # Validate schema version
            if config.schema_version not in self.SUPPORTED_SCHEMA_VERSIONS:
                raise PricingConfigInvalidError(
                    f"Unsupported schema version: {config.schema_version}. "
                    f"Supported versions: {self.SUPPORTED_SCHEMA_VERSIONS}"
                )

            # Cache pricing data
            self.pricing = config.models.copy()
            self.pricing[PRICING_DEFAULT_KEY] = config.default
            self._config_mtime = self.config_path.stat().st_mtime

            logger.info(
                f"Loaded pricing for {len(self.pricing) - THRESHOLD_MIN_COUNT} models"
            )

        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in pricing config: {e}")
            # Fall back to defaults on YAML parsing error
            self.pricing = self._get_hardcoded_defaults()
            logger.warning("Using hardcoded default pricing due to YAML error")

        except (ValidationError, KeyError, TypeError, PricingConfigInvalidError) as e:
            logger.error(f"Invalid pricing config: {e}", exc_info=True)
            # Fall back to defaults on validation errors
            self.pricing = self._get_hardcoded_defaults()
            logger.warning("Using hardcoded default pricing due to validation error")

    def _get_hardcoded_defaults(self) -> dict[str, ModelPricing]:
        """Get emergency fallback pricing.

        Used when configuration file is missing or invalid.

        Returns:
            Dictionary with default pricing
        """
        logger.warning("Using emergency fallback pricing")
        return {
            PRICING_DEFAULT_KEY: ModelPricing(
                input_price=DEFAULT_FALLBACK_INPUT_PRICE,
                output_price=DEFAULT_FALLBACK_OUTPUT_PRICE,
                effective_date=date(FALLBACK_PRICING_YEAR, 1, 1),
                source_url=None,
            )
        }

    def get_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost for LLM usage.

        Args:
            model: Model name (e.g., "claude-3-opus", "gpt-4")
            input_tokens: Number of input tokens (must be non-negative)
            output_tokens: Number of output tokens (must be non-negative)

        Returns:
            Cost in USD

        Raises:
            ValueError: If token counts are negative

        Example:
            >>> pricing = get_pricing_manager()
            >>> cost = pricing.get_cost("claude-3-opus", 1_000_000, 1_000_000)
            >>> print(f"${cost:.2f}")
            $90.00
        """
        # Validate inputs
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError(
                f"Token counts must be non-negative: "
                f"input={input_tokens}, output={output_tokens}"
            )

        # Auto-reload if config file changed
        try:
            if self.config_path.exists():
                current_mtime = self.config_path.stat().st_mtime
                if current_mtime != self._config_mtime:
                    logger.info("Config file changed, reloading pricing")
                    self._load_pricing()
        except (FileNotFoundError, PermissionError) as e:
            logger.warning(f"Could not check config file for changes: {e}")
            # Continue with cached pricing

        # Lookup model pricing
        pricing = self.pricing.get(model)

        if pricing is None:
            # Model not found, use default
            logger.warning(
                f"Model '{model}' not in pricing config. Using default pricing. "
                f"Add to {self.config_path} for accurate costs."
            )
            pricing = self.pricing[PRICING_DEFAULT_KEY]

        # Calculate cost
        input_cost = (input_tokens / TOKENS_PER_MILLION) * pricing.input_price
        output_cost = (output_tokens / TOKENS_PER_MILLION) * pricing.output_price

        return input_cost + output_cost

    def reload_pricing(self) -> None:
        """Reload pricing from configuration file.

        Useful for runtime updates when pricing config changes.
        Invalidates cache and reloads from disk.
        """
        self._config_mtime = None  # Invalidate cache
        self._load_pricing()
        logger.info("Pricing configuration reloaded")

    def get_pricing_info(self, model: str) -> ModelPricing | None:
        """Get pricing information for a specific model.

        Args:
            model: Model name

        Returns:
            ModelPricing object or None if not found
        """
        return self.pricing.get(model)

    def list_supported_models(self) -> list[str]:
        """List all models with configured pricing.

        Returns:
            List of model names (excludes '_default')
        """
        return [m for m in self.pricing.keys() if m != PRICING_DEFAULT_KEY]

    def health_check(self) -> dict[str, Any]:
        """Health check for monitoring systems.

        Returns:
            Dictionary with health status
        """
        return {
            "status": "healthy" if self.pricing else "degraded",
            "models_loaded": len(self.pricing)
            - THRESHOLD_MIN_COUNT,  # Exclude _default
            "config_path": str(self.config_path),
            "config_exists": self.config_path.exists(),
            "last_reload_mtime": self._config_mtime,
            "using_fallback": not self.config_path.exists(),
        }

    @classmethod
    def reset_for_testing(cls) -> None:
        """Reset singleton for testing.

        Clears both the class singleton and the _initialized flag so
        __init__ will run again on next instantiation.
        Should only be used in test code.
        """
        with cls._lock:
            if cls._instance is not None and hasattr(cls._instance, "_initialized"):
                del cls._instance._initialized
            cls._instance = None


def get_pricing_manager(
    config_path: str = "configs/model_pricing.yaml",
) -> PricingManager:
    """Get global pricing manager instance.

    Routes through PricingManager.__new__ singleton, so there is only
    one path for instance creation (no dual-singleton inconsistency).

    Args:
        config_path: Path to pricing config (only used on first call)

    Returns:
        PricingManager singleton instance

    Example:
        >>> pricing = get_pricing_manager()
        >>> cost = pricing.get_cost("claude-3-opus", 100000, 50000)
    """
    return PricingManager(config_path)
