"""
Problem detection for M5 Phase 3.

This module provides the core problem detection functionality for the M5
self-improvement system. It analyzes performance comparisons to detect
quality, cost, and speed problems, and coordinates improvement proposal generation.
"""

from .problem_models import (
    PerformanceProblem,
    ProblemType,
    ProblemSeverity,
)
from .problem_config import ProblemDetectionConfig
from .problem_detector import (
    ProblemDetector,
    ProblemDetectionError,
    InsufficientDataError,
)
from .improvement_proposal import ImprovementProposal
from .improvement_detector import (
    ImprovementDetector,
    ImprovementDetectionError,
    NoBaselineError,
    ComponentError,
)

__all__ = [
    "PerformanceProblem",
    "ProblemType",
    "ProblemSeverity",
    "ProblemDetectionConfig",
    "ProblemDetector",
    "ProblemDetectionError",
    "InsufficientDataError",
    "ImprovementProposal",
    "ImprovementDetector",
    "ImprovementDetectionError",
    "NoBaselineError",
    "ComponentError",
]
