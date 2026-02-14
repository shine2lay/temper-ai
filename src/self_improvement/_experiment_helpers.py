"""Helper functions extracted from ExperimentOrchestrator to reduce class size.

These are internal implementation details - use ExperimentOrchestrator's public API.
"""
import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from sqlmodel import func, select

from src.self_improvement.data_models import (
    ExecutionResult,
    SelfImprovementExperiment,
    SIOptimizationConfig,
    utcnow,
)
from src.self_improvement.statistical_analyzer import (
    VariantResults,
)
from src.self_improvement.storage.experiment_models import (
    M5ExecutionResult,
    M5Experiment,
)

logger = logging.getLogger(__name__)


@dataclass
class ExperimentResultData:
    """Bundle of experiment result parameters for recording."""
    experiment_id: str
    variant_id: str
    execution_id: str
    quality_score: Optional[float]
    speed_seconds: Optional[float]
    cost_usd: Optional[float]
    success: Optional[bool]
    extra_metrics: Optional[Dict[str, float]]


@dataclass
class ExperimentCreationData:
    """Bundle of experiment creation parameters."""
    agent_name: str
    experiment_id: str
    control_config: SIOptimizationConfig
    variant_configs: List[SIOptimizationConfig]
    target: int
    proposal_id: Optional[str]
    extra_metadata: Optional[Dict[str, Any]]

# ID truncation lengths
EXPERIMENT_ID_UUID_LENGTH = 8
RESULT_ID_UUID_LENGTH = 12

# Hash constants
HASH_PREFIX_LENGTH = 8
HEX_BASE = 16


def hash_to_variant(hash_input: str, num_variants: int) -> str:
    """Map hash input to variant ID using consistent hashing.

    Args:
        hash_input: String to hash
        num_variants: Total number of variants (including control)

    Returns:
        variant_id: "control", "variant_0", "variant_1", etc.
    """
    hash_value = hashlib.sha256(hash_input.encode()).hexdigest()
    hash_int = int(hash_value[:HASH_PREFIX_LENGTH], HEX_BASE)
    variant_index = hash_int % num_variants

    if variant_index == 0:
        return "control"
    else:
        return f"variant_{variant_index - 1}"


def aggregate_variant_results(
    variant_id: str,
    results: List[ExecutionResult],
) -> VariantResults:
    """Aggregate results for a specific variant."""
    variant_results = [r for r in results if r.variant_id == variant_id]

    quality_scores = [r.quality_score for r in variant_results if r.quality_score is not None]
    speed_scores = [r.speed_seconds for r in variant_results if r.speed_seconds is not None]
    cost_scores = [r.cost_usd for r in variant_results if r.cost_usd is not None]

    return VariantResults(
        variant_id=variant_id,
        variant_name=variant_id,
        sample_size=len(variant_results),
        quality_scores=quality_scores,
        speed_scores=speed_scores,
        cost_scores=cost_scores,
    )


def get_experiment_progress(
    experiment_id: str,
    session_factory: Callable[[], Any],
    get_db_experiment_fn: Callable[..., Any],
) -> Dict[str, Any]:
    """Get current progress for each variant in experiment.

    Args:
        experiment_id: Experiment identifier
        session_factory: Callable that returns a context-manager session
        get_db_experiment_fn: Function to get DB experiment (with session param)

    Returns:
        Dict with progress information
    """
    from src.self_improvement.experiment_orchestrator import _db_to_experiment

    with session_factory() as session:
        db_exp = get_db_experiment_fn(experiment_id, session=session)
        experiment = _db_to_experiment(db_exp)
        target = db_exp.target_samples_per_variant

        count_stmt = (
            select(M5ExecutionResult.variant_id, func.count())
            .where(M5ExecutionResult.experiment_id == experiment_id)
            .group_by(M5ExecutionResult.variant_id)
        )
        count_rows = session.execute(count_stmt).all()
        count_map = {row[0]: row[1] for row in count_rows}

    variant_progress = {}
    expected_variants = ["control"] + [
        f"variant_{i}" for i in range(len(experiment.variant_configs))
    ]

    for vid in expected_variants:
        count = count_map.get(vid, 0)
        variant_progress[vid] = {
            "collected": count,
            "target": target,
            "pct": (count / target * 100) if target > 0 else 0,
        }

    is_complete = all(vp["collected"] >= target for vp in variant_progress.values())
    total_collected = sum(vp["collected"] for vp in variant_progress.values())
    total_target = target * len(expected_variants)

    return {
        "experiment_id": experiment_id,
        "status": experiment.status,
        "target_per_variant": target,
        "variants": variant_progress,
        "total_collected": total_collected,
        "total_target": total_target,
        "is_complete": is_complete,
        "can_analyze": is_complete,
    }


def record_result_to_db(
    data: ExperimentResultData,
    session_factory: Callable[[], Any],
) -> None:
    """Create and store an execution result ORM record.

    Args:
        data: ExperimentResultData bundle with all result parameters
        session_factory: Session factory callable
    """
    result_id = f"result-{uuid.uuid4().hex[:RESULT_ID_UUID_LENGTH]}"
    db_result = M5ExecutionResult(
        id=result_id,
        experiment_id=data.experiment_id,
        variant_id=data.variant_id,
        execution_id=data.execution_id,
        quality_score=data.quality_score,
        speed_seconds=data.speed_seconds,
        cost_usd=data.cost_usd,
        success=data.success,
        recorded_at=utcnow(),
        extra_metrics=data.extra_metrics or {},
    )
    with session_factory() as session:
        session.add(db_result)
        session.commit()


def create_experiment_in_db(
    data: ExperimentCreationData,
    session_factory: Callable[[], Any],
) -> SelfImprovementExperiment:
    """Create experiment ORM record and return domain model.

    Args:
        data: ExperimentCreationData bundle with all creation parameters
        session_factory: Session factory callable

    Returns:
        SelfImprovementExperiment domain model
    """
    now = utcnow()

    db_exp = M5Experiment(
        id=data.experiment_id,
        agent_name=data.agent_name,
        status="running",
        control_config=data.control_config.to_dict(),
        variant_configs=[v.to_dict() for v in data.variant_configs],
        target_samples_per_variant=data.target,
        proposal_id=data.proposal_id,
        created_at=now,
        extra_metadata=data.extra_metadata or {},
    )
    with session_factory() as session:
        session.add(db_exp)
        session.commit()

    return SelfImprovementExperiment(
        id=data.experiment_id,
        agent_name=data.agent_name,
        status="running",
        control_config=data.control_config,
        variant_configs=data.variant_configs,
        proposal_id=data.proposal_id,
        created_at=now,
        extra_metadata=data.extra_metadata or {},
    )
