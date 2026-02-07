"""Re-export shim for backward compatibility.

DEPRECATED: Import from src.database.models instead.
"""
import warnings

warnings.warn(
    "Importing from src.observability.models is deprecated. "
    "Import from src.database.models instead.",
    DeprecationWarning,
    stacklevel=2
)

from src.database.models import *  # noqa: F401, F403
