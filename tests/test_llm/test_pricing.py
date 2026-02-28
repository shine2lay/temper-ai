"""Tests for temper_ai.llm.pricing module.

Covers PricingManager singleton, path security validation, YAML loading,
cost calculation, pricing lookups, and health check.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from temper_ai.llm.pricing import (
    ModelPricing,
    PricingManager,
    SecurityError,
    get_pricing_manager,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

VALID_PRICING_YAML = """\
schema_version: "1.0"
last_updated: "2026-01-01"
models:
  test-model:
    input_price: 1.0
    output_price: 2.0
    effective_date: "2026-01-01"
default:
  input_price: 3.0
  output_price: 15.0
  effective_date: "2026-01-01"
"""


# ---------------------------------------------------------------------------
# Autouse fixture — reset singleton before/after every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pricing_singleton():
    """Reset PricingManager singleton before and after each test."""
    PricingManager.reset_for_testing()
    yield
    PricingManager.reset_for_testing()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_manager(tmp_path, yaml_content=None):
    """Create a PricingManager with a temp config, bypassing path security."""
    config_file = tmp_path / "pricing.yaml"
    config_file.write_text(yaml_content or VALID_PRICING_YAML)
    with patch.object(PricingManager, "_validate_config_path"):
        return PricingManager(config_path=str(config_file))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPricingManagerSingleton:
    """Tests for singleton instantiation and reset behaviour."""

    def test_singleton_same_instance(self):
        """Successive calls return the identical instance."""
        with (
            patch.object(PricingManager, "_validate_config_path"),
            patch.object(PricingManager, "_load_pricing"),
        ):
            m1 = PricingManager()
            m2 = PricingManager()

        assert m1 is m2

    def test_reset_for_testing_creates_new_instance(self):
        """reset_for_testing clears singleton so next instantiation is fresh."""
        with (
            patch.object(PricingManager, "_validate_config_path"),
            patch.object(PricingManager, "_load_pricing"),
        ):
            m1 = PricingManager()

        PricingManager.reset_for_testing()

        with (
            patch.object(PricingManager, "_validate_config_path"),
            patch.object(PricingManager, "_load_pricing"),
        ):
            m2 = PricingManager()

        assert m1 is not m2


class TestValidateConfigPath:
    """Tests for _validate_config_path security checks."""

    def test_path_traversal_blocked(self):
        """Path traversal attempt raises SecurityError."""
        with pytest.raises(SecurityError):
            PricingManager(config_path="../../../../etc/passwd")

    def test_absolute_path_outside_project_blocked(self):
        """Absolute path outside the project root raises SecurityError."""
        with pytest.raises(SecurityError):
            PricingManager(config_path="/etc/passwd")


class TestLoadPricing:
    """Tests for _load_pricing file parsing and fallback behaviour."""

    def test_valid_yaml_loaded(self, tmp_path):
        """Valid YAML config populates model pricing dict."""
        manager = _make_manager(tmp_path)

        assert "test-model" in manager.pricing
        assert "_default" in manager.pricing
        assert isinstance(manager.pricing["test-model"], ModelPricing)

    def test_invalid_yaml_falls_back_to_defaults(self, tmp_path):
        """Malformed YAML falls back to hardcoded defaults."""
        manager = _make_manager(tmp_path, yaml_content="key: [unclosed")

        assert "_default" in manager.pricing
        assert "test-model" not in manager.pricing

    def test_missing_file_falls_back_to_defaults(self, tmp_path):
        """Non-existent config path falls back to hardcoded defaults."""
        missing = tmp_path / "nonexistent.yaml"
        with patch.object(PricingManager, "_validate_config_path"):
            manager = PricingManager(config_path=str(missing))

        assert "_default" in manager.pricing

    def test_oversized_file_blocked(self):
        """Config file larger than 1 MB raises SecurityError."""
        project_root = Path(__file__).parent.parent.parent
        large_file = (
            project_root / "tests" / "test_llm" / "_temp_oversized_pricing.yaml"
        )
        try:
            large_file.write_bytes(b"x" * (PricingManager.MAX_CONFIG_SIZE + 1))
            with pytest.raises(SecurityError):
                PricingManager(config_path=str(large_file))
        finally:
            large_file.unlink(missing_ok=True)


class TestGetCost:
    """Tests for PricingManager.get_cost calculation."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Provide a PricingManager loaded with valid test config."""
        return _make_manager(tmp_path)

    def test_known_model_returns_correct_cost(self, manager):
        """Known model pricing yields expected USD cost."""
        # test-model: input=1.0/M, output=2.0/M
        # 1M input + 1M output → $1.00 + $2.00 = $3.00
        cost = manager.get_cost("test-model", 1_000_000, 1_000_000)
        assert cost == pytest.approx(3.0)

    def test_unknown_model_uses_default_pricing(self, manager):
        """Unknown model falls back to _default pricing entry."""
        # default: input=3.0/M → 1M input = $3.00
        cost = manager.get_cost("no-such-model", 1_000_000, 0)
        assert cost == pytest.approx(3.0)

    def test_zero_tokens_returns_zero(self, manager):
        """Zero input and output tokens yields zero cost."""
        cost = manager.get_cost("test-model", 0, 0)
        assert cost == 0.0

    def test_negative_tokens_raises_value_error(self, manager):
        """Negative token counts raise ValueError."""
        with pytest.raises(ValueError):
            manager.get_cost("test-model", -1, 0)


