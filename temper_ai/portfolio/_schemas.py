"""Pydantic schemas for portfolio management."""

from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from temper_ai.portfolio.constants import (
    DEFAULT_MAX_CONCURRENT_PER_PRODUCT,
    DEFAULT_MAX_TOTAL_CONCURRENT,
    DEFAULT_PRODUCT_WEIGHT,
)


class AllocationStrategy(str, Enum):
    """Resource allocation strategy for portfolio products."""

    EQUAL = "equal"
    WEIGHTED = "weighted"
    PRIORITY = "priority"
    DYNAMIC = "dynamic"


class ProductDefinition(BaseModel):
    """A single product within a portfolio."""

    name: str
    weight: float = DEFAULT_PRODUCT_WEIGHT
    max_concurrent: int = DEFAULT_MAX_CONCURRENT_PER_PRODUCT
    budget_limit_usd: float = 0.0  # 0 = unlimited
    workflow_configs: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class PortfolioConfig(BaseModel):
    """Top-level portfolio configuration."""

    name: str
    description: str = ""
    products: List[ProductDefinition] = Field(default_factory=list)
    strategy: AllocationStrategy = AllocationStrategy.WEIGHTED
    total_budget_usd: float = 0.0  # 0 = unlimited
    max_total_concurrent: int = DEFAULT_MAX_TOTAL_CONCURRENT


class AllocationStatus(BaseModel):
    """Current allocation state for a product."""

    product_type: str
    active_runs: int = 0
    completed_runs: int = 0
    budget_used_usd: float = 0.0
    budget_limit_usd: float = 0.0
    utilization: float = 0.0


class ComponentMatch(BaseModel):
    """A pair of similar stage configurations across products."""

    source_stage: str
    target_stage: str
    similarity: float = 0.0
    shared_keys: List[str] = Field(default_factory=list)
    differing_keys: List[str] = Field(default_factory=list)


class ProductScorecard(BaseModel):
    """4-metric scorecard for a product type."""

    product_type: str
    success_rate: float = 0.0
    cost_efficiency: float = 0.0
    trend: float = 0.0
    utilization: float = 0.0
    composite_score: float = 0.0


class OptimizationAction(str, Enum):
    """Recommended action for a product."""

    INVEST = "invest"
    MAINTAIN = "maintain"
    REDUCE = "reduce"
    SUNSET = "sunset"


class PortfolioRecommendation(BaseModel):
    """Optimization recommendation for a product."""

    product_type: str
    action: OptimizationAction
    scorecard: ProductScorecard
    rationale: str = ""
    suggested_weight_delta: float = 0.0


class KGConceptType(str, Enum):
    """Types of knowledge graph concepts."""

    PRODUCT = "product"
    STAGE = "stage"
    AGENT = "agent"
    TOOL = "tool"
    OUTCOME = "outcome"


class KGRelation(str, Enum):
    """Types of knowledge graph edges."""

    USES = "uses"
    REQUIRES = "requires"
    HAS_AGENT = "has_agent"
    PRODUCED_RESULT = "produced_result"
    TOOK_DURATION = "took_duration"
    COMPATIBLE_WITH = "compatible_with"


class TechCompatibility(BaseModel):
    """Technology compatibility record."""

    tech_a: str
    tech_b: str
    compatibility_score: float = 0.0
    notes: str = ""


class PortfolioSummary(BaseModel):
    """Summary statistics for a portfolio."""

    name: str
    product_count: int = 0
    total_runs: int = 0
    strategy: str = ""
    allocations: List[AllocationStatus] = Field(default_factory=list)
    scorecards: List[ProductScorecard] = Field(default_factory=list)
    recommendations: List[PortfolioRecommendation] = Field(default_factory=list)
    shared_components: List[ComponentMatch] = Field(default_factory=list)
    graph_stats: Dict[str, Any] = Field(default_factory=dict)
