"""Re-export shim for backward compatibility.

DEPRECATED: Import from src.database.datetime_utils instead.
"""
import warnings

warnings.warn(
    "Importing from src.observability.datetime_utils is deprecated. "
    "Import from src.database.datetime_utils instead.",
    DeprecationWarning,
    stacklevel=2
)

from src.database.datetime_utils import *  # noqa: F401, F403
