"""Helper functions for ActionPolicyEngine.

Extracted from ActionPolicyEngine to keep the class below 500 lines.
These are internal implementation details and should not be used directly.
"""

import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any

from temper_ai.safety.constants import (
    ACTION_TYPE_KEY,
    AGENT_ID_KEY,
    POLICY_KEY,
    STAGE_ID_KEY,
    WORKFLOW_ID_KEY,
)
from temper_ai.safety.interfaces import SafetyPolicy, SafetyViolation, ValidationResult

logger = logging.getLogger(__name__)


def canonical_json(obj: Any) -> str:
    """Create canonical JSON representation for deterministic hashing.

    This function ensures that identical logical data always produces
    identical JSON strings, preventing cache collision attacks.

    Security properties:
    - Recursively sorts all dict keys (not just top-level)
    - Deterministic handling of all Python types
    - Resistant to collision attacks via crafted nested structures
    - Platform-independent serialization

    Args:
        obj: Python object to serialize

    Returns:
        Canonical JSON string
    """

    def canonicalize(o: Any) -> Any:
        """Recursively canonicalize an object."""
        if isinstance(o, dict):
            return {k: canonicalize(v) for k, v in sorted(o.items())}
        elif isinstance(o, (list, tuple)):
            return [canonicalize(item) for item in o]
        elif isinstance(o, set):
            return sorted([canonicalize(item) for item in o])
        elif isinstance(o, (str, int, float, bool, type(None))):
            return o
        else:
            return str(o)

    canonical_obj = canonicalize(obj)

    return json.dumps(
        canonical_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def get_cache_key(
    policy: SafetyPolicy,
    action: dict[str, Any],
    agent_id: str,
    action_type: str,
    workflow_id: str,
    stage_id: str,
) -> str:
    """Generate cache key for policy result.

    Creates deterministic hash of policy + action + context.

    SECURITY: Uses canonical JSON serialization to prevent cache
    collision attacks.

    Args:
        policy: Safety policy being validated
        action: Action dict (may contain nested structures)
        agent_id: Agent identifier
        action_type: Type of action
        workflow_id: Workflow identifier
        stage_id: Stage identifier

    Returns:
        SHA-256 hex digest of canonical representation
    """
    data = {
        POLICY_KEY: policy.name,
        "policy_version": policy.version,
        "action": action,
        AGENT_ID_KEY: agent_id,
        ACTION_TYPE_KEY: action_type,
        WORKFLOW_ID_KEY: workflow_id,
        STAGE_ID_KEY: stage_id,
    }

    json_str = canonical_json(data)
    return hashlib.sha256(json_str.encode()).hexdigest()


def get_cached_result(
    cache: "OrderedDict[str, tuple[ValidationResult, float]]",
    cache_key: str,
    cache_ttl: float,
) -> ValidationResult | None:
    """Get cached validation result if available and not expired."""
    if cache_key in cache:
        cached_result, timestamp = cache[cache_key]

        if time.time() - timestamp < cache_ttl:
            cache.move_to_end(cache_key)
            return cached_result
        else:
            del cache[cache_key]

    return None


def cache_result(
    cache: OrderedDict,
    cache_key: str,
    result: ValidationResult,
    max_cache_size: int,
) -> None:
    """Cache validation result with timestamp.

    Uses OrderedDict for O(1) LRU eviction instead of O(n log n) sorted eviction.
    """
    cache[cache_key] = (result, time.time())
    cache.move_to_end(cache_key)

    while len(cache) > max_cache_size:
        evicted_key, _ = cache.popitem(last=False)
        logger.debug("Cache eviction: removed LRU entry %s", evicted_key)


def get_policy_snapshot(registry: Any) -> str:
    """Get a fingerprint of the current set of registered policies."""
    names = sorted(registry.list_policies())
    return hashlib.sha256(",".join(names).encode()).hexdigest()


def context_to_dict(context: Any) -> dict[str, Any]:
    """Convert PolicyExecutionContext to dict for policy validation."""
    return {
        AGENT_ID_KEY: context.agent_id,
        WORKFLOW_ID_KEY: context.workflow_id,
        STAGE_ID_KEY: context.stage_id,
        ACTION_TYPE_KEY: context.action_type,
        "action_data": context.action_data,
        "metadata": context.metadata,
    }


async def log_violations(
    violations: list[SafetyViolation],
    context: Any,
    sanitizer: Any,
) -> None:
    """Log violations to observability system.

    Args:
        violations: List of violations to log
        context: PolicyExecutionContext
        sanitizer: DataSanitizer instance
    """
    for violation in violations:
        safe_message = sanitizer.sanitize_text(violation.message).sanitized_text

        logger.warning(
            f"Safety violation: [{violation.severity.name}] "
            f"{violation.policy_name}: {safe_message}",
            extra={
                AGENT_ID_KEY: context.agent_id,
                WORKFLOW_ID_KEY: context.workflow_id,
                STAGE_ID_KEY: context.stage_id,
                POLICY_KEY: violation.policy_name,
                "severity": violation.severity.name,
                ACTION_TYPE_KEY: context.action_type,
            },
        )


def log_violations_sync(
    violations: list[SafetyViolation],
    context: Any,
    sanitizer: Any,
) -> None:
    """Synchronous version of log_violations."""
    for violation in violations:
        safe_message = sanitizer.sanitize_text(violation.message).sanitized_text

        logger.warning(
            f"Safety violation: [{violation.severity.name}] "
            f"{violation.policy_name}: {safe_message}",
            extra={
                AGENT_ID_KEY: context.agent_id,
                WORKFLOW_ID_KEY: context.workflow_id,
                STAGE_ID_KEY: context.stage_id,
                POLICY_KEY: violation.policy_name,
                "severity": violation.severity.name,
                ACTION_TYPE_KEY: context.action_type,
            },
        )
