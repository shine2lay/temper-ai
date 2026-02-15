"""Shared fixtures for strategy tests."""

import pytest


@pytest.fixture(autouse=True)
def reset_strategy_registry():
    """Reset the strategy registry before and after each test.

    Prevents parallel test race conditions where one test's registry
    modifications leak into another test.
    """
    from src.agent.strategies.registry import StrategyRegistry

    StrategyRegistry.reset_for_testing()
    yield
    StrategyRegistry.reset_for_testing()
