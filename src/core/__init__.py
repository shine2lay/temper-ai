"""Core framework components.

This package contains foundational components used throughout the framework:
- Circuit breakers for fault tolerance
- Context management for execution state
- Protocol definitions for common patterns
- Service utilities
"""
from src.core.protocols import Registry

__all__ = ["Registry"]
