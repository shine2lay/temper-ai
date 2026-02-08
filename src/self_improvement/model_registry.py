"""
ModelRegistry for M5 Self-Improvement system.

Maintains registry of available LLM models (primarily Ollama models for MVP).
Used by strategies like OllamaModelSelectionStrategy to generate config variants.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.self_improvement.constants import (
    CONTEXT_WINDOW_4K,
    CONTEXT_WINDOW_8K,
    CONTEXT_WINDOW_32K,
    MODEL_TIER_MEDIUM_MAX,
    MODEL_TIER_SMALL_MAX,
)


@dataclass
class ModelMetadata:
    """
    Metadata for a model available in the registry.

    Attributes:
        name: Model identifier (e.g., "llama3.1:8b", "qwen2.5:32b")
        provider: Model provider (e.g., "ollama", "openai", "anthropic")
        size: Model parameter count (e.g., "8B", "32B", "3.8B")
        expected_quality: Qualitative quality rating ("low", "medium", "high", "highest")
        expected_speed: Relative speed category ("very_fast", "fast", "medium", "slow")
        context_window: Maximum context window size in tokens
        notes: Additional notes about the model
    """
    name: str
    provider: str
    size: str
    expected_quality: str
    expected_speed: str = "medium"
    context_window: int = CONTEXT_WINDOW_4K
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "provider": self.provider,
            "size": self.size,
            "expected_quality": self.expected_quality,
            "expected_speed": self.expected_speed,
            "context_window": self.context_window,
            "notes": self.notes,
        }


class ModelRegistry:
    """
    Registry of available LLM models.

    Maintains a catalog of models that can be used for experimentation.
    Strategies query this registry to discover available models and their
    characteristics when generating config variants.

    Example:
        registry = ModelRegistry()
        small_models = registry.get_by_quality("medium")
        fast_models = registry.get_by_speed("very_fast")
        all_ollama = registry.get_by_provider("ollama")
    """

    def __init__(self):
        """Initialize registry with built-in Ollama models."""
        self._models: Dict[str, ModelMetadata] = {}
        self._load_default_models()

    def _load_default_models(self):
        """Load default Ollama models for M5 MVP."""
        # Based on M5 architecture doc (line 1571-1586)
        default_models = [
            ModelMetadata(
                name="phi3:mini",
                provider="ollama",
                size="3.8B",
                expected_quality="medium",
                expected_speed="very_fast",
                context_window=CONTEXT_WINDOW_4K,
                notes="Small, fast model. Good for simple tasks."
            ),
            ModelMetadata(
                name="llama3.1:8b",
                provider="ollama",
                size="8B",
                expected_quality="high",
                expected_speed="fast",
                context_window=CONTEXT_WINDOW_8K,
                notes="Balanced model. Good default choice."
            ),
            ModelMetadata(
                name="mistral:7b",
                provider="ollama",
                size="7B",
                expected_quality="high",
                expected_speed="fast",
                context_window=CONTEXT_WINDOW_8K,
                notes="High quality, efficient model."
            ),
            ModelMetadata(
                name="qwen2.5:32b",
                provider="ollama",
                size="32B",
                expected_quality="highest",
                expected_speed="slow",
                context_window=CONTEXT_WINDOW_32K,
                notes="Large, high-quality model. Best accuracy."
            ),
        ]

        for model in default_models:
            self.register(model)

    def register(self, model: ModelMetadata):
        """
        Register a new model in the registry.

        Args:
            model: ModelMetadata instance
        """
        self._models[model.name] = model

    def get(self, name: str) -> Optional[ModelMetadata]:
        """
        Get model by name.

        Args:
            name: Model name (e.g., "llama3.1:8b")

        Returns:
            ModelMetadata if found, None otherwise
        """
        return self._models.get(name)

    def get_all(self) -> List[ModelMetadata]:
        """Get all registered models."""
        return list(self._models.values())

    def get_by_provider(self, provider: str) -> List[ModelMetadata]:
        """
        Get models by provider.

        Args:
            provider: Provider name (e.g., "ollama", "openai")

        Returns:
            List of models from that provider
        """
        return [m for m in self._models.values() if m.provider == provider]

    def get_by_quality(self, quality: str) -> List[ModelMetadata]:
        """
        Get models by quality rating.

        Args:
            quality: Quality rating ("medium", "high", "highest")

        Returns:
            List of models with that quality rating
        """
        return [m for m in self._models.values() if m.expected_quality == quality]

    def get_by_speed(self, speed: str) -> List[ModelMetadata]:
        """
        Get models by speed category.

        Args:
            speed: Speed category ("very_fast", "fast", "medium", "slow")

        Returns:
            List of models in that speed category
        """
        return [m for m in self._models.values() if m.expected_speed == speed]

    def get_tiers(self) -> Dict[str, List[ModelMetadata]]:
        """
        Get models grouped by size tiers.

        Returns:
            Dictionary mapping tier name to list of models:
            - "small": < 5B parameters
            - "medium": 5B - 15B parameters
            - "large": > 15B parameters
        """
        tiers = {"small": [], "medium": [], "large": []}

        for model in self._models.values():
            # Extract numeric size (e.g., "8B" -> 8)
            size_str = model.size.replace("B", "")
            try:
                size_float = float(size_str)
                if size_float < MODEL_TIER_SMALL_MAX:
                    tiers["small"].append(model)
                elif size_float <= MODEL_TIER_MEDIUM_MAX:
                    tiers["medium"].append(model)
                else:
                    tiers["large"].append(model)
            except ValueError:
                # If size can't be parsed, skip
                continue

        return tiers

    def exists(self, name: str) -> bool:
        """Check if model exists in registry."""
        return name in self._models

    def count(self) -> int:
        """Get total number of registered models."""
        return len(self._models)
