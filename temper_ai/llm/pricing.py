"""Cost estimation for LLM calls.

Simple dict-based pricing. Models are matched by exact name first,
then by prefix. Falls back to a conservative default.
"""

# Pricing per 1M tokens: (input_cost, output_cost)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4": (30.0, 60.0),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3-mini": (1.10, 4.40),
    # Anthropic
    "claude-sonnet-4": (3.00, 15.0),
    "claude-opus-4": (15.0, 75.0),
    "claude-haiku-4": (0.80, 4.0),
    # Gemini
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.0-flash": (0.10, 0.40),
    # Local / self-hosted — typically free
    "qwen": (0.0, 0.0),
    "llama": (0.0, 0.0),
    "mistral": (0.0, 0.0),
    # Default fallback
    "_default": (3.0, 15.0),
}


def estimate_cost(
    model: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
) -> float:
    """Estimate the cost of an LLM call in USD.

    Uses per-model pricing when available, falls back to default rates.
    If only total_tokens is available, assumes a 60/40 input/output split.
    """
    pricing = _find_pricing(model)
    input_rate, output_rate = pricing

    if prompt_tokens is not None and completion_tokens is not None:
        return round(
            (prompt_tokens / 1_000_000) * input_rate
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
