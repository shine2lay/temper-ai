"""API key management and user signup endpoints.

Provides public signup and authenticated API key management routes
for the multi-tenant auth system. Prefix: /api/auth.
"""

import logging
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlmodel import col, select
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_429_TOO_MANY_REQUESTS,
)

from temper_ai.auth.api_key_auth import (
    AuthContext,
    generate_api_key,
    require_auth,
)
from temper_ai.storage.database.manager import get_session
from temper_ai.storage.database.models_tenancy import (
    ROLE_OWNER,
    APIKey,
    Tenant,
    TenantMembership,
    UserDB,
)

logger = logging.getLogger(__name__)

# ── Rate limiting ─────────────────────────────────────────────────────

SIGNUP_RATE_LIMIT = 5  # requests per window
API_KEY_RATE_LIMIT = 10  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds
_SLUG_UUID_PREFIX_LEN = 8

_rate_limit_store: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(key: str, max_requests: int) -> bool:
    """Return True if request is allowed, False if rate limited."""
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW
    hits = _rate_limit_store[key]
    # Prune old entries outside the window
    _rate_limit_store[key] = [t for t in hits if t > window_start]
    if len(_rate_limit_store[key]) >= max_requests:
        return False
    _rate_limit_store[key].append(now)
    return True


# ── Request / Response models ─────────────────────────────────────────


class SignupRequest(BaseModel):
    """POST /api/auth/signup request body."""

    email: EmailStr
    name: str | None = None


class CreateApiKeyRequest(BaseModel):
    """POST /api/auth/api-keys request body."""

    label: str | None = "default"


# ── Helper functions ──────────────────────────────────────────────────


def _create_user(session: Any, email: str, name: str) -> UserDB:
    """Create and persist a new UserDB record."""
    existing = session.exec(select(UserDB).where(col(UserDB.email) == email)).first()
    if existing is not None:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="A user with that email already exists.",
        )
    user = UserDB(email=email, name=name)
    session.add(user)
    session.flush()
    return user


def _derive_tenant_slug(email: str) -> str:
    """Derive a tenant slug from an email domain or generate a personal one."""
    try:
        domain = email.split("@", 1)[1].split(".")[0]
        if domain:
            return domain
    except (IndexError, AttributeError):
        pass
    return f"personal-{str(uuid.uuid4())[:_SLUG_UUID_PREFIX_LEN]}"


def _create_tenant(session: Any, slug: str) -> Tenant:
    """Create and persist a new Tenant record, handling slug collisions."""
    base_slug = slug
    suffix = 1
    while (
        session.exec(select(Tenant).where(col(Tenant.slug) == slug)).first() is not None
    ):
        suffix += 1
        slug = f"{base_slug}-{suffix}"
    tenant = Tenant(name=slug, slug=slug)
    session.add(tenant)
    session.flush()
    return tenant


def _create_membership(
    session: Any, tenant_id: str, user_id: str, role: str
) -> TenantMembership:
    """Create and persist a TenantMembership linking user to tenant."""
    membership = TenantMembership(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
    )
    session.add(membership)
    session.flush()
    return membership


