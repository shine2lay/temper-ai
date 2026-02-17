"""Pydantic schemas for progressive autonomy configuration."""

from enum import IntEnum
from typing import Optional

from pydantic import BaseModel, Field

from src.safety.autonomy.constants import SPOT_CHECK_SAMPLE_RATE


class AutonomyLevel(IntEnum):
    """Progressive autonomy levels, ordered from most to least supervised."""

    SUPERVISED = 0
    SPOT_CHECKED = 1
    RISK_GATED = 2
    AUTONOMOUS = 3
    STRATEGIC = 4


class AutonomyConfig(BaseModel):
    """Per-agent autonomy configuration.

    All fields have safe defaults so existing agent configs work unchanged.
    """

    enabled: bool = False
    level: AutonomyLevel = Field(default=AutonomyLevel.SUPERVISED)
    allow_escalation: bool = True
    max_level: AutonomyLevel = Field(default=AutonomyLevel.RISK_GATED)
    shadow_mode: bool = True
    budget_usd: Optional[float] = None
    spot_check_rate: float = Field(
        default=SPOT_CHECK_SAMPLE_RATE, ge=0.0, le=1.0
    )
