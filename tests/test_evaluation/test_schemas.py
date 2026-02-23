"""Tests for prompt testing harness schemas."""

import pytest
from pydantic import ValidationError

from temper_ai.evaluation._schemas import (
    SuiteResult,
    TestCase,
    TestCaseValidator,
    TestResult,
    TestSuite,
)


class TestTestCaseValidator:
    def test_valid_construction(self):
        v = TestCaseValidator(
            name="has_decision", pattern=r"DECISION:\s*(APPROVE|REJECT)"
        )
        assert v.name == "has_decision"
        assert v.type == "regex"
        assert v.severity == "block"

    def test_warn_severity(self):
        v = TestCaseValidator(name="soft_check", pattern=r"OPTIONAL:", severity="warn")
        assert v.severity == "warn"

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            TestCaseValidator(pattern=r"test")

    def test_missing_pattern_raises(self):
        with pytest.raises(ValidationError):
            TestCaseValidator(name="test")

    def test_default_type_is_regex(self):
        v = TestCaseValidator(name="v", pattern=r".*")
        assert v.type == "regex"

    def test_default_severity_is_block(self):
        v = TestCaseValidator(name="v", pattern=r".*")
        assert v.severity == "block"


class TestTestCase:
    def test_valid_construction(self):
        case = TestCase(
            name="approve_valid",
            input_vars={"suggestion_text": "test"},
            validators=[TestCaseValidator(name="v1", pattern=r"test")],
        )
        assert case.name == "approve_valid"
        assert len(case.validators) == 1

    def test_empty_validators_accepted(self):
        case = TestCase(name="no_validators", input_vars={"x": "y"}, validators=[])
        assert len(case.validators) == 0

    def test_missing_input_vars_raises(self):
        with pytest.raises(ValidationError):
            TestCase(name="test", validators=[])

    def test_default_description_is_empty(self):
        case = TestCase(name="t1", input_vars={"k": "v"}, validators=[])
        assert case.description == ""

    def test_description_can_be_set(self):
        case = TestCase(
            name="t1",
            description="My test",
            input_vars={"k": "v"},
            validators=[],
        )
        assert case.description == "My test"


class TestTestSuite:
    def test_valid_construction(self):
        suite = TestSuite(
            agent_config="configs/agents/test.yaml",
            test_cases=[
                TestCase(name="t1", input_vars={"x": "y"}, validators=[]),
            ],
        )
        assert suite.agent_config == "configs/agents/test.yaml"
        assert len(suite.test_cases) == 1

    def test_empty_test_cases_accepted(self):
        suite = TestSuite(agent_config="some.yaml", test_cases=[])
        assert len(suite.test_cases) == 0

    def test_missing_agent_config_raises(self):
        with pytest.raises(ValidationError):
            TestSuite(test_cases=[])


class TestTestResult:
    def test_defaults(self):
        r = TestResult(test_name="t1", status="PASS", duration_seconds=1.0)
        assert r.raw_output == ""
        assert r.answer_text == ""
        assert r.error is None
        assert r.validator_results == []

    def test_all_fields(self):
        r = TestResult(
            test_name="t2",
            status="FAIL",
            duration_seconds=2.5,
            raw_output="raw",
            answer_text="answer",
            error="some error",
            validator_results=[{"name": "v1", "passed": False}],
        )
        assert r.test_name == "t2"
        assert r.status == "FAIL"
        assert r.raw_output == "raw"
        assert r.answer_text == "answer"
        assert r.error == "some error"
        assert len(r.validator_results) == 1


class TestSuiteResultSchema:
    def test_construction(self):
        sr = SuiteResult(
            agent_name="test_agent",
            agent_config="test.yaml",
            total=2,
            passed=1,
            failed=1,
            errors=0,
            results=[],
            duration_seconds=5.0,
        )
        assert sr.total == 2
        assert sr.passed == 1
        assert sr.failed == 1
        assert sr.errors == 0
        assert sr.agent_name == "test_agent"
        assert sr.duration_seconds == 5.0

    def test_with_results(self):
        results = [
            TestResult(test_name="t1", status="PASS", duration_seconds=1.0),
            TestResult(test_name="t2", status="FAIL", duration_seconds=0.5),
        ]
        sr = SuiteResult(
            agent_name="agent",
            agent_config="agent.yaml",
            total=2,
            passed=1,
            failed=1,
            errors=0,
            results=results,
            duration_seconds=1.5,
        )
        assert len(sr.results) == 2
