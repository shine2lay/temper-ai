"""SQLModel database models for M5 experiment system.

Replaces raw SQL table creation for m5_experiments and m5_experiment_results.
These models are managed by SQLModel.metadata.create_all() alongside other
ORM-managed tables.
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlmodel import Column, Field, Relationship, SQLModel

from src.database.datetime_utils import utcnow


class M5Experiment(SQLModel, table=True):
    """SQLModel for M5 experiment storage.

    Stores A/B testing experiments created by the self-improvement loop.
    Configuration is stored as JSON for flexibility.
    Timestamps use proper datetime columns.
    """
    __tablename__ = "m5_experiments"
    __table_args__ = (
        Index("idx_m5_exp_agent", "agent_name"),
        Index("idx_m5_exp_status", "status"),
    )

    id: str = Field(primary_key=True)
    agent_name: str
    status: str  # "running", "completed", "stopped", "failed"
    control_config: Dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    variant_configs: List[Dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    target_samples_per_variant: int = Field(default=50)
    winner_variant_id: Optional[str] = None
    analysis_results: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    proposal_id: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime, nullable=False, default=utcnow),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    extra_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    results: List["M5ExecutionResult"] = Relationship(
        back_populates="experiment",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    def get_control_config_dict(self) -> Dict[str, Any]:
        """Return control config dict (already deserialized by JSON column)."""
        if isinstance(self.control_config, str):
            return json.loads(self.control_config)
        return self.control_config

    def get_variant_configs_dicts(self) -> List[Dict[str, Any]]:
        """Return variant configs list (already deserialized by JSON column)."""
        if isinstance(self.variant_configs, str):
            return json.loads(self.variant_configs)
        return self.variant_configs

    def get_variant_count(self) -> int:
        """Total number of variants including control."""
        configs = self.get_variant_configs_dicts()
        return 1 + len(configs)

    def get_extra_metadata(self) -> Dict[str, Any]:
        """Return extra metadata dict (already deserialized by JSON column)."""
        if self.extra_metadata is None:
            return {}
        if isinstance(self.extra_metadata, str):
            return json.loads(self.extra_metadata)
        return self.extra_metadata


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
    experiment_id: str = Field(
        sa_column=Column(String, ForeignKey("m5_experiments.id", ondelete="CASCADE"), nullable=False)
    )
    variant_id: str
    execution_id: str = Field(unique=True)
    quality_score: Optional[float] = None
    speed_seconds: Optional[float] = None
    cost_usd: Optional[float] = None
    success: Optional[bool] = None
    recorded_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime, nullable=False, default=utcnow),
    )
    extra_metrics: Optional[Dict[str, float]] = Field(default=None, sa_column=Column(JSON))

    experiment: Optional[M5Experiment] = Relationship(back_populates="results")

    def get_extra_metrics(self) -> Dict[str, float]:
        """Return extra metrics dict (already deserialized by JSON column)."""
        if self.extra_metrics is None:
            return {}
        if isinstance(self.extra_metrics, str):
            return json.loads(self.extra_metrics)
        return self.extra_metrics
