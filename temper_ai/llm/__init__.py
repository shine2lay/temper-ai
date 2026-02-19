"""LLM service — reusable LLM call lifecycle management.

Provides LLMService (tool-calling loop, retry, tracking, cost estimation)
independent of any specific agent implementation.

Imports are lazy to avoid circular dependency:
  temper_ai.llm -> temper_ai.llm.service -> temper_ai.agent.utils.constants
  -> temper_ai.agent.__init__ -> temper_ai.agent.standard_agent -> temper_ai.llm.service (circular)
"""
from typing import Any


def __getattr__(name: str) -> Any:
    if name in ("LLMService", "LLMRunResult"):
        from temper_ai.llm.service import LLMRunResult, LLMService  # noqa: F811

        globals()["LLMService"] = LLMService
        globals()["LLMRunResult"] = LLMRunResult
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["LLMService", "LLMRunResult"]
