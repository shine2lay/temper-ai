"""
Configuration deployment module for M5 self-improvement.

Provides safe deployment of winning configurations with rollback capability.
"""

from src.self_improvement.deployment.deployer import ConfigDeployer

__all__ = ["ConfigDeployer"]
