"""Timezone-aware datetime utilities for observability system.

Delegates to the canonical implementation in ``temper_ai.shared.utils.datetime_utils``
while preserving backward-compatible imports for all existing consumers.
"""

from temper_ai.shared.utils.datetime_utils import (  # noqa: F401
    ensure_utc as ensure_utc,
)
from temper_ai.shared.utils.datetime_utils import (
    safe_duration_seconds as safe_duration_seconds,
)
from temper_ai.shared.utils.datetime_utils import (
    utcnow as utcnow,
)
from temper_ai.shared.utils.datetime_utils import (
    validate_utc_aware as validate_utc_aware,
)

__all__ = [
    "utcnow",
    "ensure_utc",
    "validate_utc_aware",
    "safe_duration_seconds",
]
