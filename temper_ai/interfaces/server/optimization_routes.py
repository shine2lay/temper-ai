"""Optimization API endpoints for DSPy program compilation and management.

Provides endpoints for compiling DSPy programs and retrieving compiled results.
"""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.status import HTTP_404_NOT_FOUND, HTTP_500_INTERNAL_SERVER_ERROR

from temper_ai.auth.api_key_auth import require_auth, require_role

logger = logging.getLogger(__name__)

_DEFAULT_MAX_BOOTSTRAPPED_DEMOS = 3


# ── Request / Response models ─────────────────────────────────────────


class TrainingExampleModel(BaseModel):
    """A single training example for DSPy compilation."""

    inputs: dict[str, Any]
    outputs: dict[str, Any]
    score: float | None = None


class CompileRequest(BaseModel):
    """POST /api/optimization/compile request body."""

    agent_name: str
    training_examples: list[TrainingExampleModel]
    optimizer: str = "bootstrap"
    num_candidates: int = 10
    max_bootstrapped_demos: int = _DEFAULT_MAX_BOOTSTRAPPED_DEMOS
    provider: str = "openai"
    model: str = "gpt-4"


# ── Endpoint handlers ─────────────────────────────────────────────────


def _handle_compile_program(body: CompileRequest) -> dict[str, Any]:
    """Compile a DSPy program using training examples."""
    from temper_ai.optimization.dspy._schemas import (
        PromptOptimizationConfig,
        TrainingExample,
    )
    from temper_ai.optimization.dspy.compiler import DSPyCompiler
    from temper_ai.optimization.dspy.program_store import CompiledProgramStore

    compiler = DSPyCompiler()
    store = CompiledProgramStore()
    examples = [
        TrainingExample(
            input_text=str(ex.inputs),
            output_text=str(ex.outputs),
            metric_score=float(ex.score) if ex.score is not None else 1.0,
            agent_name=body.agent_name,
        )
        for ex in body.training_examples
    ]
    config = PromptOptimizationConfig(
        optimizer=body.optimizer,
        max_demos=body.max_bootstrapped_demos,
    )

    try:
        import dspy

        class _StubProgram(dspy.Module):
            def __init__(self) -> None:
                super().__init__()
                self.predict = dspy.Predict("input -> output")

            def forward(self, **kwargs: Any) -> Any:
                """Run the stub DSPy predict module."""
                return self.predict(**kwargs)

        result = compiler.compile(
            program=_StubProgram(),
            training_examples=examples,
            config=config,
            provider=body.provider,
            model=body.model,
        )
        result.agent_name = body.agent_name
        program_id = store.save(
            agent_name=body.agent_name,
            program=result.program_data,
            metadata={
                "optimizer": body.optimizer,
                "train_score": str(result.train_score),
                "val_score": str(result.val_score),
            },
        )
        return {
            "program_id": program_id,
            "agent_name": body.agent_name,
            "train_score": result.train_score,
            "val_score": result.val_score,
            "num_examples": result.num_examples,
            "num_demos": result.num_demos,
            "status": "compiled",
        }
    except ImportError:
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="DSPy is not installed. Install with: pip install 'temper-ai[dspy]'",
        )
    except Exception as e:
        logger.exception("DSPy compilation failed for agent %s", body.agent_name)
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Compilation failed: {e}",
        ) from e


def _handle_list_programs(agent_name: str | None) -> dict[str, Any]:
    """List all compiled DSPy programs."""
    from temper_ai.optimization.dspy.program_store import CompiledProgramStore

    store = CompiledProgramStore()
    try:
        programs = store.list_programs(agent_name=agent_name)
        return {"programs": programs, "total": len(programs)}
    except Exception as e:
        logger.exception("Failed to list compiled programs")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list programs"
        ) from e


def _handle_preview_program(name: str) -> dict[str, Any]:
    """Preview the latest compiled program for an agent."""
    from temper_ai.optimization.dspy.program_store import CompiledProgramStore

    store = CompiledProgramStore()
    program = store.load_latest(agent_name=name)
    if program is None:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"No compiled program found for agent '{name}'",
        )
    return program


# ── Router factory ────────────────────────────────────────────────────


def create_optimization_router(auth_enabled: bool = False) -> APIRouter:
    """Create the optimization API router."""
    router = APIRouter(prefix="/api/optimization")
    read_deps = [Depends(require_auth)] if auth_enabled else []
    write_deps = [Depends(require_role("owner", "editor"))] if auth_enabled else []

    @router.post("/compile", dependencies=write_deps)
    def compile_program(body: CompileRequest = Body(...)) -> dict[str, Any]:
        """Compile a DSPy optimization program."""
        return _handle_compile_program(body)

    @router.get("/programs", dependencies=read_deps)
    def list_programs(
        agent_name: str | None = Query(None, description="Filter by agent name")
    ) -> dict[str, Any]:
        """List available optimization programs."""
        return _handle_list_programs(agent_name)

    @router.get("/programs/{name}/preview", dependencies=read_deps)
    def preview_program(name: str) -> dict[str, Any]:
        """Preview an optimization program's configuration."""
        return _handle_preview_program(name)

    return router
