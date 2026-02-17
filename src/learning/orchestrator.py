"""Mining orchestrator — runs all miners, deduplicates, persists."""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from src.learning.miners.agent_performance import AgentPerformanceMiner
from src.learning.miners.base import BaseMiner, DEFAULT_LOOKBACK_HOURS
from src.learning.miners.collaboration_patterns import CollaborationPatternMiner
from src.learning.miners.cost_patterns import CostPatternMiner
from src.learning.miners.failure_patterns import FailurePatternMiner
from src.learning.miners.model_effectiveness import ModelEffectivenessMiner
from src.learning.models import STATUS_COMPLETED, LearnedPattern, MiningRun
from src.learning.store import LearningStore

logger = logging.getLogger(__name__)

_DEDUP_KEY_LENGTH = 16

ALL_MINERS: List[BaseMiner] = [
    AgentPerformanceMiner(),
    ModelEffectivenessMiner(),
    FailurePatternMiner(),
    CostPatternMiner(),
    CollaborationPatternMiner(),
]


class MiningOrchestrator:
    """Runs all miners, deduplicates, persists, optionally publishes to MemoryService."""

    def __init__(
        self,
        store: LearningStore,
        miners: Optional[List[BaseMiner]] = None,
        memory_service: Optional[object] = None,
    ) -> None:
        self.store = store
        self.miners = miners if miners is not None else ALL_MINERS
        self.memory_service = memory_service

    def run_mining(self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS) -> MiningRun:
        """Execute all miners, deduplicate results, persist, return run record."""
        run = MiningRun(id=uuid.uuid4().hex, started_at=datetime.now(timezone.utc))
        all_patterns: List[LearnedPattern] = []
        miner_stats: dict = {}

        for miner in self.miners:
            try:
                found = miner.mine(lookback_hours=lookback_hours)
                all_patterns.extend(found)
                miner_stats[miner.pattern_type] = len(found)
            except Exception as exc:
                logger.warning("Miner %s failed: %s", miner.pattern_type, exc)
                miner_stats[miner.pattern_type] = f"error: {exc}"

        deduped = self._deduplicate(all_patterns)
        for pattern in deduped:
            self.store.save_pattern(pattern)

        self._publish_to_memory(deduped)

        run.completed_at = datetime.now(timezone.utc)
        run.status = STATUS_COMPLETED
        run.patterns_found = len(all_patterns)
        run.patterns_new = len(deduped)
        run.novelty_score = _calc_novelty(len(all_patterns), len(deduped))
        run.miner_stats = miner_stats
        self.store.save_mining_run(run)
        return run

    def _deduplicate(self, patterns: List[LearnedPattern]) -> List[LearnedPattern]:
        """Remove patterns that already exist (by type+title hash)."""
        existing = self.store.list_patterns(status=None, limit=1000)
        existing_keys = {_pattern_key(p) for p in existing}
        new_patterns: List[LearnedPattern] = []
        for p in patterns:
            if _pattern_key(p) not in existing_keys:
                new_patterns.append(p)
                existing_keys.add(_pattern_key(p))
        return new_patterns

    def _publish_to_memory(self, patterns: List[LearnedPattern]) -> None:
        """Store patterns in MemoryService shared namespace if available."""
        if self.memory_service is None or not patterns:
            return
        try:
            svc = self.memory_service
            for p in patterns:
                if hasattr(svc, "store"):
                    svc.store(
                        content=f"[{p.pattern_type}] {p.title}: {p.description}",
                        memory_type="procedural",
                        namespace="learning",
                    )
        except Exception as exc:
            logger.warning("Failed to publish patterns to MemoryService: %s", exc)


def _pattern_key(p: LearnedPattern) -> str:
    """Compute a dedup key from pattern type + title."""
    raw = f"{p.pattern_type}:{p.title}"
    return hashlib.sha256(raw.encode()).hexdigest()[:_DEDUP_KEY_LENGTH]


def _calc_novelty(total: int, new: int) -> float:
    """Compute novelty score (0.0–1.0). Higher means more new patterns."""
    if total == 0:
        return 0.0
    return new / total
