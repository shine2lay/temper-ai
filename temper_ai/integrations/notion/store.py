"""Reads and writes of the Notion tables (see models.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import col, select

from temper_ai.integrations.notion.client import normalize_id
from temper_ai.integrations.notion.models import (
    NotionComment,
    NotionRun,
    NotionState,
)


def _session() -> Any:
    from temper_ai.database import get_session

    return get_session()


# -- runs ------------------------------------------------------------------------

def save_run(execution_id: str, page_id: str, origin: bool = True, rule: str = "",
             discussion_id: str = "") -> None:
    with _session() as session:
        session.add(NotionRun(execution_id=execution_id, page_id=normalize_id(page_id), origin=origin,
                              rule=rule, discussion_id=discussion_id))
        session.commit()


def pages_of(execution_id: str, origin_only: bool = False) -> list[dict[str, Any]]:
    """The pages a run reports to, oldest first."""
    with _session() as session:
        stmt = select(NotionRun).where(NotionRun.execution_id == execution_id)
        if origin_only:
            stmt = stmt.where(NotionRun.origin == True)  # noqa: E712 - SQL
        return [{"page_id": r.page_id, "discussion_id": r.discussion_id, "rule": r.rule, "origin": r.origin}
                for r in session.exec(stmt.order_by(col(NotionRun.id))).all()]


def set_discussion(execution_id: str, page_id: str, discussion_id: str) -> None:
    """The thread a run's comments on a page go in (the page is tied to the
    run if it was not yet: a place its ``notify:`` names)."""
    with _session() as session:
        row = session.exec(select(NotionRun).where(NotionRun.execution_id == execution_id,
                                                   NotionRun.page_id == normalize_id(page_id))).first()
        if row is None:
            row = NotionRun(execution_id=execution_id, page_id=normalize_id(page_id), origin=False)
        row.discussion_id = discussion_id
        session.add(row)
        session.commit()


def runs_for_page(page_id: str) -> list[str]:
    """Run ids started from a page, newest first."""
    with _session() as session:
        rows = session.exec(select(NotionRun).where(NotionRun.page_id == normalize_id(page_id),
                                                    NotionRun.origin == True)  # noqa: E712 - SQL
                            .order_by(col(NotionRun.id).desc())).all()
        return [r.execution_id for r in rows]


# Notion's events are kept in the event inbox (integrations.inbox).


# -- comments temper posted ------------------------------------------------------

def save_comment(comment_id: str, page_id: str, execution_id: str = "", discussion_id: str = "",
                 question: bool = False) -> None:
    with _session() as session:
        session.merge(NotionComment(comment_id=normalize_id(comment_id), page_id=normalize_id(page_id),
                                    execution_id=execution_id, discussion_id=discussion_id, question=question))
        session.commit()


def is_ours(comment_id: str) -> bool:
    with _session() as session:
        return session.get(NotionComment, normalize_id(comment_id)) is not None


def question_in(discussion_id: str) -> str | None:
    """The run whose question was posted in this discussion, newest first."""
    with _session() as session:
        row = session.exec(select(NotionComment).where(NotionComment.discussion_id == discussion_id,
                                                       NotionComment.question == True)  # noqa: E712
                           .order_by(col(NotionComment.created_at).desc())).first()
        return row.execution_id if row else None


# -- state -----------------------------------------------------------------------

def get_state(key: str) -> str | None:
    with _session() as session:
        row = session.get(NotionState, key)
        return row.value if row else None


def set_state(key: str, value: str) -> None:
    with _session() as session:
        row = session.get(NotionState, key) or NotionState(key=key)
        row.value = value
        row.updated_at = datetime.now(UTC)
        session.add(row)
        session.commit()
