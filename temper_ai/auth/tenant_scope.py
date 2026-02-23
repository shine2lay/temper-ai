"""Reusable tenant-scoped query helpers for multi-tenant isolation.

All DB queries in tenant-aware routes should use these helpers to ensure
rows from one tenant are never visible to another.
"""

import logging
from typing import TypeVar

from sqlmodel import Session, col, select

logger = logging.getLogger(__name__)

T = TypeVar("T")


def scoped_query(session: Session, model: type[T], tenant_id: str):
    """Build a SELECT query scoped to a specific tenant.

    Args:
        session: SQLModel session.
        model: SQLModel table class (must have tenant_id column).
        tenant_id: Tenant ID to filter by.

    Returns:
        SQLModel select statement with WHERE tenant_id = ?.
    """
    return select(model).where(col(model.tenant_id) == tenant_id)  # type: ignore[attr-defined]


def get_scoped(
    session: Session,
    model: type[T],
    tenant_id: str,
    record_id: str,
) -> T | None:
    """Get a single record scoped to a specific tenant.

    Args:
        session: SQLModel session.
        model: SQLModel table class.
        tenant_id: Tenant ID for isolation.
        record_id: Primary key of the record.

    Returns:
        The record if found within the tenant, None otherwise.
    """
    stmt = (
        select(model)
        .where(col(model.id) == record_id)  # type: ignore[attr-defined]
        .where(col(model.tenant_id) == tenant_id)  # type: ignore[attr-defined]
    )
    return session.exec(stmt).first()


def count_scoped(
    session: Session,
    model: type[T],
    tenant_id: str,
) -> int:
    """Count records scoped to a specific tenant.

    Args:
        session: SQLModel session.
        model: SQLModel table class.
        tenant_id: Tenant ID for isolation.

    Returns:
        Number of records belonging to this tenant.
    """
    from sqlalchemy import func

    stmt = (
        select(func.count())
        .select_from(model)
        .where(col(model.tenant_id) == tenant_id)  # type: ignore[attr-defined]
    )
    result = session.exec(stmt).one()
    return int(result)
