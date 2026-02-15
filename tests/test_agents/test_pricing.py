"""Tests for LLM pricing management system."""
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.llm.pricing import (
    ModelPricing,
    PricingManager,
    SecurityError,
    get_pricing_manager,
)


@pytest.fixture(autouse=True)
def reset_pricing_singleton():
    """Reset pricing singleton before each test."""
    PricingManager.reset_for_testing()
    yield
    PricingManager.reset_for_testing()


@pytest.fixture
def config_path():
    """Path to test pricing configuration."""
    return "tests/fixtures/pricing.yaml"


@pytest.fixture
def temp_pricing_file(tmp_path):
    """Create temporary pricing config file within project for testing."""
    # Create temp file in tests/fixtures directory (within project)
    temp_file = Path('tests/fixtures/temp_test_pricing.yaml')

    config = {
        'schema_version': '1.0',
        'last_updated': '2026-02-01',
        'models': {
            'test-model': {
                'input_price': 1.0,
                'output_price': 2.0,
                'effective_date': '2026-01-01'
            }
        },
        'default': {
            'input_price': 3.0,
            'output_price': 15.0,
            'effective_date': '2026-01-01'
        }
    }

    with open(temp_file, 'w') as f:
        yaml.dump(config, f)

    yield str(temp_file)

    # Cleanup
    temp_file.unlink(missing_ok=True)


class TestModelPricing:
    """Test ModelPricing pydantic model."""

    def test_valid_pricing(self):
        """Test creating valid pricing."""
        pricing = ModelPricing(
            input_price=1.0,
            output_price=2.0,
            effective_date=date(2026, 1, 1)
        )

        assert pricing.input_price == 1.0
        assert pricing.output_price == 2.0
        assert pricing.effective_date == date(2026, 1, 1)

    def test_negative_price_rejected(self):
        """Test that negative prices are rejected."""
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            ModelPricing(
                input_price=-1.0,
                output_price=2.0,
                effective_date=date(2026, 1, 1)
            )

    def test_zero_price_allowed(self):
        """Test that zero prices are allowed (for local/free models)."""
        pricing = ModelPricing(
            input_price=0.0,
            output_price=0.0,
            effective_date=date(2026, 1, 1)
        )
        assert pricing.input_price == 0.0
        assert pricing.output_price == 0.0

    def test_unreasonably_high_price_rejected(self):
        """Test that unreasonably high prices are rejected."""
        with pytest.raises(ValidationError, match="unreasonably high"):
            ModelPricing(
                input_price=1500.0,  # > $1000 per 1M tokens
                output_price=2.0,
                effective_date=date(2026, 1, 1)
            )

    def test_optional_fields(self):
        """Test optional fields."""
        pricing = ModelPricing(
            input_price=1.0,
            output_price=2.0,
            effective_date=date(2026, 1, 1),
            source_url="https://example.com/pricing",
            notes="Test pricing"
        )

        assert pricing.source_url == "https://example.com/pricing"
        assert pricing.notes == "Test pricing"


