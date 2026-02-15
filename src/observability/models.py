"""Re-export shim for backward compatibility.

DEPRECATED: Import from src.storage.database.models instead.
"""
import warnings

warnings.warn(
    "Importing from src.observability.models is deprecated. "
    "Import from src.storage.database.models instead.",
    DeprecationWarning,
    stacklevel=2
)

from src.storage.database.models import *  # noqa: F401, F403
