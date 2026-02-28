"""Tests for cost_estimator module (src/agents/cost_estimator.py).

Tests cover:
- estimate_cost with split tokens (prompt + completion)
- estimate_cost with total_tokens only (60/40 split estimation)
- estimate_cost with zero tokens (returns 0.0)
- estimate_cost with unknown model (uses default pricing)
- estimate_cost with fallback_model parameter
"""

from unittest.mock import patch

from temper_ai.llm.cost_estimator import estimate_cost
from temper_ai.llm.providers.base import LLMResponse

_SENTINEL = object()


def _make_response(
    prompt_tokens=None,
    completion_tokens=None,
    total_tokens=None,
    model=_SENTINEL,
):
    """Create an LLMResponse for testing."""
    return LLMResponse(
        content="test",
        model="test-model" if model is _SENTINEL else model,
        provider="test",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


class TestEstimateCost:
    """Tests for the estimate_cost function."""

    def test_zero_tokens_returns_zero(self):
        response = _make_response(total_tokens=0)
        assert estimate_cost(response) == 0.0

    def test_none_tokens_returns_zero(self):
        response = _make_response(total_tokens=None)
        assert estimate_cost(response) == 0.0

    def test_split_tokens_delegates_to_pricing(self):
        response = _make_response(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="gpt-4",
        )
        with patch("temper_ai.llm.cost_estimator.get_pricing_manager") as mock_pm:
            mock_pm.return_value.get_cost.return_value = 0.05
            cost = estimate_cost(response)
            mock_pm.return_value.get_cost.assert_called_once_with("gpt-4", 100, 50)
            assert cost == 0.05

    def test_total_only_estimates_split(self):
        response = _make_response(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=1000,
            model="gpt-4",
        )
        with patch("temper_ai.llm.cost_estimator.get_pricing_manager") as mock_pm:
            mock_pm.return_value.get_cost.return_value = 0.03
            cost = estimate_cost(response)
            # Should estimate 60% input (600), 40% output (400)
            mock_pm.return_value.get_cost.assert_called_once_with("gpt-4", 600, 400)
            assert cost == 0.03

    def test_fallback_model_used_when_model_is_none(self):
        response = _make_response(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model=None,
        )
        with patch("temper_ai.llm.cost_estimator.get_pricing_manager") as mock_pm:
            mock_pm.return_value.get_cost.return_value = 0.01
            estimate_cost(response, fallback_model="default-model")
            mock_pm.return_value.get_cost.assert_called_once_with(
                "default-model", 100, 50
            )

    def test_model_from_response_takes_precedence(self):
        response = _make_response(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            model="claude-3",
        )
        with patch("temper_ai.llm.cost_estimator.get_pricing_manager") as mock_pm:
            mock_pm.return_value.get_cost.return_value = 0.02
            estimate_cost(response, fallback_model="fallback")
            mock_pm.return_value.get_cost.assert_called_once_with("claude-3", 100, 50)
