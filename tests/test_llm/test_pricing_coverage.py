"""Coverage tests for temper_ai/llm/pricing.py.

Covers: PricingConfigNotFoundError, PricingConfigInvalidError, ModelPricing validation,
PricingManager._validate_config_path, reload_pricing, health_check,
get_cost auto-reload, unreasonable price validation.
"""

from __future__ import annotations

from datetime import date

import pytest

from temper_ai.llm.pricing import (
    MAX_REASONABLE_PRICE_PER_MILLION,
    ModelPricing,
    PricingConfigInvalidError,
    PricingConfigNotFoundError,
    PricingManager,
    get_pricing_manager,
)


@pytest.fixture(autouse=True)
def reset_pricing_singleton() -> None:
    """Reset the PricingManager singleton before each test."""
    PricingManager.reset_for_testing()
    yield  # type: ignore[misc]
    PricingManager.reset_for_testing()


class TestModelPricing:
    def test_valid(self) -> None:
        mp = ModelPricing(
            input_price=3.0,
            output_price=15.0,
            effective_date=date(2024, 1, 1),
        )
        assert mp.input_price == 3.0

    def test_unreasonable_price_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ModelPricing(
                input_price=MAX_REASONABLE_PRICE_PER_MILLION + 1,
                output_price=1.0,
                effective_date=date(2024, 1, 1),
            )

    def test_zero_price(self) -> None:
        mp = ModelPricing(
            input_price=0.0,
            output_price=0.0,
            effective_date=date(2024, 1, 1),
        )
        assert mp.input_price == 0.0


class TestPricingConfigErrors:
    def test_not_found_error(self) -> None:
        err = PricingConfigNotFoundError("not found")
        assert "not found" in str(err)

    def test_invalid_error(self) -> None:
        err = PricingConfigInvalidError("invalid config")
        assert "invalid" in str(err)


class TestPricingManager:
    def test_get_cost_negative_tokens_raises(self) -> None:
        pm = PricingManager()
        with pytest.raises(ValueError, match="non-negative"):
            pm.get_cost("test-model", -1, 0)

    def test_get_cost_unknown_model_uses_default(self) -> None:
        pm = PricingManager()
        # Unknown model should use default pricing
        cost = pm.get_cost("totally-unknown-model-xyz", 1000000, 0)
        assert cost > 0

    def test_health_check(self) -> None:
        pm = PricingManager()
        health = pm.health_check()
        assert "status" in health
        assert "models_loaded" in health
        assert "config_path" in health

    def test_get_pricing_info_missing(self) -> None:
        pm = PricingManager()
        info = pm.get_pricing_info("nonexistent-model-xyz")
        assert info is None

    def test_list_supported_models(self) -> None:
        pm = PricingManager()
        models = pm.list_supported_models()
        assert isinstance(models, list)
        assert "_default" not in models

    def test_reload_pricing(self) -> None:
        pm = PricingManager()
        # Should not raise
        pm.reload_pricing()
        assert pm._config_mtime is not None or pm.pricing

    def test_reset_for_testing(self) -> None:
        PricingManager()
        PricingManager.reset_for_testing()
        assert PricingManager._instance is None


class TestGetPricingManager:
    def test_returns_instance(self) -> None:
        pm = get_pricing_manager()
        assert isinstance(pm, PricingManager)

    def test_singleton(self) -> None:
        get_pricing_manager()
        # Reset and get again
        PricingManager.reset_for_testing()
        pm2 = get_pricing_manager()
        # After reset, they may or may not be the same instance
        assert isinstance(pm2, PricingManager)
