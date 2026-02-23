"""Prompt testing harness for Temper AI agents.

Provides:
- PromptTestRunner: Runs test cases against agent prompts
- TestSuite/TestCase: Declarative test definitions
- TestResult/SuiteResult: Structured test results
"""

from temper_ai.evaluation._schemas import (  # noqa: F401
    SuiteResult,
    TestCase,
    TestCaseValidator,
    TestResult,
    TestSuite,
)


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy import PromptTestRunner on first access."""
    if name == "PromptTestRunner":
        from temper_ai.evaluation.runner import PromptTestRunner

        return PromptTestRunner
    raise AttributeError(f"module 'temper_ai.evaluation' has no attribute {name!r}")
