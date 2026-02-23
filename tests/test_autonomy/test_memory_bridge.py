"""Tests for LearningToMemoryBridge."""

from unittest.mock import MagicMock

import pytest

from temper_ai.autonomy.memory_bridge import (
    APPROVED_STATUS,
    GOALS_NAMESPACE,
    PROCEDURAL_NAMESPACE,
    LearningToMemoryBridge,
)
from temper_ai.memory.constants import MEMORY_TYPE_PROCEDURAL
from temper_ai.memory.registry import MemoryProviderRegistry
from temper_ai.memory.service import MemoryService


@pytest.fixture(autouse=True)
def reset_registry():
    MemoryProviderRegistry.reset_for_testing()
    yield
    MemoryProviderRegistry.reset_for_testing()


def _make_pattern(
    pid: str = "p1",
    pattern_type: str = "agent_performance",
    title: str = "Optimize model",
    description: str = "Use smaller model for simple tasks",
    recommendation: str = "Switch to gpt-4o-mini",
    confidence: float = 0.85,
    status: str = "active",
):
    p = MagicMock()
    p.id = pid
    p.pattern_type = pattern_type
    p.title = title
    p.description = description
    p.recommendation = recommendation
    p.confidence = confidence
    p.status = status
    return p


def _make_goal(
    gid: str = "g1",
    goal_type: str = "performance",
    title: str = "Reduce latency",
    description: str = "Reduce P99 latency by 30%",
    proposed_actions: list = None,
    status: str = "approved",
):
    g = MagicMock()
    g.id = gid
    g.goal_type = goal_type
    g.title = title
    g.description = description
    g.proposed_actions = proposed_actions or ["optimize queries"]
    g.status = status
    return g


class TestSyncPatternsToMemory:
    def test_sync_active_patterns(self):
        learning_store = MagicMock()
        learning_store.list_patterns.return_value = [
            _make_pattern(pid="p1", confidence=0.9),
            _make_pattern(pid="p2", confidence=0.8),
        ]
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        count = bridge.sync_patterns_to_memory()
        assert count == 2
        scope = svc.build_scope(namespace=PROCEDURAL_NAMESPACE)
        entries = svc.list_memories(scope, memory_type=MEMORY_TYPE_PROCEDURAL)
        assert len(entries) == 2

    def test_filters_by_confidence(self):
        learning_store = MagicMock()
        learning_store.list_patterns.return_value = [
            _make_pattern(pid="p1", confidence=0.9),
            _make_pattern(pid="p2", confidence=0.3),
        ]
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        count = bridge.sync_patterns_to_memory(min_confidence=0.7)
        assert count == 1

    def test_custom_min_confidence(self):
        learning_store = MagicMock()
        learning_store.list_patterns.return_value = [
            _make_pattern(pid="p1", confidence=0.5),
        ]
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        count = bridge.sync_patterns_to_memory(min_confidence=0.4)
        assert count == 1

    def test_deduplication(self):
        learning_store = MagicMock()
        learning_store.list_patterns.return_value = [
            _make_pattern(pid="p1", confidence=0.9),
        ]
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        first = bridge.sync_patterns_to_memory()
        second = bridge.sync_patterns_to_memory()
        assert first == 1
        assert second == 0

    def test_no_active_patterns(self):
        learning_store = MagicMock()
        learning_store.list_patterns.return_value = []
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        count = bridge.sync_patterns_to_memory()
        assert count == 0

    def test_pattern_metadata_stored(self):
        learning_store = MagicMock()
        learning_store.list_patterns.return_value = [
            _make_pattern(pid="p1", pattern_type="cost", confidence=0.9),
        ]
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        bridge.sync_patterns_to_memory()
        scope = svc.build_scope(namespace=PROCEDURAL_NAMESPACE)
        entries = svc.list_memories(scope, memory_type=MEMORY_TYPE_PROCEDURAL)
        assert len(entries) == 1
        assert entries[0].metadata["pattern_id"] == "p1"
        assert entries[0].metadata["pattern_type"] == "cost"
        assert entries[0].metadata["source"] == "learning_bridge"

    def test_pattern_content_formatted(self):
        learning_store = MagicMock()
        learning_store.list_patterns.return_value = [
            _make_pattern(
                pid="p1",
                pattern_type="failure",
                title="Handle timeouts",
                description="Add retry logic",
                recommendation="Use exponential backoff",
                confidence=0.9,
            ),
        ]
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        bridge.sync_patterns_to_memory()
        scope = svc.build_scope(namespace=PROCEDURAL_NAMESPACE)
        entries = svc.list_memories(scope, memory_type=MEMORY_TYPE_PROCEDURAL)
        content = entries[0].content
        assert "[failure]" in content
        assert "Handle timeouts" in content
        assert "Add retry logic" in content
        assert "exponential backoff" in content


class TestSyncGoalsToMemory:
    def test_sync_approved_goals(self):
        learning_store = MagicMock()
        goal_store = MagicMock()
        goal_store.list_proposals.return_value = [
            _make_goal(gid="g1"),
            _make_goal(gid="g2"),
        ]
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        count = bridge.sync_goals_to_memory(goal_store)
        assert count == 2
        goal_store.list_proposals.assert_called_once_with(status=APPROVED_STATUS)

    def test_goal_deduplication(self):
        learning_store = MagicMock()
        goal_store = MagicMock()
        goal_store.list_proposals.return_value = [_make_goal(gid="g1")]
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        first = bridge.sync_goals_to_memory(goal_store)
        second = bridge.sync_goals_to_memory(goal_store)
        assert first == 1
        assert second == 0

    def test_no_approved_goals(self):
        learning_store = MagicMock()
        goal_store = MagicMock()
        goal_store.list_proposals.return_value = []
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        count = bridge.sync_goals_to_memory(goal_store)
        assert count == 0

    def test_goal_metadata_stored(self):
        learning_store = MagicMock()
        goal_store = MagicMock()
        goal_store.list_proposals.return_value = [
            _make_goal(gid="g1", goal_type="reliability"),
        ]
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        bridge.sync_goals_to_memory(goal_store)
        scope = svc.build_scope(namespace=GOALS_NAMESPACE)
        entries = svc.list_memories(scope, memory_type=MEMORY_TYPE_PROCEDURAL)
        assert len(entries) == 1
        assert entries[0].metadata["goal_id"] == "g1"
        assert entries[0].metadata["goal_type"] == "reliability"
        assert entries[0].metadata["source"] == "goal_bridge"

    def test_goal_content_formatted(self):
        learning_store = MagicMock()
        goal_store = MagicMock()
        goal_store.list_proposals.return_value = [
            _make_goal(
                gid="g1",
                goal_type="performance",
                title="Speed up pipeline",
                description="Reduce end-to-end time",
                proposed_actions=["cache results", "parallel stages"],
            ),
        ]
        svc = MemoryService(provider_name="in_memory")
        bridge = LearningToMemoryBridge(learning_store, memory_service=svc)
        bridge.sync_goals_to_memory(goal_store)
        scope = svc.build_scope(namespace=GOALS_NAMESPACE)
        entries = svc.list_memories(scope, memory_type=MEMORY_TYPE_PROCEDURAL)
        content = entries[0].content
        assert "[performance]" in content
        assert "Speed up pipeline" in content
        assert "cache results" in content


class TestLazyMemoryService:
    def test_creates_service_when_not_provided(self):
        learning_store = MagicMock()
        learning_store.list_patterns.return_value = []
        bridge = LearningToMemoryBridge(learning_store, memory_service=None)
        count = bridge.sync_patterns_to_memory()
        assert count == 0
        assert bridge._memory_service is not None
