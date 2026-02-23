"""Re-export shim for backward compatibility.

DEPRECATED: Import from temper_ai.storage.database.models instead.
"""

import warnings

warnings.warn(
    "Importing from temper_ai.observability.models is deprecated. "
    "Import from temper_ai.storage.database.models instead.",
    DeprecationWarning,
    stacklevel=2,
)

from temper_ai.storage.database.models import *  # noqa: F401, F403
