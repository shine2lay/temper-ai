"""SQLModel database models for M5 experiment system.

Replaces raw SQL table creation for m5_experiments and m5_experiment_results.
These models are managed by SQLModel.metadata.create_all() alongside other
ORM-managed tables.
"""
import json
from typing import Optional, Dict, Any, List

from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Index


class M5Experiment(SQLModel, table=True):
    """SQLModel for M5 experiment storage.

    Stores A/B testing experiments created by the self-improvement loop.
    Configuration is stored as JSON text for flexibility.
    """
    __tablename__ = "m5_experiments"
    __table_args__ = (
        Index("idx_m5_exp_agent", "agent_name"),
        Index("idx_m5_exp_status", "status"),
    )

    id: str = Field(primary_key=True)
    agent_name: str
    status: str  # "running", "completed", "stopped", "failed"
    control_config: str  # JSON text (serialized OptimizationConfig)
    variant_configs: str  # JSON text (serialized List[OptimizationConfig])
    target_samples_per_variant: int = Field(default=50)
    winner_variant_id: Optional[str] = None
    analysis_results: Optional[str] = None  # JSON text
    proposal_id: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    extra_metadata: Optional[str] = None  # JSON text

    results: List["M5ExecutionResult"] = Relationship(back_populates="experiment")

    def get_control_config_dict(self) -> Dict[str, Any]:
        """Deserialize control config from JSON."""
        return json.loads(self.control_config)

    def get_variant_configs_dicts(self) -> List[Dict[str, Any]]:
        """Deserialize variant configs from JSON."""
        return json.loads(self.variant_configs)

    def get_variant_count(self) -> int:
        """Total number of variants including control."""
        return 1 + len(json.loads(self.variant_configs))

    def get_extra_metadata(self) -> Dict[str, Any]:
        """Deserialize extra metadata from JSON."""
        return json.loads(self.extra_metadata) if self.extra_metadata else {}


class M5ExecutionResult(SQLModel, table=True):
    """SQLModel for M5 per-execution experiment results.

    Records the outcome of a single agent execution during an experiment,
    tracking which variant was used and performance metrics.
    """
    __tablename__ = "m5_experiment_results"
    __table_args__ = (
        Index("idx_m5_result_experiment", "experiment_id"),
        Index("idx_m5_result_variant", "variant_id"),
    )

    id: str = Field(primary_key=True)
    experiment_id: str = Field(foreign_key="m5_experiments.id")
    variant_id: str
    execution_id: str = Field(unique=True)
    quality_score: Optional[float] = None
    speed_seconds: Optional[float] = None
    cost_usd: Optional[float] = None
    success: Optional[bool] = None
    recorded_at: str
    extra_metrics: Optional[str] = None  # JSON text

    experiment: Optional[M5Experiment] = Relationship(back_populates="results")

    def get_extra_metrics(self) -> Dict[str, float]:
        """Deserialize extra metrics from JSON."""
        return json.loads(self.extra_metrics) if self.extra_metrics else {}
