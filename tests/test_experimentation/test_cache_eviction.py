"""Tests for bounded LRU cache eviction in ExperimentService.

Verifies that:
1. ExperimentService._experiment_cache stays within max_cache_size
2. LRU eviction removes least recently used entries
3. Cache access promotes entries (move_to_end)
"""

import pytest
from collections import OrderedDict

from src.experimentation.service import ExperimentService


class TestExperimentServiceCacheEviction:
    """Verify ExperimentService._experiment_cache stays bounded via LRU."""

    def test_default_max_cache_size(self):
        svc = ExperimentService()
        assert svc._max_cache_size == ExperimentService.MAX_CACHE_SIZE

    def test_custom_max_cache_size(self):
        svc = ExperimentService(max_cache_size=10)
        assert svc._max_cache_size == 10

    def test_cache_is_ordered_dict(self):
        svc = ExperimentService()
        assert isinstance(svc._experiment_cache, OrderedDict)

    def test_cache_put_evicts_oldest_when_full(self):
        svc = ExperimentService(max_cache_size=3)

        # Manually insert via _cache_put to test eviction in isolation
        for i in range(5):
            svc._cache_put(f"exp_{i}", f"experiment_{i}")

        assert len(svc._experiment_cache) == 3
        # Oldest 2 should be evicted
        assert "exp_0" not in svc._experiment_cache
        assert "exp_1" not in svc._experiment_cache
        # Newest 3 should survive
        assert "exp_2" in svc._experiment_cache
        assert "exp_3" in svc._experiment_cache
        assert "exp_4" in svc._experiment_cache

    def test_cache_put_promotes_existing_key(self):
        svc = ExperimentService(max_cache_size=3)

        svc._cache_put("a", "val_a")
        svc._cache_put("b", "val_b")
        svc._cache_put("c", "val_c")

        # Re-insert "a" to promote it to most-recent
        svc._cache_put("a", "val_a_updated")

        # Now insert "d" - should evict "b" (oldest after "a" was promoted)
        svc._cache_put("d", "val_d")

        assert "b" not in svc._experiment_cache
        assert "a" in svc._experiment_cache
        assert "c" in svc._experiment_cache
        assert "d" in svc._experiment_cache

    def test_cache_put_single_item_limit(self):
        svc = ExperimentService(max_cache_size=1)

        svc._cache_put("first", "v1")
        svc._cache_put("second", "v2")

        assert len(svc._experiment_cache) == 1
        assert "first" not in svc._experiment_cache
        assert "second" in svc._experiment_cache
