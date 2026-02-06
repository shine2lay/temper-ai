"""
Problem detection for M5 Phase 3.

This module provides the core problem detection functionality for the M5
self-improvement system. It analyzes performance comparisons to detect
quality, cost, and speed problems, and coordinates improvement proposal generation.
"""

from .improvement_detector import (
    ComponentError,
    ImprovementDetectionError,
    ImprovementDetector,
    NoBaselineError,
)
from .improvement_proposal import ImprovementProposal
from .problem_config import ProblemDetectionConfig
from .problem_detector import (
    ProblemDetectionDataError,
    ProblemDetectionError,
    ProblemDetector,
)
from .problem_models import (
    PerformanceProblem,
    ProblemSeverity,
    ProblemType,
)

__all__ = [
    "PerformanceProblem",
    "ProblemType",
    "ProblemSeverity",
    "ProblemDetectionConfig",
    "ProblemDetector",
    "ProblemDetectionError",
    "ProblemDetectionDataError",
    "ImprovementProposal",
    "ImprovementDetector",
    "ImprovementDetectionError",
    "NoBaselineError",
    "ComponentError",
]
