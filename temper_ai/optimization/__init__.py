"""DSPy prompt optimization integration for Temper AI.

Provides:
- TrainingDataCollector: Extracts training examples from execution history
- DSPyProgramBuilder: Converts agent config into dspy.Module
- DSPyCompiler: Wraps DSPy optimizers (BootstrapFewShot, MIPROv2)
- CompiledProgramStore: JSON file persistence for compiled programs
- DSPyPromptAdapter: Injects compiled program into agent prompts

Requires the ``dspy`` optional dependency:
    pip install 'temper-ai[dspy]'
"""
from temper_ai.optimization._schemas import PromptOptimizationConfig  # noqa: F401


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy import optimization classes on first access."""
    if name == "TrainingDataCollector":
        from temper_ai.optimization.data_collector import TrainingDataCollector
        return TrainingDataCollector
    if name == "DSPyProgramBuilder":
        from temper_ai.optimization.program_builder import DSPyProgramBuilder
        return DSPyProgramBuilder
    if name == "DSPyCompiler":
        from temper_ai.optimization.compiler import DSPyCompiler
        return DSPyCompiler
    if name == "CompiledProgramStore":
        from temper_ai.optimization.program_store import CompiledProgramStore
        return CompiledProgramStore
    if name == "DSPyPromptAdapter":
        from temper_ai.optimization.prompt_adapter import DSPyPromptAdapter
        return DSPyPromptAdapter
    raise AttributeError(f"module 'temper_ai.optimization' has no attribute {name!r}")