class TestPricingManager:
    """Test PricingManager class."""

    def test_singleton_pattern(self, config_path):
        """Test that PricingManager is a singleton."""
        manager1 = PricingManager(config_path)
        manager2 = PricingManager(config_path)

        assert manager1 is manager2

    def test_load_pricing_from_config(self, config_path):
        """Test loading pricing from config file."""
        manager = PricingManager(config_path)

        assert 'test-model-1' in manager.pricing
        assert 'test-model-2' in manager.pricing
        assert '_default' in manager.pricing

    def test_get_cost_known_model(self, config_path):
        """Test cost calculation for known model."""
        manager = PricingManager(config_path)

        # test-model-1: input=$1/1M, output=$2/1M
        # 1M input + 1M output = $1 + $2 = $3
        cost = manager.get_cost('test-model-1', 1_000_000, 1_000_000)

        assert cost == 3.0

    def test_get_cost_unknown_model_uses_default(
        self,
        config_path,
        caplog
    ):
        """Test that unknown models use default pricing."""
        manager = PricingManager(config_path)

        # Unknown model should use default: input=$3/1M, output=$15/1M
        cost = manager.get_cost('unknown-model', 1_000_000, 1_000_000)

        assert cost == 18.0
        assert "not in pricing config" in caplog.text

    def test_get_cost_calculation_accuracy(self, config_path):
        """Test cost calculation accuracy."""
        manager = PricingManager(config_path)

        # test-model-2: input=$10/1M, output=$20/1M
        # 500K input + 250K output = $5 + $5 = $10
        cost = manager.get_cost('test-model-2', 500_000, 250_000)

        assert cost == 10.0

    def test_reload_pricing(self, temp_pricing_file):
        """Test reloading pricing configuration."""
        manager = PricingManager(temp_pricing_file)

        # Initial cost
        initial_cost = manager.get_cost('test-model', 1_000_000, 1_000_000)
        assert initial_cost == 3.0  # 1 + 2

        # Update config file
        new_config = {
            'schema_version': '1.0',
            'last_updated': '2026-02-01',
            'models': {
                'test-model': {
                    'input_price': 10.0,
                    'output_price': 20.0,
                    'effective_date': '2026-01-01'
                }
            },
            'default': {
                'input_price': 3.0,
                'output_price': 15.0,
                'effective_date': '2026-01-01'
            }
        }

        with open(temp_pricing_file, 'w') as f:
            yaml.dump(new_config, f)

        # Reload pricing
        manager.reload_pricing()

        # New cost should reflect updated pricing
        updated_cost = manager.get_cost('test-model', 1_000_000, 1_000_000)
        assert updated_cost == 30.0  # 10 + 20

    def test_missing_config_uses_fallback(self, caplog):
        """Test that missing config file uses hardcoded fallback."""
        manager = PricingManager('nonexistent/pricing.yaml')

        # Should use hardcoded default
        cost = manager.get_cost('any-model', 1_000_000, 1_000_000)

        assert cost == 18.0  # 3 + 15 (hardcoded default)
        assert "not found" in caplog.text
        assert "hardcoded defaults" in caplog.text

    def test_list_supported_models(self, config_path):
        """Test listing supported models."""
        manager = PricingManager(config_path)

        models = manager.list_supported_models()

        assert 'test-model-1' in models
        assert 'test-model-2' in models
        assert '_default' not in models  # Should exclude internal default

    def test_get_pricing_info(self, config_path):
        """Test getting pricing info for a model."""
        manager = PricingManager(config_path)

        info = manager.get_pricing_info('test-model-1')

        assert info is not None
        assert info.input_price == 1.0
        assert info.output_price == 2.0

    def test_get_pricing_info_unknown_model(self, config_path):
        """Test getting pricing info for unknown model."""
        manager = PricingManager(config_path)

        info = manager.get_pricing_info('unknown-model')

        assert info is None

    def test_health_check(self, config_path):
        """Test health check returns correct status."""
        manager = PricingManager(config_path)

        health = manager.health_check()

        assert health['status'] == 'healthy'
        assert health['models_loaded'] == 2  # test-model-1, test-model-2
        assert health['config_exists'] is True
        assert health['using_fallback'] is False

    def test_security_path_traversal_blocked(self):
        """Test that path traversal is blocked."""
        with pytest.raises(SecurityError, match="outside project"):
            PricingManager('/etc/passwd')

    def test_security_file_size_limit(self):
        """Test that oversized config files are rejected."""
        # Create a large file (> 1MB) within project
        large_file = Path('tests/fixtures/large_pricing.yaml')
        with open(large_file, 'w') as f:
            # Write > 1MB of data
            f.write("x" * (1024 * 1024 + 1))

        try:
            # Should reject due to size
            with pytest.raises(SecurityError, match="too large"):
                PricingManager(str(large_file))
        finally:
            # Cleanup
            large_file.unlink(missing_ok=True)

    def test_unsupported_schema_version(self, tmp_path):
        """Test that unsupported schema versions are rejected."""
        config_file = Path('tests/fixtures/unsupported_schema.yaml')

        config = {
            'schema_version': '99.0',  # Unsupported version
            'last_updated': '2026-02-01',
            'models': {
                'test-model': {
                    'input_price': 1.0,
                    'output_price': 2.0,
                    'effective_date': '2026-01-01'
                }
            },
            'default': {
                'input_price': 3.0,
                'output_price': 15.0,
                'effective_date': '2026-01-01'
            }
        }

        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        try:
            # Should fall back to defaults and log warning
            manager = PricingManager(str(config_file))

            # Should use hardcoded fallback
            assert '_default' in manager.pricing
        finally:
            config_file.unlink(missing_ok=True)

    def test_negative_token_counts_rejected(self, config_path):
        """Test that negative token counts are rejected."""
        manager = PricingManager(config_path)

        with pytest.raises(ValueError, match="non-negative"):
            manager.get_cost('test-model-1', -100, 100)

        with pytest.raises(ValueError, match="non-negative"):
            manager.get_cost('test-model-1', 100, -100)

    def test_zero_tokens(self, config_path):
        """Test cost calculation with zero tokens."""
        manager = PricingManager(config_path)

        cost = manager.get_cost('test-model-1', 0, 0)

        assert cost == 0.0


class TestGetPricingManager:
    """Test get_pricing_manager() function."""

    def test_returns_singleton(self, config_path):
        """Test that get_pricing_manager returns singleton."""
        manager1 = get_pricing_manager(config_path)
        manager2 = get_pricing_manager(config_path)

        assert manager1 is manager2

    def test_default_config_path(self):
        """Test that default config path is used."""
        # Create a fresh instance with default path
        # Note: Can't test the global singleton since it may be initialized
        # with a test path, so we test the PricingManager directly
        PricingManager.reset_for_testing()

        # Create manager without arguments (uses default)
        manager = PricingManager()

        # Should use default path
        assert 'config/model_pricing.yaml' in str(manager.config_path)


class TestPricingIntegration:
    """Integration tests for pricing system."""

    def test_production_config_loads(self):
        """Test that production pricing config loads successfully."""
        # Reset singleton
        PricingManager.reset_for_testing()

        # Should load without errors
        manager = get_pricing_manager()

        # Should have some models loaded
        models = manager.list_supported_models()
        assert len(models) > 0

        # Should include common models
        common_models = ['claude-3-opus', 'claude-3-sonnet', 'gpt-4']
        for model in common_models:
            if model in models:
                # Verify pricing is reasonable
                cost = manager.get_cost(model, 1_000_000, 1_000_000)
                assert cost > 0
                assert cost < 1000  # Sanity check

    def test_cost_estimation_matches_documentation(self):
        """Test that costs match documented examples."""
        PricingManager.reset_for_testing()
        manager = get_pricing_manager()

        # Claude 3 Opus: $15/1M input, $75/1M output
        # 1M input + 1M output should = $90
        if 'claude-3-opus' in manager.list_supported_models():
            cost = manager.get_cost('claude-3-opus', 1_000_000, 1_000_000)
            assert cost == 90.0
