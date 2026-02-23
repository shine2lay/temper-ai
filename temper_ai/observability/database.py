"""Re-export shim for backward compatibility.

DEPRECATED: Import from temper_ai.storage.database instead.
"""

import warnings

warnings.warn(
    "Importing from temper_ai.observability.database is deprecated. "
    "Import from temper_ai.storage.database instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export all public API including private functions and module state
from temper_ai.storage.database.manager import *  # noqa: F401, F403
from temper_ai.storage.database.manager import (  # noqa: F401
    _db_lock,
    _db_manager,
    _mask_database_url,
)
