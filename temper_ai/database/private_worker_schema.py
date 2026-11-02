"""Additive scoped-worker-key migration, separate from C1 custody schema.

The normal database initializer imports guard_models and create_all includes this
table. This callable migrates only this new table for isolated dialect checks or
explicit migration tooling; HTTP/key operations NEVER create missing tables.
Old and new servers can coexist. No existing table, row, or version id changes.
"""
from __future__ import annotations

from sqlalchemy import Engine


def create_private_worker_key_table(engine: Engine) -> None:
    from sqlmodel import SQLModel

    from temper_ai.api.guard_models import RunPrivateKey

    SQLModel.metadata.tables[RunPrivateKey.__tablename__].create(engine, checkfirst=True)
