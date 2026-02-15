"""Backward-compatibility shim — canonical location is ``src.workflow.stage_compiler``."""


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy re-export from canonical module to avoid circular import edge."""
    from src.workflow import stage_compiler as _mod  # noqa: F811

    return getattr(_mod, name)
