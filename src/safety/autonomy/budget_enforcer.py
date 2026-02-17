"""Budget enforcement for cost-controlled autonomy."""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from src.storage.database.datetime_utils import utcnow
from src.safety.autonomy.constants import (
    BUDGET_WARNING_THRESHOLD,
    DEFAULT_BUDGET_USD,
    STATUS_ACTIVE,
    STATUS_EXHAUSTED,
    STATUS_WARNING,
)
from src.safety.autonomy.models import BudgetRecord
from src.safety.autonomy.store import AutonomyStore

logger = logging.getLogger(__name__)

UUID_HEX_LEN = 12

# Token unit for pricing (prices are per 1M tokens)
TOKENS_PER_MILLION = 1_000_000


@dataclass
class BudgetCheckResult:
    """Result of a budget check."""

    allowed: bool
    remaining_usd: float
    status: str
    message: str = ""


@dataclass
class BudgetStatus:
    """Summary of budget status for a scope."""

    scope: str
    budget_usd: float
    spent_usd: float
    remaining_usd: float
    utilization: float
    action_count: int
    status: str


class BudgetEnforcer:
    """Enforce cost budgets for autonomous agent operations.

    Tracks spending against per-scope budgets and blocks actions
    when budgets are exhausted.
    """

    def __init__(
        self,
        store: AutonomyStore,
        pricing_path: Optional[str] = None,
        default_budget: float = DEFAULT_BUDGET_USD,
    ) -> None:
        self._store = store
        self._default_budget = default_budget
        self._pricing = self._load_pricing(pricing_path)

    def check_budget(
        self, scope: str, estimated_cost: float = 0.0
    ) -> BudgetCheckResult:
        """Check if an action is within budget.

        Args:
            scope: Budget scope (e.g., agent name or workflow).
            estimated_cost: Estimated cost in USD for the action.

        Returns:
            BudgetCheckResult with allowed flag and status.
        """
        budget = self._get_or_create_budget(scope)
        remaining = budget.budget_usd - budget.spent_usd

        if remaining <= 0:
            return BudgetCheckResult(
                allowed=False,
                remaining_usd=0.0,
                status=STATUS_EXHAUSTED,
                message=f"Budget exhausted for scope '{scope}'",
            )

        if estimated_cost > remaining:
            return BudgetCheckResult(
                allowed=False,
                remaining_usd=remaining,
                status=STATUS_WARNING,
                message=f"Estimated cost ${estimated_cost:.4f} exceeds remaining ${remaining:.4f}",
            )

        utilization = budget.spent_usd / budget.budget_usd if budget.budget_usd > 0 else 0.0
        status = STATUS_WARNING if utilization >= BUDGET_WARNING_THRESHOLD else STATUS_ACTIVE

        return BudgetCheckResult(
            allowed=True,
            remaining_usd=remaining,
            status=status,
        )

    def record_spend(self, scope: str, cost_usd: float) -> None:
        """Record actual cost after an action completes.

        Args:
            scope: Budget scope.
            cost_usd: Actual cost in USD.
        """
        budget = self._get_or_create_budget(scope)
        budget.spent_usd += cost_usd
        budget.action_count += 1
        budget.updated_at = utcnow()

        # Update status
        utilization = budget.spent_usd / budget.budget_usd if budget.budget_usd > 0 else 0.0
        if budget.spent_usd >= budget.budget_usd:
            budget.status = STATUS_EXHAUSTED
        elif utilization >= BUDGET_WARNING_THRESHOLD:
            budget.status = STATUS_WARNING
        else:
            budget.status = STATUS_ACTIVE

        self._store.save_budget(budget)
        logger.debug(
            "Recorded spend $%.4f for scope '%s' (total: $%.4f / $%.4f)",
            cost_usd, scope, budget.spent_usd, budget.budget_usd,
        )

    def estimate_action_cost(
        self, model: str, estimated_tokens: int
    ) -> float:
        """Estimate cost for an LLM action using model pricing.

        Args:
            model: Model name (e.g., "claude-opus-4.5").
            estimated_tokens: Estimated token count.

        Returns:
            Estimated cost in USD.
        """
        pricing = self._pricing.get(model)
        if pricing is None:
            return 0.0

        # Use output price as conservative estimate
        output_price = pricing.get("output_price", 0.0)
        return float((estimated_tokens / TOKENS_PER_MILLION) * output_price)

    def get_budget_status(self, scope: str) -> BudgetStatus:
        """Get summary budget status for a scope.

        Args:
            scope: Budget scope.

        Returns:
            BudgetStatus summary.
        """
        budget = self._get_or_create_budget(scope)
        remaining = max(0.0, budget.budget_usd - budget.spent_usd)
        utilization = budget.spent_usd / budget.budget_usd if budget.budget_usd > 0 else 0.0

        return BudgetStatus(
            scope=scope,
            budget_usd=budget.budget_usd,
            spent_usd=budget.spent_usd,
            remaining_usd=remaining,
            utilization=utilization,
            action_count=budget.action_count,
            status=budget.status,
        )

    def _get_or_create_budget(self, scope: str) -> BudgetRecord:
        """Get existing budget or create default."""
        budget = self._store.get_budget(scope)
        if budget is None:
            budget = BudgetRecord(
                id=f"bg-{uuid.uuid4().hex[:UUID_HEX_LEN]}",
                scope=scope,
                period="unlimited",
                budget_usd=self._default_budget,
            )
            self._store.save_budget(budget)
        return budget

    def _load_pricing(self, pricing_path: Optional[str]) -> Dict[str, Any]:
        """Load model pricing from YAML."""
        if pricing_path is None:
            default_path = Path(__file__).parent.parent.parent.parent / "config" / "model_pricing.yaml"
            if default_path.exists():
                pricing_path = str(default_path)
            else:
                return {}

        try:
            with open(pricing_path) as f:
                data = yaml.safe_load(f)
            return data.get("models", {}) if isinstance(data, dict) else {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Could not load model pricing: %s", exc)
            return {}
