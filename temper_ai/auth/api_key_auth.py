"""Per-user API key authentication via FastAPI dependency injection.

Flow: Authorization: Bearer tk_... → SHA-256 hash → DB lookup →
join tenant_memberships for role → return AuthContext.
"""

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

logger = logging.getLogger(__name__)


def _get_pepper() -> str:
    """Read pepper from environment at call time, not import time."""
    return os.environ.get("TEMPER_API_KEY_PEPPER", "")


BEARER_PREFIX = "Bearer "
API_KEY_TOKEN_PREFIX = "tk_"
API_KEY_RANDOM_BYTES = 24  # secrets.token_urlsafe(24) → 32 chars
KEY_PREFIX_DISPLAY_LEN = 8

# Row indices for the _lookup_api_key SELECT result
_ROW_IS_ACTIVE = 3
_ROW_EXPIRES_AT = 4
_ROW_ROLE = 5
_ROW_KEY_HASH = 6


@dataclass(frozen=True)
class AuthContext:
    """Authenticated request context injected by require_auth."""

    user_id: str
    tenant_id: str
    role: str  # "owner" | "editor" | "viewer"
    api_key_id: str  # For audit logging


def hash_api_key(raw_key: str) -> str:
    """HMAC-SHA256 hash an API key with server-side pepper."""
    pepper = _get_pepper()
    if not pepper:
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return hmac.new(
        pepper.encode("utf-8"),
        raw_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        (full_key, key_prefix, key_hash) tuple.
        full_key is shown once to the user, then only key_prefix is stored for display.
    """
    random_part = secrets.token_urlsafe(API_KEY_RANDOM_BYTES)
    full_key = f"{API_KEY_TOKEN_PREFIX}{random_part}"
    key_prefix = full_key[: len(API_KEY_TOKEN_PREFIX) + KEY_PREFIX_DISPLAY_LEN]
    key_hash = hash_api_key(full_key)
    return full_key, key_prefix, key_hash


def _extract_bearer_token(request: Request) -> str | None:
    """Extract Bearer token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith(BEARER_PREFIX):
        return None
    return auth_header[len(BEARER_PREFIX) :].strip()


def _lookup_api_key_sync(key_hash: str) -> dict | None:
    """Synchronous DB lookup for API key — runs in a thread."""
    from sqlmodel import col, select

    from temper_ai.storage.database.manager import get_session
    from temper_ai.storage.database.models_tenancy import APIKey, TenantMembership

    with get_session() as session:
        stmt = (
            select(  # type: ignore[call-overload]
                APIKey.id,
                APIKey.user_id,
                APIKey.tenant_id,
                APIKey.is_active,
                APIKey.expires_at,
                TenantMembership.role,
                APIKey.key_hash,
            )
            .join(
                TenantMembership,
                (TenantMembership.user_id == APIKey.user_id)
                & (TenantMembership.tenant_id == APIKey.tenant_id),
            )
            .where(col(APIKey.key_hash) == key_hash)
        )
        row = session.exec(stmt).first()
        if row is None:
            return None

        # C-09: Defense-in-depth constant-time key hash comparison
        if not hmac.compare_digest(row[_ROW_KEY_HASH], key_hash):
            return None

        # Update usage stats
        api_key_record = session.get(APIKey, row[0])
        if api_key_record is not None:
            api_key_record.last_used_at = datetime.now(UTC)
            api_key_record.total_requests += 1
            session.add(api_key_record)
            session.commit()

        return {
            "api_key_id": row[0],
            "user_id": row[1],
            "tenant_id": row[2],
            "is_active": row[_ROW_IS_ACTIVE],
            "expires_at": row[_ROW_EXPIRES_AT],
            "role": row[_ROW_ROLE],
        }


async def _lookup_api_key(key_hash: str) -> dict | None:
    """Look up API key by hash, joining user and membership info."""
    return await asyncio.to_thread(_lookup_api_key_sync, key_hash)


async def require_auth(request: Request) -> AuthContext:
    """FastAPI dependency: extract and validate Bearer API key.

    Only declare this dependency on routes that require authentication.
    Public routes (signup, health, docs) must not declare this dependency.

    Raises:
        HTTPException 401: Missing/invalid/expired API key.
    """
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Use: Authorization: Bearer tk_...",
        )

    if not token.startswith(API_KEY_TOKEN_PREFIX):
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format. Keys must start with 'tk_'.",
        )

    key_hash = hash_api_key(token)
    result = await _lookup_api_key(key_hash)

    if result is None:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    if not result["is_active"]:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="API key has been revoked.",
        )

    if result["expires_at"] is not None:
        now = datetime.now(UTC)
        expires = result["expires_at"]
        if hasattr(expires, "tzinfo") and expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if now > expires:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="API key has expired.",
            )

    return AuthContext(
        user_id=result["user_id"],
        tenant_id=result["tenant_id"],
        role=result["role"],
        api_key_id=result["api_key_id"],
    )


def require_role(*allowed_roles: str):
    """Factory: create a dependency that checks the user's role.

    Usage: Depends(require_role("owner", "editor"))
    """
    allowed = frozenset(allowed_roles)

    async def _check_role(
        ctx: AuthContext = Depends(require_auth),
    ) -> AuthContext:
        if ctx.role not in allowed:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {sorted(allowed)}, got: {ctx.role}",
            )
        return ctx

    return _check_role


async def authenticate_ws_token(token: str) -> AuthContext | None:
    """Authenticate a WebSocket connection token.

    Returns AuthContext on success, None on failure.
    """
    if not token or not token.startswith(API_KEY_TOKEN_PREFIX):
        return None

    key_hash = hash_api_key(token)
    result = await _lookup_api_key(key_hash)

    if result is None or not result["is_active"]:
        return None

    if result["expires_at"] is not None:
        now = datetime.now(UTC)
        expires = result["expires_at"]
        if hasattr(expires, "tzinfo") and expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if now > expires:
            return None

    return AuthContext(
        user_id=result["user_id"],
        tenant_id=result["tenant_id"],
        role=result["role"],
        api_key_id=result["api_key_id"],
    )
