"""
Configuration deployment module for M5 self-improvement.

Provides safe deployment of winning configurations with rollback capability.
"""

from src.self_improvement.deployment.deployer import ConfigDeployer
from src.self_improvement.deployment.rollback_monitor import (
    RegressionThresholds,
    RollbackMonitor,
)

__all__ = ["ConfigDeployer", "RollbackMonitor", "RegressionThresholds"]
