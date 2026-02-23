"""Pydantic schemas for the prompt testing harness (R8)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TestCaseValidator(BaseModel):
    """A single validator applied to LLM output for a test case."""

    __test__ = False  # Not a pytest test class

    name: str
    type: Literal["regex"] = "regex"
    pattern: str
    severity: Literal["block", "warn"] = "block"


class TestCase(BaseModel):
    """A single prompt test case with input vars and validators."""

    __test__ = False  # Not a pytest test class

    name: str
    description: str = ""
    input_vars: dict[str, str]
    validators: list[TestCaseValidator]


class TestSuite(BaseModel):
    """A collection of test cases for a given agent config."""

    __test__ = False  # Not a pytest test class

    agent_config: str
    test_cases: list[TestCase]


class TestResult(BaseModel):
    """Result of running a single test case."""

    __test__ = False  # Not a pytest test class

    test_name: str
    status: str
    duration_seconds: float
    validator_results: list[dict[str, Any]] = Field(default_factory=list)
    raw_output: str = ""
    answer_text: str = ""
    error: str | None = None


class SuiteResult(BaseModel):
    """Aggregated result of running a full test suite."""

    agent_name: str
    agent_config: str
    total: int
    passed: int
    failed: int
    errors: int
    results: list[TestResult]
    duration_seconds: float
