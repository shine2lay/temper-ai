"""DSPy prompt optimization integration for Temper AI.

Provides:
- TrainingDataCollector: Extracts training examples from execution history
- DSPyProgramBuilder: Converts agent config into dspy.Module
- DSPyCompiler: Wraps pluggable DSPy optimizers via registry dispatch
- CompiledProgramStore: JSON file persistence for compiled programs
- DSPyPromptAdapter: Injects compiled program into agent prompts
- Registries: get_metric, get_optimizer, get_module_builder (+ register/list)

Requires the ``dspy`` optional dependency:
    pip install 'temper-ai[dspy]'
"""

from temper_ai.optimization.dspy._schemas import PromptOptimizationConfig  # noqa: F401

# Mapping of lazy attribute name → (module_path, object_name)
_LAZY_IMPORTS = {
    "TrainingDataCollector": (
        "temper_ai.optimization.dspy.data_collector",
        "TrainingDataCollector",
    ),
    "DSPyProgramBuilder": (
        "temper_ai.optimization.dspy.program_builder",
        "DSPyProgramBuilder",
    ),
    "DSPyCompiler": ("temper_ai.optimization.dspy.compiler", "DSPyCompiler"),
    "CompiledProgramStore": (
        "temper_ai.optimization.dspy.program_store",
        "CompiledProgramStore",
    ),
    "DSPyPromptAdapter": (
        "temper_ai.optimization.dspy.prompt_adapter",
        "DSPyPromptAdapter",
    ),
    # Metric registry
    "get_metric": ("temper_ai.optimization.dspy.metrics", "get_metric"),
    "register_metric": ("temper_ai.optimization.dspy.metrics", "register_metric"),
    "list_metrics": ("temper_ai.optimization.dspy.metrics", "list_metrics"),
    # Optimizer registry
    "get_optimizer": ("temper_ai.optimization.dspy.optimizers", "get_optimizer"),
    "register_optimizer": (
        "temper_ai.optimization.dspy.optimizers",
        "register_optimizer",
    ),
    "list_optimizers": ("temper_ai.optimization.dspy.optimizers", "list_optimizers"),
    # Module registry
    "get_module_builder": ("temper_ai.optimization.dspy.modules", "get_module_builder"),
    "register_module": ("temper_ai.optimization.dspy.modules", "register_module"),
    "list_modules": ("temper_ai.optimization.dspy.modules", "list_modules"),
}


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy import optimization classes and registry functions on first access."""
    if name in _LAZY_IMPORTS:
        module_path, obj_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, obj_name)
    raise AttributeError(
        f"module 'temper_ai.optimization.dspy' has no attribute {name!r}"
    )
