"""Dialogue-based collaboration strategy — backward-compat shim.

Deprecated: Use MultiRoundStrategy(mode='dialogue') directly.

This module now re-exports MultiRoundStrategy as DialogueOrchestrator
for backward compatibility. All multi-round dialogue behavior is provided
by MultiRoundStrategy.
"""

import logging
import warnings
from typing import Any, Optional

from temper_ai.agent.strategies.multi_round import (
    CommunicationHistory,
    CommunicationRound,
    MultiRoundConfig,
    MultiRoundStrategy,
)

logger = logging.getLogger(__name__)

# Re-export aliases for backward compatibility
DialogueRound = CommunicationRound
DialogueHistory = CommunicationHistory

DEFAULT_MAX_ROUNDS = 3
DEFAULT_CONVERGENCE_THRESHOLD = 0.85


class DialogueOrchestrator(MultiRoundStrategy):
    """Deprecated. Use MultiRoundStrategy(mode='dialogue').

    This class is a thin wrapper that defaults to dialogue mode and
    accepts the original DialogueOrchestrator constructor parameters.
    """

    # Inherit class-level embedding model from MultiRoundStrategy

    @classmethod
    def warm_up(cls) -> bool:
        """Preload the SentenceTransformer model for semantic convergence."""
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
            if not cls._embedding_model_loaded:
                logger.info("Loading sentence-transformers model (paraphrase-MiniLM-L6-v2)...")
                cls._embedding_model = SentenceTransformer('paraphrase-MiniLM-L6-v2')
                cls._embedding_model_loaded = True
            return True
        except ImportError:
            logger.warning(
                "sentence-transformers not available for warm_up. "
                "Install with: pip install sentence-transformers"
            )
            return False
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to warm up embedding model: %s", e)
            return False

    def __init__(  # noqa: params — legacy compat, delegates to MultiRoundConfig
        self,
        config: Optional[MultiRoundConfig] = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        convergence_threshold: float = DEFAULT_CONVERGENCE_THRESHOLD,
        cost_budget_usd: Optional[float] = None,
        min_rounds: int = 1,
        use_semantic_convergence: bool = True,
        context_strategy: str = "full",
        context_window_size: int = 2,
        use_merit_weighting: bool = False,
        merit_domain: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        warnings.warn(
            "DialogueOrchestrator is deprecated, use MultiRoundStrategy(mode='dialogue')",
            DeprecationWarning,
            stacklevel=2,
        )
        # Support both new and legacy calling styles
        if config is None:
            config = MultiRoundConfig(
                max_rounds=max_rounds,
                min_rounds=min_rounds,
                convergence_threshold=convergence_threshold,
                use_semantic_convergence=use_semantic_convergence,
                context_strategy=context_strategy,
                context_window_size=context_window_size,
                cost_budget_usd=cost_budget_usd,
                use_merit_weighting=use_merit_weighting,
                merit_domain=merit_domain,
            )
        super().__init__(mode="dialogue", config=config, **kwargs)