def _create_api_key(
    session: Any, user_id: str, tenant_id: str, label: str
) -> tuple[str, APIKey]:
    """Generate and persist an APIKey; returns (full_key, record)."""
    full_key, key_prefix, key_hash = generate_api_key()
    api_key = APIKey(
        user_id=user_id,
        tenant_id=tenant_id,
        label=label,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    session.add(api_key)
    session.flush()
    return full_key, api_key


# ── Endpoint handlers ─────────────────────────────────────────────────


def _handle_signup(body: SignupRequest, request: Request) -> dict[str, Any]:
    """Create user + default tenant + first API key."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"signup:{client_ip}", SIGNUP_RATE_LIMIT):
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many signup requests. Please try again later.",
        )
    email = body.email.strip().lower()
    name = (body.name or "").strip()
    slug = _derive_tenant_slug(email)

    with get_session() as session:
        user = _create_user(session, email, name)
        tenant = _create_tenant(session, slug)
        _create_membership(session, tenant.id, user.id, ROLE_OWNER)
        full_key, api_key = _create_api_key(session, user.id, tenant.id, "default")
        session.commit()
        return {"user_id": user.id, "tenant_id": tenant.id, "api_key": full_key}


def _handle_create_api_key_endpoint(
    body: CreateApiKeyRequest, ctx: AuthContext
) -> dict[str, Any]:
    """Create an additional API key for the authenticated user."""
    if not _check_rate_limit(f"api-key:{ctx.user_id}", API_KEY_RATE_LIMIT):
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many API key creation requests. Please try again later.",
        )
    label = (body.label or "default").strip()
    with get_session() as session:
        full_key, api_key = _create_api_key(session, ctx.user_id, ctx.tenant_id, label)
        session.commit()
        return {
            "api_key_id": api_key.id,
            "api_key": full_key,
            "key_prefix": api_key.key_prefix,
            "label": api_key.label,
        }


def _handle_list_api_keys(ctx: AuthContext) -> dict[str, Any]:
    """List API keys for the authenticated user (prefix only)."""
    with get_session() as session:
        keys = session.exec(
            select(APIKey).where(col(APIKey.user_id) == ctx.user_id)
        ).all()
        return {
            "keys": [
                {
                    "id": k.id,
                    "label": k.label,
                    "key_prefix": k.key_prefix,
                    "is_active": k.is_active,
                    "created_at": k.created_at.isoformat(),
                    "last_used_at": (
                        k.last_used_at.isoformat() if k.last_used_at else None
                    ),
                    "total_requests": k.total_requests,
                }
                for k in keys
            ]
        }


def _handle_revoke_api_key(key_id: str, ctx: AuthContext) -> dict[str, Any]:
    """Revoke an API key (soft-delete: set is_active=False)."""
    with get_session() as session:
        api_key = session.get(APIKey, key_id)
        if api_key is None or api_key.user_id != ctx.user_id:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND, detail="API key not found."
            )
        api_key.is_active = False
        session.add(api_key)
        session.commit()
        return {"revoked": True}


def _handle_me(ctx: AuthContext) -> dict[str, Any]:
    """Return current user + tenant info."""
    with get_session() as session:
        user = session.get(UserDB, ctx.user_id)
        if user is None:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND, detail="User not found."
            )
        tenant = session.get(Tenant, ctx.tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND, detail="Tenant not found."
            )
        membership = session.exec(
            select(TenantMembership).where(
                (col(TenantMembership.user_id) == ctx.user_id)
                & (col(TenantMembership.tenant_id) == ctx.tenant_id)
            )
        ).first()
        role = membership.role if membership else ctx.role
        return {
            "user": {"id": user.id, "email": user.email, "name": user.name},
            "tenant": {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "plan": tenant.plan,
            },
            "role": role,
        }


# ── Router factory ────────────────────────────────────────────────────


def create_auth_router() -> APIRouter:
    """Create the /api/auth router."""
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/signup")
    def signup(body: SignupRequest, request: Request) -> dict[str, Any]:
        """Register a new user account."""
        return _handle_signup(body, request)

    @router.post("/api-keys")
    def create_api_key(
        body: CreateApiKeyRequest, ctx: AuthContext = Depends(require_auth)
    ) -> dict[str, Any]:
        """Create a new API key for the authenticated user."""
        return _handle_create_api_key_endpoint(body, ctx)

    @router.get("/api-keys")
    def list_api_keys(ctx: AuthContext = Depends(require_auth)) -> dict[str, Any]:
        """List all API keys for the authenticated user."""
        return _handle_list_api_keys(ctx)

    @router.delete("/api-keys/{key_id}")
    def revoke_api_key(
        key_id: str, ctx: AuthContext = Depends(require_auth)
    ) -> dict[str, Any]:
        """Revoke an API key by ID."""
        return _handle_revoke_api_key(key_id, ctx)

    @router.post("/ws-ticket")
    def create_ws_ticket(ctx: AuthContext = Depends(require_auth)) -> dict[str, Any]:
        """Create a WebSocket authentication ticket."""
        from temper_ai.auth.ws_tickets import generate_ws_ticket

        return {"ticket": generate_ws_ticket(ctx)}

    @router.get("/me")
    def me(ctx: AuthContext = Depends(require_auth)) -> dict[str, Any]:
        """Get the current authenticated user profile."""
        return _handle_me(ctx)

    return router
