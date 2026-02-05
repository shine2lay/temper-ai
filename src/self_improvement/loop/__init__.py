"""
M5 Self-Improvement Loop.

Main orchestrator for M5 self-improvement cycles integrating all 5 phases:
1. DETECT - Problem detection
2. ANALYZE - Performance analysis
3. STRATEGY - Strategy generation
4. EXPERIMENT - A/B testing
5. DEPLOY - Deployment and rollback

Example:
    >>> from coord_service.database import Database
    >>> from src.observability.database import get_session
    >>> from src.self_improvement.loop import M5SelfImprovementLoop, LoopConfig
    >>>
    >>> coord_db = Database()
    >>> with get_session() as obs_session:
    ...     config = LoopConfig(
    ...         detection_window_hours=168,
    ...         target_samples_per_variant=50,
    ...         enable_auto_deploy=True,
    ...     )
    ...     loop = M5SelfImprovementLoop(coord_db, obs_session, config)
    ...     result = loop.run_iteration("my_agent")
    ...     if result.success:
    ...         print("Improvement cycle completed!")
"""

from .orchestrator import M5SelfImprovementLoop
from .config import LoopConfig
from .models import (
    Phase,
    LoopStatus,
    LoopState,
    IterationResult,
    DetectionResult,
    AnalysisResult,
    StrategyResult,
    ExperimentPhaseResult,
    DeploymentResult,
    ProgressReport,
    RecoveryAction,
)
from .metrics import LoopMetrics

__all__ = [
    # Main API
    "M5SelfImprovementLoop",
    "LoopConfig",
    # Models
    "Phase",
    "LoopStatus",
    "LoopState",
    "IterationResult",
    "DetectionResult",
    "AnalysisResult",
    "StrategyResult",
    "ExperimentPhaseResult",
    "DeploymentResult",
    "ProgressReport",
    "RecoveryAction",
    "LoopMetrics",
]

__version__ = "1.0.0"
