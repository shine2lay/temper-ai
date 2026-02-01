"""
Problem detection for M5 Phase 3.

This module provides the core problem detection functionality for the M5
self-improvement system. It analyzes performance comparisons to detect
quality, cost, and speed problems.
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

__all__ = [
    "PerformanceProblem",
    "ProblemType",
    "ProblemSeverity",
    "ProblemDetectionConfig",
    "ProblemDetector",
    "ProblemDetectionError",
    "InsufficientDataError",
]
