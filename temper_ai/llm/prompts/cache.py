"""
Template caching for PromptEngine.

Provides LRU cache for compiled Jinja2 templates with statistics tracking.
"""

from typing import Any

from jinja2 import Template
from jinja2.sandbox import ImmutableSandboxedEnvironment

from temper_ai.llm.cache.constants import DEFAULT_CACHE_SIZE


class TemplateCacheManager:
    """Manages template compilation cache with LRU eviction.

    Caches compiled Jinja2 templates to avoid recompilation overhead.
    Provides cache statistics for monitoring and optimization.
    """

    def __init__(self, cache_size: int = DEFAULT_CACHE_SIZE):
        """
        Initialize cache manager.

        Args:
            cache_size: Maximum number of compiled templates to cache (default from cache constants)
        """
        self._template_cache: dict[str, Template] = {}
        self._cache_size = cache_size
        self._cache_hits = 0
        self._cache_misses = 0

    def get_or_compile(
        self, template_str: str, sandbox_env: ImmutableSandboxedEnvironment
    ) -> Template:
        """
        Get cached template or compile and cache it.

        Args:
            template_str: Template string to compile
            sandbox_env: Jinja2 sandboxed environment for compilation

        Returns:
            Compiled Jinja2 template
        """
        # Check cache for compiled template
        jinja_template = self._template_cache.get(template_str)

        if jinja_template is None:
            # Cache miss - compile template
            self._cache_misses += 1
            jinja_template = sandbox_env.from_string(template_str)

            # Add to cache (FIFO eviction if full)
            if len(self._template_cache) >= self._cache_size:
                # Remove oldest entry (simple FIFO since dicts are ordered in Python 3.7+)
                oldest_key = next(iter(self._template_cache))
                del self._template_cache[oldest_key]

            self._template_cache[template_str] = jinja_template
        else:
            # Cache hit
            self._cache_hits += 1

        return jinja_template

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get template cache statistics.

        Returns:
            Dictionary with cache statistics including hits, misses, size, and hit rate.

        Examples:
            >>> cache = TemplateCacheManager()
            >>> cache.get_or_compile("Hello {{name}}!", env)
            >>> cache.get_or_compile("Hello {{name}}!", env)
            >>> stats = cache.get_cache_stats()
            >>> stats["cache_hits"]
            1
            >>> stats["cache_hit_rate"]
            0.5
        """
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total_requests if total_requests > 0 else 0.0

        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "total_requests": total_requests,
            "cache_hit_rate": hit_rate,
            "cache_size": len(self._template_cache),
            "cache_capacity": self._cache_size,
        }

    def clear_cache(self) -> None:
        """
        Clear the template cache and reset hit/miss counters.

        Useful for testing or when template content needs to be invalidated.

        Examples:
            >>> cache = TemplateCacheManager()
            >>> cache.get_or_compile("Hello {{name}}!", env)
            >>> cache.clear_cache()
            >>> stats = cache.get_cache_stats()
            >>> stats["cache_size"]
            0
        """
        self._template_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
