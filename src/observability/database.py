"""Re-export shim for backward compatibility.

DEPRECATED: Import from src.storage.database instead.
"""
import warnings

warnings.warn(
    "Importing from src.observability.database is deprecated. "
    "Import from src.storage.database instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export all public API including private functions and module state
from src.storage.database.manager import *  # noqa: F401, F403
from src.storage.database.manager import _db_lock, _db_manager, _mask_database_url  # noqa: F401
