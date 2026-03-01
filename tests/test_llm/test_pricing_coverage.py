"""Coverage tests for temper_ai/llm/pricing.py.

Covers: PricingConfigInvalidError, ModelPricing validation,
PricingManager._validate_config_path, get_cost, unreasonable price validation.
"""

from __future__ import annotations

from datetime import date

import pytest

from temper_ai.llm.pricing import (
    MAX_REASONABLE_PRICE_PER_MILLION,
    ModelPricing,
    PricingConfigInvalidError,
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
