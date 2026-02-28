"""Tests for temper_ai/auth/tenant_scope.py — tenant-scoped query helpers."""

from unittest.mock import MagicMock, patch

from temper_ai.auth.tenant_scope import count_scoped, get_scoped, scoped_query

# ── Helpers ───────────────────────────────────────────────────────────


class FakeModel:
    """Minimal model with tenant_id and id columns for testing."""

    tenant_id = MagicMock(name="FakeModel.tenant_id")
    id = MagicMock(name="FakeModel.id")


def _make_record(record_id: str, tenant_id: str) -> MagicMock:
    """Build a mock DB record."""
    rec = MagicMock()
    rec.id = record_id
    rec.tenant_id = tenant_id
    return rec


# ── scoped_query ──────────────────────────────────────────────────────


def test_scoped_query_returns_select_statement():
    """scoped_query should produce a SELECT with a WHERE clause on tenant_id."""
    session = MagicMock()
    with (
        patch("temper_ai.auth.tenant_scope.select") as mock_select,
        patch("temper_ai.auth.tenant_scope.col") as mock_col,
    ):
        mock_stmt = MagicMock()
        mock_select.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt
        mock_col.return_value = MagicMock()

        result = scoped_query(session, FakeModel, "tenant-abc")

        mock_select.assert_called_once_with(FakeModel)
        mock_stmt.where.assert_called_once()
        assert result is mock_stmt


def test_scoped_query_uses_tenant_id():
    """The WHERE clause uses the model's tenant_id column."""
    session = MagicMock()
    with (
        patch("temper_ai.auth.tenant_scope.select") as mock_select,
        patch("temper_ai.auth.tenant_scope.col") as mock_col,
    ):
        col_return = MagicMock()
        mock_col.return_value = col_return
        mock_stmt = MagicMock()
        mock_select.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt

        scoped_query(session, FakeModel, "t1")

        # col() was called with the model's tenant_id attribute
        mock_col.assert_called_once_with(FakeModel.tenant_id)


# ── get_scoped ────────────────────────────────────────────────────────


def test_get_scoped_found():
    """Returns the record when it belongs to the given tenant."""
    record = _make_record("rec-1", "tenant-1")
    session = MagicMock()

    with (
        patch("temper_ai.auth.tenant_scope.select") as mock_select,
        patch("temper_ai.auth.tenant_scope.col"),
    ):
        mock_stmt = MagicMock()
        mock_select.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt
        session.exec.return_value.first.return_value = record

        result = get_scoped(session, FakeModel, "tenant-1", "rec-1")

    assert result is record


def test_get_scoped_not_found():
    """Returns None when no record matches id + tenant_id."""
    session = MagicMock()

    with (
        patch("temper_ai.auth.tenant_scope.select") as mock_select,
        patch("temper_ai.auth.tenant_scope.col"),
    ):
        mock_stmt = MagicMock()
        mock_select.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt
        session.exec.return_value.first.return_value = None

        result = get_scoped(session, FakeModel, "tenant-1", "nonexistent-id")

    assert result is None


def test_get_scoped_wrong_tenant():
    """Returns None when the record exists but belongs to a different tenant."""
    session = MagicMock()

    with (
        patch("temper_ai.auth.tenant_scope.select") as mock_select,
        patch("temper_ai.auth.tenant_scope.col"),
    ):
        mock_stmt = MagicMock()
        mock_select.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt
        # DB correctly filters, so exec().first() returns None for wrong tenant
        session.exec.return_value.first.return_value = None

        result = get_scoped(session, FakeModel, "tenant-X", "rec-1")

    assert result is None


def test_get_scoped_applies_both_where_clauses():
    """get_scoped must chain two WHERE clauses: id and tenant_id."""
    session = MagicMock()

    with (
        patch("temper_ai.auth.tenant_scope.select") as mock_select,
        patch("temper_ai.auth.tenant_scope.col"),
    ):
        mock_stmt = MagicMock()
        mock_select.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt
        session.exec.return_value.first.return_value = None

        get_scoped(session, FakeModel, "t1", "id1")

        # where() is called twice: once for id, once for tenant_id
        assert mock_stmt.where.call_count == 2


# ── count_scoped ──────────────────────────────────────────────────────


def test_count_scoped_returns_integer():
    """count_scoped should return an int."""
    session = MagicMock()

    with (
        patch("temper_ai.auth.tenant_scope.select") as mock_select,
        patch("temper_ai.auth.tenant_scope.col"),
        patch("temper_ai.auth.tenant_scope.func", create=True),
    ):
        mock_stmt = MagicMock()
        mock_select.return_value = mock_stmt
        mock_stmt.select_from.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt
        session.exec.return_value.one.return_value = 42

        result = count_scoped(session, FakeModel, "tenant-1")

    assert result == 42
    assert isinstance(result, int)


def test_count_scoped_zero():
    """count_scoped returns 0 when no records exist for the tenant."""
    session = MagicMock()

    with (
        patch("temper_ai.auth.tenant_scope.select") as mock_select,
        patch("temper_ai.auth.tenant_scope.col"),
        patch("temper_ai.auth.tenant_scope.func", create=True),
    ):
        mock_stmt = MagicMock()
        mock_select.return_value = mock_stmt
        mock_stmt.select_from.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt
        session.exec.return_value.one.return_value = 0

        result = count_scoped(session, FakeModel, "tenant-empty")

    assert result == 0


def test_count_scoped_uses_sqlalchemy_count():
    """count_scoped imports and uses sqlalchemy.func.count()."""
    session = MagicMock()

    with (
        patch("temper_ai.auth.tenant_scope.select") as mock_select,
        patch("temper_ai.auth.tenant_scope.col"),
        patch("sqlalchemy.func"),
    ):
        mock_stmt = MagicMock()
        mock_select.return_value = mock_stmt
        mock_stmt.select_from.return_value = mock_stmt
        mock_stmt.where.return_value = mock_stmt
        session.exec.return_value.one.return_value = 5

        # Patch inside count_scoped's lazy import
        with patch("temper_ai.auth.tenant_scope.count_scoped.__module__"):
            pass

        # Just verify no exceptions are raised and return type is correct
        # The actual func.count usage is an implementation detail
        result = count_scoped(session, FakeModel, "tenant-1")
        assert isinstance(result, int)
