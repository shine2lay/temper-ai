"""Re-export shim for backward compatibility.

DEPRECATED: Import from temper_ai.storage.database.datetime_utils instead.
"""
import warnings

warnings.warn(
    "Importing from temper_ai.observability.datetime_utils is deprecated. "
    "Import from temper_ai.storage.database.datetime_utils instead.",
    DeprecationWarning,
    stacklevel=2
)

from temper_ai.storage.database.datetime_utils import *  # noqa: F401, F403
