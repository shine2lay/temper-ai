"""Explicit additive metadata install; no content migration or import-time work.

This repository currently uses table-scoped create_all, not Alembic revisions.
Normal composition may call install_metadata(engine); importing service does not.
Existing tables/rows remain untouched. No destructive down migration is supplied.
"""
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from .models import (
    PrivateAttemptRow,
    PrivateContextRow,
    PrivateFenceRow,
    PrivateInvocationRow,
    PrivateRefusalRow,
)

TABLES = tuple(SQLModel.metadata.tables[model.__tablename__] for model in (PrivateFenceRow, PrivateContextRow, PrivateInvocationRow, PrivateAttemptRow, PrivateRefusalRow))


def install_metadata(engine: Engine) -> None:
    if engine.dialect.name not in {"sqlite", "postgresql"}:
        raise ValueError("private metadata dialect unavailable")
    with engine.begin() as connection:
        SQLModel.metadata.create_all(connection, tables=TABLES)
        insert = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
        connection.execute(insert(PrivateFenceRow).values(id=1, revision=0).on_conflict_do_nothing(index_elements=["id"]))
