"""Convergence detection for stage re-execution.

Determines whether a stage's output has stabilised across iterations,
enabling automatic termination of convergence loops when further
re-execution would not produce meaningfully different results.
"""

import hashlib
import logging
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.stage._schemas import ConvergenceConfig

logger = logging.getLogger(__name__)


class StageConvergenceDetector:
    """Detect when sequential stage outputs have converged.

    Supports two comparison methods:
    - ``exact_hash``: SHA-256 digest comparison (outputs must be identical).
    - ``semantic``:   SequenceMatcher ratio comparison against a configurable
                      similarity threshold.
    """

    def __init__(self, config: "ConvergenceConfig") -> None:
        self._config = config

    # ── Public API ──

    def has_converged(self, previous_output: str, current_output: str) -> bool:
        """Return True when *previous_output* and *current_output* are
        considered equivalent under the configured comparison method.
        """
        if self._config.method == "semantic":
            return self._semantic_compare(previous_output, current_output)
        return self._hash_compare(previous_output, current_output)

    # ── Private helpers ──

    @staticmethod
    def _hash_compare(a: str, b: str) -> bool:
        """Return True when both strings produce identical SHA-256 digests."""
        hash_a = hashlib.sha256(a.encode("utf-8")).hexdigest()
        hash_b = hashlib.sha256(b.encode("utf-8")).hexdigest()
        return hash_a == hash_b

    def _semantic_compare(self, a: str, b: str) -> bool:
        """Return True when the SequenceMatcher ratio meets the threshold."""
        ratio = SequenceMatcher(None, a, b).ratio()
        logger.debug(
            "Semantic convergence ratio=%.4f threshold=%.4f",
            ratio,
            self._config.similarity_threshold,
        )
        return ratio >= self._config.similarity_threshold
