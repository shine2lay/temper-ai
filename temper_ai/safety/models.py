"""Safety system data models.

This module provides data models for safety violations and validation results.
Models are designed for serialization, logging, and observability integration.

Key Models:
    - SafetyViolation: Immutable record of a safety violation
    - ValidationResult: Result of validating an action
    - ViolationSeverity: Enum for violation severity levels

These models are re-exported from interfaces.py for convenience and
to provide a stable public API.
"""
from temper_ai.safety.interfaces import (
    SafetyViolation,
    ValidationResult,
    ViolationSeverity,
)

__all__ = [
    "SafetyViolation",
    "ValidationResult",
    "ViolationSeverity",
]
