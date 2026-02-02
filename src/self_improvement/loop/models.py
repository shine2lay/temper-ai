"""
Data models for M5 Self-Improvement Loop.

Contains models for loop state, iteration results, configuration, and progress tracking.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List


class Phase(Enum):
    """M5 improvement cycle phases."""
    DETECT = "detect"  # Phase 1: Problem detection
    ANALYZE = "analyze"  # Phase 2: Performance analysis
    STRATEGY = "strategy"  # Phase 3: Strategy generation
    EXPERIMENT = "experiment"  # Phase 4: A/B testing
    DEPLOY = "deploy"  # Phase 5: Deployment & rollback


class LoopStatus(Enum):
    """Loop execution status."""
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"


class RecoveryAction(Enum):
    """Error recovery actions."""
    RETRY = "retry"
    SKIP = "skip"
    ROLLBACK = "rollback"
    FAIL = "fail"


@dataclass
class LoopState:
    """
    Current state of improvement loop for an agent.

    Persisted in coordination DB for crash recovery and multi-process support.
    """
    agent_name: str
    current_phase: Phase
    status: LoopStatus
    iteration_number: int
    phase_data: Dict[str, Any] = field(default_factory=dict)
    last_error: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = field(default_factory=lambda: datetime.utcnow())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "agent_name": self.agent_name,
            "current_phase": self.current_phase.value,
            "status": self.status.value,
            "iteration_number": self.iteration_number,
            "phase_data": self.phase_data,
            "last_error": self.last_error,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoopState":
        """Load from dictionary (from database)."""
        return cls(
            agent_name=data["agent_name"],
            current_phase=Phase(data["current_phase"]),
            status=LoopStatus(data["status"]),
            iteration_number=data["iteration_number"],
            phase_data=data.get("phase_data", {}),
            last_error=data.get("last_error"),
            started_at=datetime.fromisoformat(data["started_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


@dataclass
class DetectionResult:
    """Result from Phase 1: Problem Detection."""
    has_problem: bool
    problem_type: Optional[str] = None
    baseline_metrics: Optional[Dict[str, Any]] = None
    current_metrics: Optional[Dict[str, Any]] = None
    improvement_opportunity: Optional[str] = None


@dataclass
class AnalysisResult:
    """Result from Phase 2: Performance Analysis."""
    performance_profile: Any  # AgentPerformanceProfile
    metrics_summary: Dict[str, Any]
    baseline_comparison: Optional[Dict[str, Any]] = None


@dataclass
class StrategyResult:
    """Result from Phase 3: Strategy Generation."""
    control_config: Any  # AgentConfig
    variant_configs: List[Any]  # List[AgentConfig]
    strategy_name: str
    strategy_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentResult:
    """Result from Phase 4: Experimentation."""
    experiment_id: str
    winner_variant_id: Optional[str]
    winner_config: Optional[Any] = None  # AgentConfig
    statistical_significance: Optional[float] = None
    metrics_comparison: Optional[Dict[str, Any]] = None


@dataclass
class DeploymentResult:
    """Result from Phase 5: Deployment."""
    deployment_id: str
    deployed_config: Any  # AgentConfig
    previous_config: Any  # AgentConfig
    deployment_timestamp: datetime
    rollback_monitoring_enabled: bool


@dataclass
class IterationResult:
    """
    Complete iteration result.

    Contains results from all phases and metadata about the iteration.
    """
    agent_name: str
    iteration_number: int
    success: bool
    phases_completed: List[Phase]
    detection_result: Optional[DetectionResult] = None
    analysis_result: Optional[AnalysisResult] = None
    strategy_result: Optional[StrategyResult] = None
    experiment_result: Optional[ExperimentResult] = None
    deployment_result: Optional[DeploymentResult] = None
    error: Optional[Exception] = None
    error_phase: Optional[Phase] = None
    duration_seconds: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.utcnow())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "agent_name": self.agent_name,
            "iteration_number": self.iteration_number,
            "success": self.success,
            "phases_completed": [p.value for p in self.phases_completed],
            "error": str(self.error) if self.error else None,
            "error_phase": self.error_phase.value if self.error_phase else None,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp.isoformat(),
            # Phase results stored separately if needed
        }


@dataclass
class PhaseProgress:
    """Progress information for a single phase."""
    phase: Phase
    status: str  # not_started, in_progress, completed, failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class ProgressReport:
    """
    Current progress report for an agent's improvement loop.

    Used for monitoring and dashboards.
    """
    agent_name: str
    current_phase: Phase
    current_iteration: int
    total_iterations_completed: int
    phase_progress: Dict[Phase, PhaseProgress]
    estimated_completion: Optional[datetime] = None
    health_status: str = "healthy"  # healthy, degraded, failed
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
