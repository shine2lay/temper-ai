"""LLM service — reusable LLM call lifecycle management.

Provides LLMService (tool-calling loop, retry, tracking, cost estimation)
independent of any specific agent implementation.

Imports are lazy to avoid circular dependency:
  src.llm -> src.llm.service -> src.agent.utils.constants
  -> src.agent.__init__ -> src.agent.standard_agent -> src.llm.service (circular)
"""
from typing import Any


def __getattr__(name: str) -> Any:
    if name in ("LLMService", "LLMRunResult"):
        from src.llm.service import LLMRunResult, LLMService  # noqa: F811

        globals()["LLMService"] = LLMService
        globals()["LLMRunResult"] = LLMRunResult
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["LLMService", "LLMRunResult"]
