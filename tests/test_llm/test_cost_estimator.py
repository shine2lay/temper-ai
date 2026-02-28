"""Tests for temper_ai.llm.cost_estimator module.

Covers estimate_cost: zero/None tokens, split vs. estimated tokens,
model resolution, and fallback model usage.
"""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.llm.cost_estimator import estimate_cost

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_llm_response(
    total_tokens,
    prompt_tokens=None,
    completion_tokens=None,
    model="test-model",
):
    """Create a mock LLMResponse with the given token and model attributes."""
    mock = MagicMock()
    mock.total_tokens = total_tokens
    mock.prompt_tokens = prompt_tokens
    mock.completion_tokens = completion_tokens
    mock.model = model
    return mock


def _mock_pricing_manager(return_value=0.05):
    """Return a mock PricingManager with get_cost stubbed."""
    mock_pm = MagicMock()
    mock_pm.get_cost.return_value = return_value
    return mock_pm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEstimateCost:
    """Tests for the estimate_cost function."""

    def test_zero_total_tokens_returns_zero(self):
        """Zero total_tokens short-circuits to 0.0 without pricing manager."""
        response = _make_llm_response(total_tokens=0)
        result = estimate_cost(response)
        assert result == 0.0

    def test_none_total_tokens_returns_zero(self):
        """None total_tokens short-circuits to 0.0 without pricing manager."""
        response = _make_llm_response(total_tokens=None)
        result = estimate_cost(response)
        assert result == 0.0

    def test_input_output_split_delegates_to_pricing_manager(self):
        """Explicit prompt/completion tokens are forwarded to get_cost."""
        response = _make_llm_response(
            total_tokens=150, prompt_tokens=100, completion_tokens=50
        )
        mock_pm = _mock_pricing_manager(return_value=0.05)

        with patch(
            "temper_ai.llm.cost_estimator.get_pricing_manager", return_value=mock_pm
        ):
            result = estimate_cost(response)

        mock_pm.get_cost.assert_called_once_with("test-model", 100, 50)
        assert result == pytest.approx(0.05)

    def test_missing_split_uses_60_40_ratio(self):
        """Without prompt/completion split, total is split 60% input / 40% output."""
        response = _make_llm_response(
            total_tokens=1000, prompt_tokens=None, completion_tokens=None
        )
        mock_pm = _mock_pricing_manager(return_value=0.1)

        with patch(
            "temper_ai.llm.cost_estimator.get_pricing_manager", return_value=mock_pm
        ):
            estimate_cost(response)

        # int(1000 * 0.6) = 600, int(1000 * 0.4) = 400
        mock_pm.get_cost.assert_called_once_with("test-model", 600, 400)

    def test_model_from_response_used(self):
        """Model name in the response is passed to the pricing manager."""
        response = _make_llm_response(
            total_tokens=100,
            prompt_tokens=60,
            completion_tokens=40,
            model="claude-3-opus",
        )
        mock_pm = _mock_pricing_manager()

        with patch(
            "temper_ai.llm.cost_estimator.get_pricing_manager", return_value=mock_pm
        ):
            estimate_cost(response)

        mock_pm.get_cost.assert_called_once_with("claude-3-opus", 60, 40)

    def test_fallback_model_used_when_response_model_none(self):
        """fallback_model is used when response.model is None."""
        response = _make_llm_response(
            total_tokens=100, prompt_tokens=60, completion_tokens=40, model=None
        )
        mock_pm = _mock_pricing_manager()

        with patch(
            "temper_ai.llm.cost_estimator.get_pricing_manager", return_value=mock_pm
        ):
            estimate_cost(response, fallback_model="my-fallback")

        mock_pm.get_cost.assert_called_once_with("my-fallback", 60, 40)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
