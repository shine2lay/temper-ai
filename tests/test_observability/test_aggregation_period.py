"""Tests for src/observability/aggregation/period.py."""
import pytest
from src.observability.aggregation.period import AggregationPeriod


def test_aggregation_period_values():
    """Test that AggregationPeriod has the expected values."""
    assert AggregationPeriod.MINUTE == "minute"
    assert AggregationPeriod.HOUR == "hour"
    assert AggregationPeriod.DAY == "day"


def test_aggregation_period_is_string_enum():
    """Test that AggregationPeriod is a string enum."""
    # Verify it's a string
    assert isinstance(AggregationPeriod.MINUTE, str)
    assert isinstance(AggregationPeriod.HOUR, str)
    assert isinstance(AggregationPeriod.DAY, str)

    # Verify it's an enum
    from enum import Enum
    assert issubclass(AggregationPeriod, Enum)


def test_aggregation_period_all_members():
    """Test that AggregationPeriod has exactly 3 members."""
    members = list(AggregationPeriod)
    assert len(members) == 3
    assert AggregationPeriod.MINUTE in members
    assert AggregationPeriod.HOUR in members
    assert AggregationPeriod.DAY in members


def test_aggregation_period_equality():
    """Test that AggregationPeriod members compare correctly."""
    # Enum equality
    assert AggregationPeriod.MINUTE == AggregationPeriod.MINUTE
    assert AggregationPeriod.MINUTE != AggregationPeriod.HOUR

    # String equality
    assert AggregationPeriod.MINUTE == "minute"
    assert AggregationPeriod.HOUR == "hour"
    assert AggregationPeriod.DAY == "day"


def test_aggregation_period_iteration():
    """Test that AggregationPeriod can be iterated."""
    periods = [p for p in AggregationPeriod]
    assert len(periods) == 3

    values = [p.value for p in AggregationPeriod]
    assert "minute" in values
    assert "hour" in values
    assert "day" in values


def test_aggregation_period_from_string():
    """Test that AggregationPeriod can be created from string."""
    assert AggregationPeriod("minute") == AggregationPeriod.MINUTE
    assert AggregationPeriod("hour") == AggregationPeriod.HOUR
    assert AggregationPeriod("day") == AggregationPeriod.DAY


def test_aggregation_period_invalid_value():
    """Test that invalid values raise ValueError."""
    with pytest.raises(ValueError):
        AggregationPeriod("invalid")

    with pytest.raises(ValueError):
        AggregationPeriod("week")

    with pytest.raises(ValueError):
        AggregationPeriod("")


def test_aggregation_period_name_property():
    """Test that AggregationPeriod has correct name property."""
    assert AggregationPeriod.MINUTE.name == "MINUTE"
    assert AggregationPeriod.HOUR.name == "HOUR"
    assert AggregationPeriod.DAY.name == "DAY"


def test_aggregation_period_value_property():
    """Test that AggregationPeriod has correct value property."""
    assert AggregationPeriod.MINUTE.value == "minute"
    assert AggregationPeriod.HOUR.value == "hour"
    assert AggregationPeriod.DAY.value == "day"
