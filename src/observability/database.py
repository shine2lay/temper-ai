"""Re-export shim for backward compatibility.

DEPRECATED: Import from src.database instead.
"""
import warnings

warnings.warn(
    "Importing from src.observability.database is deprecated. "
    "Import from src.database instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export all public API including private functions and module state
from src.database.manager import *  # noqa: F401, F403
from src.database.manager import _mask_database_url, _db_manager  # noqa: F401
