"""Tests for LLM cost estimation."""

from temper_ai.llm.pricing import estimate_cost


class TestEstimateCost:
    def test_exact_model_match(self):
        cost = estimate_cost("gpt-4o", prompt_tokens=1000, completion_tokens=500)
        # gpt-4o: $2.50/1M input, $10.0/1M output
        expected = (1000 / 1_000_000) * 2.50 + (500 / 1_000_000) * 10.0
        assert cost == round(expected, 6)

    def test_prefix_match(self):
        # "gpt-4.1-mini-2025-04" should match "gpt-4.1-mini" prefix
        cost = estimate_cost("gpt-4.1-mini-2025-04", prompt_tokens=1000, completion_tokens=500)
        # gpt-4.1-mini: $0.40/1M input, $1.60/1M output
        expected = (1000 / 1_000_000) * 0.40 + (500 / 1_000_000) * 1.60
        assert cost == round(expected, 6)

    def test_default_fallback(self):
        cost = estimate_cost("unknown-model-xyz", prompt_tokens=1_000_000, completion_tokens=500_000)
        # Default: $3/1M input, $15/1M output
        expected = 3.0 + (500_000 / 1_000_000) * 15.0
        assert cost == round(expected, 6)

    def test_total_tokens_only(self):
        # When only total_tokens available, assumes 60/40 split
        cost = estimate_cost("gpt-4o", total_tokens=1000)
        input_est = 600
        output_est = 400
        expected = (input_est / 1_000_000) * 2.50 + (output_est / 1_000_000) * 10.0
        assert cost == round(expected, 6)

    def test_no_tokens(self):
        cost = estimate_cost("gpt-4o")
        assert cost == 0.0

    def test_zero_tokens(self):
        cost = estimate_cost("gpt-4o", prompt_tokens=0, completion_tokens=0)
        assert cost == 0.0

    def test_local_model_free(self):
        # "qwen" prefix models are priced at $0
        cost = estimate_cost("qwen3-next", prompt_tokens=100000, completion_tokens=50000)
        assert cost == 0.0

    def test_prompt_and_completion_takes_precedence(self):
        # If both specific and total are provided, specific wins
        cost_specific = estimate_cost(
            "gpt-4o", prompt_tokens=800, completion_tokens=200, total_tokens=1000,
        )
        cost_total = estimate_cost("gpt-4o", total_tokens=1000)
        # These should differ because specific uses 800/200, total uses 600/400
        assert cost_specific != cost_total

    def test_large_token_count(self):
        cost = estimate_cost("gpt-4", prompt_tokens=1_000_000, completion_tokens=1_000_000)
        # gpt-4: $30/1M input, $60/1M output
        assert cost == round(30.0 + 60.0, 6)
