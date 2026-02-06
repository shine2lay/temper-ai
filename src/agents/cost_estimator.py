"""Cost estimation for LLM calls.

Delegates to the pricing manager for model-specific pricing from
config/model_pricing.yaml.
"""
from typing import TYPE_CHECKING

from src.agents.pricing import get_pricing_manager

if TYPE_CHECKING:
    from src.agents.llm.base import LLMResponse


def estimate_cost(llm_response: "LLMResponse", fallback_model: str = "unknown") -> float:
    """Estimate cost of an LLM call using configured pricing.

    Uses model-specific pricing from config/model_pricing.yaml.
    Falls back to default pricing for unknown models.

    Args:
        llm_response: LLM response with token counts
        fallback_model: Model name to use if not available in response

    Returns:
        Estimated cost in USD
    """
    if not llm_response.total_tokens:
        return 0.0

    pricing = get_pricing_manager()

    model = llm_response.model or fallback_model

    input_tokens = llm_response.prompt_tokens or 0
    output_tokens = llm_response.completion_tokens or 0

    # If split not available, estimate from total_tokens
    if input_tokens == 0 and output_tokens == 0 and llm_response.total_tokens:
        # Rough estimate: assume 60% input, 40% output (typical for agent interactions)
        total = llm_response.total_tokens
        input_tokens = int(total * 0.6)
        output_tokens = int(total * 0.4)

    return pricing.get_cost(model, input_tokens, output_tokens)
