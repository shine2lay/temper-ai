"""Cost analyzer — detects cost-saving opportunities."""

import logging
from datetime import timedelta

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from temper_ai.goals._schemas import (
    EffortLevel,
    GoalEvidence,
    GoalProposal,
    GoalRiskLevel,
    GoalType,
    ImpactEstimate,
    RiskAssessment,
)
from temper_ai.goals.analyzers.base import BaseAnalyzer
from temper_ai.goals.constants import (
    DEFAULT_LOOKBACK_HOURS,
    HIGH_COST_AGENT_SHARE,
    MODEL_COST_RATIO,
)

logger = logging.getLogger(__name__)

PCT_MULTIPLIER = 100
SAVINGS_FACTOR = 0.3
LOW_CONFIDENCE = 0.4
MID_CONFIDENCE = 0.5


class CostAnalyzer(BaseAnalyzer):
    """Identifies cost-saving opportunities from LLM usage patterns."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    @property
    def analyzer_type(self) -> str:
        """Return analyzer identifier."""
        return "cost"

    def analyze(
        self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    ) -> list[GoalProposal]:
        """Analyze agent and LLM call costs for savings opportunities."""
        if self._engine is None:
            return []

        agents, llm_calls = self._query_data(lookback_hours)
        proposals: list[GoalProposal] = []
        proposals.extend(_analyze_agent_costs(agents))
        proposals.extend(_analyze_model_costs(llm_calls))
        return proposals

    def _query_data(self, lookback_hours: int) -> tuple:
        """Query agent executions and LLM calls."""
        from temper_ai.storage.database.datetime_utils import utcnow
        from temper_ai.storage.database.models import AgentExecution, LLMCall

        cutoff = utcnow() - timedelta(hours=lookback_hours)
        with Session(self._engine) as session:
            agents = list(
                session.exec(
                    select(AgentExecution).where(
                        AgentExecution.start_time >= cutoff,
                        AgentExecution.estimated_cost_usd.is_not(None),  # type: ignore[union-attr]
                    )
                ).all()
            )
            llm_calls = list(
                session.exec(
                    select(LLMCall).where(
                        LLMCall.start_time >= cutoff,
                        LLMCall.status == "success",
                        LLMCall.estimated_cost_usd.is_not(None),  # type: ignore[union-attr]
                    )
                ).all()
            )
        return agents, llm_calls


def _make_agent_cost_proposal(  # noqa: long
    agent_name: str, agent_cost: float, total_cost: float, share: float
) -> GoalProposal:
    """Build a GoalProposal for a high-cost agent."""
    savings = agent_cost * SAVINGS_FACTOR
    return GoalProposal(
        goal_type=GoalType.COST_REDUCTION,
        title=f"Reduce cost for agent: {agent_name}",
        description=(
            f"Agent '{agent_name}' consumes "
            f"{share * PCT_MULTIPLIER:.0f}% of total "
            f"cost (${agent_cost:.2f} of ${total_cost:.2f})."
        ),
        risk_assessment=RiskAssessment(
            level=GoalRiskLevel.LOW,
            blast_radius=f"agent:{agent_name}",
            reversible=True,
        ),
        effort_estimate=EffortLevel.SMALL,
        expected_impacts=[
            ImpactEstimate(
                metric_name="cost_usd",
                current_value=agent_cost,
                expected_value=agent_cost - savings,
                improvement_pct=SAVINGS_FACTOR * PCT_MULTIPLIER,
                confidence=MID_CONFIDENCE,
            )
        ],
        evidence=GoalEvidence(
            metrics={
                "agent_cost_usd": agent_cost,
                "total_cost_usd": total_cost,
                "cost_share": share,
            },
            analysis_summary=f"High cost concentration: {share * PCT_MULTIPLIER:.0f}%",
        ),
        proposed_actions=[
            "Switch to a cheaper model variant",
            "Reduce prompt length or token usage",
            "Add caching for repeated queries",
        ],
    )


def _analyze_agent_costs(agents: list) -> list[GoalProposal]:
    """Find agents consuming disproportionate cost share."""
    if not agents:
        return []
    total_cost = sum(a.estimated_cost_usd or 0 for a in agents)
    if total_cost <= 0:
        return []

    by_agent: dict[str, float] = {}
    for a in agents:
        by_agent[a.agent_name] = by_agent.get(a.agent_name, 0) + (
            a.estimated_cost_usd or 0
        )

    proposals: list[GoalProposal] = []
    for agent_name, agent_cost in by_agent.items():
        share = agent_cost / total_cost
        if share > HIGH_COST_AGENT_SHARE:  # noqa: long
            proposals.append(
                _make_agent_cost_proposal(agent_name, agent_cost, total_cost, share)
            )
    return proposals


def _make_model_cost_proposal(
    model_name: str,
    cheapest_name: str,
    per_call: float,
    cheapest_per_call: float,
    ratio: float,
    stats: dict,
) -> GoalProposal:
    """Build a GoalProposal for a model that costs significantly more than cheapest."""
    savings = stats["cost"] - (cheapest_per_call * stats["calls"])
    improvement = (savings / stats["cost"]) * PCT_MULTIPLIER if stats["cost"] > 0 else 0
    return GoalProposal(
        goal_type=GoalType.COST_REDUCTION,
        title=f"Consider cheaper model for: {model_name}",
        description=(
            f"Model '{model_name}' costs ${per_call:.4f}/call vs "
            f"'{cheapest_name}' at ${cheapest_per_call:.4f}/call ({ratio:.1f}x)."
        ),
        risk_assessment=RiskAssessment(
            level=GoalRiskLevel.MEDIUM,
            blast_radius=f"model:{model_name}",
            reversible=True,
        ),
        effort_estimate=EffortLevel.SMALL,
        expected_impacts=[
            ImpactEstimate(
                metric_name="cost_usd",
                current_value=stats["cost"],
                expected_value=stats["cost"] - savings,
                improvement_pct=improvement,
                confidence=LOW_CONFIDENCE,
            )
        ],
        evidence=GoalEvidence(
            metrics={
                "cost_per_call": per_call,
                "cheap_cost_per_call": cheapest_per_call,
            },
            analysis_summary=f"Model cost ratio: {ratio:.1f}x",
        ),
        proposed_actions=[
            f"Evaluate '{cheapest_name}' as replacement",
            "Run A/B test comparing output quality",
        ],
    )


def _analyze_model_costs(llm_calls: list) -> list[GoalProposal]:
    """Find expensive models that could be replaced with cheaper alternatives."""
    if not llm_calls:
        return []

    by_model: dict[str, dict] = {}
    for call in llm_calls:
        m = by_model.setdefault(call.model, {"cost": 0.0, "calls": 0})
        m["cost"] += call.estimated_cost_usd or 0
        m["calls"] += 1

    models = list(by_model.items())
    if len(models) < 2:
        return []

    models.sort(key=lambda x: x[1]["cost"] / max(x[1]["calls"], 1))
    cheapest_name, cheapest = models[0]
    cheapest_per_call = cheapest["cost"] / max(cheapest["calls"], 1)
    if cheapest_per_call <= 0:
        return []

    proposals: list[GoalProposal] = []
    for model_name, stats in models[1:]:
        per_call = stats["cost"] / max(stats["calls"], 1)
        ratio = per_call / cheapest_per_call
        if ratio > MODEL_COST_RATIO:
            proposals.append(
                _make_model_cost_proposal(
                    model_name, cheapest_name, per_call, cheapest_per_call, ratio, stats
                )
            )
    return proposals