class TestGetPricingInfo:
    """Tests for PricingManager.get_pricing_info lookup."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Provide a PricingManager loaded with valid test config."""
        return _make_manager(tmp_path)

    def test_known_model_returns_model_pricing(self, manager):
        """Known model returns its ModelPricing object."""
        info = manager.get_pricing_info("test-model")
        assert isinstance(info, ModelPricing)
        assert info.input_price == pytest.approx(1.0)
        assert info.output_price == pytest.approx(2.0)

    def test_unknown_model_returns_none(self, manager):
        """Unknown model returns None."""
        info = manager.get_pricing_info("unknown-xyz")
        assert info is None


class TestListSupportedModels:
    """Tests for PricingManager.list_supported_models."""

    def test_excludes_default_key(self, tmp_path):
        """list_supported_models excludes '_default' and includes named models."""
        manager = _make_manager(tmp_path)
        models = manager.list_supported_models()

        assert "_default" not in models
        assert "test-model" in models


class TestHealthCheck:
    """Tests for PricingManager.health_check monitoring interface."""

    def test_returns_required_keys(self, tmp_path):
        """health_check dict contains status, models_loaded, and config_path."""
        manager = _make_manager(tmp_path)
        result = manager.health_check()

        assert "status" in result
        assert "models_loaded" in result
        assert "config_path" in result

    def test_healthy_when_pricing_loaded(self, tmp_path):
        """Status is 'healthy' when pricing models are successfully loaded."""
        manager = _make_manager(tmp_path)
        result = manager.health_check()

        assert result["status"] == "healthy"


class TestGetPricingManagerFunction:
    """Tests for the get_pricing_manager convenience function."""

    def test_returns_pricing_manager_instance(self):
        """get_pricing_manager returns a PricingManager instance."""
        with (
            patch.object(PricingManager, "_validate_config_path"),
            patch.object(PricingManager, "_load_pricing"),
        ):
            pm = get_pricing_manager()

        assert isinstance(pm, PricingManager)

    def test_returns_same_singleton(self):
        """get_pricing_manager returns the same instance on repeated calls."""
        with (
            patch.object(PricingManager, "_validate_config_path"),
            patch.object(PricingManager, "_load_pricing"),
        ):
            pm1 = get_pricing_manager()
            pm2 = get_pricing_manager()

        assert pm1 is pm2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
