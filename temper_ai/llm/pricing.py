"""Cost estimation for LLM calls.

Simple dict-based pricing. Models are matched by exact name first,
then by prefix. Falls back to a conservative default.
"""

# Pricing per 1M tokens: (input_cost, output_cost)
# Uses API pricing to show equivalent cost even for self-hosted models.
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # --- OpenAI ---
    "gpt-4.5": (75.0, 150.0),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-4": (30.0, 60.0),
    "o4-mini": (1.10, 4.40),
    "o3": (10.0, 40.0),
    "o3-mini": (1.10, 4.40),
    # --- Anthropic ---
    # Prefix match, longest wins: "claude-opus-5" does not start with "claude-opus-4",
    # so every model past the 4 series fell through to _default (3/15) and was
    # mispriced in both directions until listed here.
    # Rates from platform.claude.com/docs/en/about-claude/pricing, 2026-09-19.
    # Fable is the top tier at twice Opus; it was listed here at the Sonnet
    # rate and under-reported every Fable run by 3-5x.
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    # Opus 5.5 is CHEAPER than Opus 5 ($4/$20 against $5/$25), so inheriting
    # by prefix is wrong in the direction that matters: it over-reports every
    # 5.5 run by 25%. Listed explicitly, never inferred from the family.
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4": (3.00, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4": (0.80, 4.0),
    "claude-haiku-3": (0.25, 1.25),
    # --- Google Gemini ---
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.0-flash": (0.10, 0.40),
    # --- DeepSeek ---
    "deepseek-r1": (0.55, 2.19),
    "deepseek-v3": (0.27, 1.10),
    "deepseek-chat": (0.27, 1.10),
    "deepseek": (0.27, 1.10),
    # --- Mistral (API) ---
    "mistral-large": (2.00, 6.00),
    "mistral-small": (0.10, 0.30),
    "codestral": (0.30, 0.90),
    "mistral": (0.30, 0.90),
    # --- xAI ---
    "grok-3": (3.00, 15.0),
    "grok-3-mini": (0.30, 0.50),
    "grok-2": (2.00, 10.0),
    "grok": (2.00, 10.0),
    # --- Cohere ---
    "command-r-plus": (2.50, 10.0),
    "command-r": (0.15, 0.60),
    "command": (0.15, 0.60),
    # --- Open-weight models (API-hosted pricing via Together/Fireworks) ---
    # Qwen
    "qwen3": (0.90, 0.90),       # ~72B+ class hosted API
    "qwen2.5": (0.90, 0.90),
    "qwen": (0.90, 0.90),
    # Llama
    "llama-4": (0.27, 0.85),     # Llama 4 Maverick class
    "llama-3.1-405b": (3.50, 3.50),
    "llama-3.1-70b": (0.88, 0.88),
    "llama-3.1-8b": (0.18, 0.18),
    "llama-3": (0.88, 0.88),     # Default to 70B class
    "llama": (0.88, 0.88),
    # --- Default fallback (mid-tier model) ---
    "_default": (3.0, 15.0),
}


# Anthropic's cache multipliers, which OpenAI and Gemini approximately share:
# reading a cached prefix costs a tenth of fresh input, writing one costs a
# quarter extra. Priced at the full input rate, a well-cached agent run reads
# as roughly ten times its real cost.
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25

# Fable 5.1 and Mythos 5.1 read cache at 0.025x base input (the pricing page's
# footnote); the other models keep the 0.1x above. Prefix-matched like the
# rates. For an agent run, where nearly every call re-reads the same prefix,
# this is most of the difference between Fable 5 and 5.1.
_CACHE_READ_OVERRIDES: dict[str, float] = {
    "claude-fable-5-1": 0.025,
    "claude-mythos-5-1": 0.025,
    # Opus 5.5 reads cache at 0.05x base ($0.20 against $4), half the usual
    # rate. An agent run re-reads its prefix on nearly every call, so this is
    # most of what a long run costs.
    "claude-opus-5-5": 0.05,
}


def cache_read_multiplier(model: str) -> float:
    best: str | None = None
    for key in _CACHE_READ_OVERRIDES:
        if model.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return _CACHE_READ_OVERRIDES[best] if best else CACHE_READ_MULTIPLIER


def estimate_cost(
    model: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    cached_prompt_tokens: int | None = None,
    cache_write_tokens: int | None = None,
) -> float:
    """Estimate the cost of an LLM call in USD.

    Uses per-model pricing when available, falls back to default rates.
    If only total_tokens is available, assumes a 60/40 input/output split.
    Cached input, when the provider reports it, is priced as cached.
    """
    pricing = _find_pricing(model)
    input_rate, output_rate = pricing

    if prompt_tokens is not None and completion_tokens is not None:
        cached = cached_prompt_tokens or 0
        written = cache_write_tokens or 0
        fresh = max(prompt_tokens - cached - written, 0)
        return round(
            (fresh / 1_000_000) * input_rate
            + (cached / 1_000_000) * input_rate * cache_read_multiplier(model)
            + (written / 1_000_000) * input_rate * CACHE_WRITE_MULTIPLIER
            + (completion_tokens / 1_000_000) * output_rate,
            6,
        )

    if total_tokens is not None:
        input_est = int(total_tokens * 0.6)
        output_est = total_tokens - input_est
        return round(
            (input_est / 1_000_000) * input_rate
            + (output_est / 1_000_000) * output_rate,
            6,
        )

    return 0.0


def _find_pricing(model: str) -> tuple[float, float]:
    """Find pricing for a model — exact match, then longest prefix match, then default."""
    if model in _MODEL_PRICING:
        return _MODEL_PRICING[model]

    # Find the longest matching prefix (most specific match)
    best_key: str | None = None
    for key in _MODEL_PRICING:
        if key != "_default" and model.startswith(key):
            if best_key is None or len(key) > len(best_key):
                best_key = key

    if best_key is not None:
        return _MODEL_PRICING[best_key]

    return _MODEL_PRICING["_default"]
