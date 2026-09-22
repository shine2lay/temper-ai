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

    def test_local_model_uses_api_equivalent_pricing(self):
        # Self-hosted models still show estimated API-equivalent cost
        cost = estimate_cost("qwen3-next", prompt_tokens=100000, completion_tokens=50000)
        assert cost > 0  # priced based on qwen3 prefix match

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


class TestCurrentAnthropicRates:
    """platform.claude.com/docs/en/about-claude/pricing as of 2026-09-19. Fable
    sat in the table at the Sonnet rate for a while, so every Fable run was
    under-reported 3-5x; these pin the tiers against the published page."""

    def test_fable_is_twice_opus_and_five_times_sonnet(self):
        fable = estimate_cost("claude-fable-5-1", prompt_tokens=1_000_000, completion_tokens=1_000_000)
        opus = estimate_cost("claude-opus-5", prompt_tokens=1_000_000, completion_tokens=1_000_000)
        sonnet = estimate_cost("claude-sonnet-5", prompt_tokens=1_000_000, completion_tokens=1_000_000)
        assert fable == 60.0   # $10 in + $50 out
        assert opus == 30.0    # $5 in + $25 out
        assert sonnet == 12.0  # $2 in + $10 out

    def test_fable_5_1_reads_cache_at_a_fortieth_where_others_read_at_a_tenth(self):
        # 1M cached prompt tokens, nothing else: 0.025 x $10 vs 0.1 x $10
        fable_5_1 = estimate_cost("claude-fable-5-1", prompt_tokens=1_000_000, completion_tokens=0,
                                  cached_prompt_tokens=1_000_000)
        fable_5 = estimate_cost("claude-fable-5", prompt_tokens=1_000_000, completion_tokens=0,
                                cached_prompt_tokens=1_000_000)
        assert fable_5_1 == 0.25
        assert fable_5 == 1.0

    def test_the_opus_4_line_is_five_and_twenty_five_from_4_5_up(self):
        for m in ("claude-opus-4-5-20251101", "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8"):
            assert estimate_cost(m, prompt_tokens=1_000_000, completion_tokens=0) == 5.0, m
        # 4.1 and 4 stay at the retired $15
        assert estimate_cost("claude-opus-4-1", prompt_tokens=1_000_000, completion_tokens=0) == 15.0

    def test_opus_5_5_is_cheaper_than_opus_5_and_says_so_itself(self):
        """5.5 undercuts 5: $4/$20 against $5/$25.

        Every other model in this table is at or above its predecessor, so a
        prefix match onto "claude-opus-5" reads as harmless and over-reports
        every 5.5 run by 25%. It has to be its own row.
        """
        opus_5_5 = estimate_cost("claude-opus-5-5", prompt_tokens=1_000_000, completion_tokens=1_000_000)
        opus_5 = estimate_cost("claude-opus-5", prompt_tokens=1_000_000, completion_tokens=1_000_000)
        assert opus_5_5 == 24.0  # $4 in + $20 out
        assert opus_5_5 < opus_5
        # Dated releases must land on it too, not fall back to the 5 row.
        assert estimate_cost("claude-opus-5-5-20260115", prompt_tokens=1_000_000, completion_tokens=0) == 4.0

    def test_opus_5_5_reads_cache_at_a_twentieth_where_opus_5_reads_at_a_tenth(self):
        """0.05x base, half the usual rate -- and cache reads are most of a long run."""
        opus_5_5 = estimate_cost("claude-opus-5-5", prompt_tokens=1_000_000, completion_tokens=0,
                                 cached_prompt_tokens=1_000_000)
        opus_5 = estimate_cost("claude-opus-5", prompt_tokens=1_000_000, completion_tokens=0,
                               cached_prompt_tokens=1_000_000)
        assert opus_5_5 == 0.20
        assert opus_5 == 0.50

    def test_haiku_4_5_is_one_and_five(self):
        assert estimate_cost("claude-haiku-4-5-20251001", prompt_tokens=1_000_000, completion_tokens=1_000_000) == 6.0
