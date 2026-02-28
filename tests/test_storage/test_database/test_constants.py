"""Tests for temper_ai.storage.database.constants.

Verifies constant values, types, and string contents to prevent
accidental modifications that would break database constraints.
"""

from temper_ai.storage.database.constants import (
    CASCADE_ALL_DELETE_ORPHAN,
    CASCADE_SIMPLE,
    FIELD_EXTRA_METADATA,
    FIELD_WORKFLOW_CONFIG_SNAPSHOT,
    FK_AGENT_EXECUTIONS_ID,
    FK_CASCADE,
    FK_STAGE_EXECUTIONS_ID,
    FK_WORKFLOW_EXECUTIONS_ID,
    STATUS_CONSTRAINT,
)


class TestForeignKeyConstants:
    """Test FK-related string constants."""

    def test_fk_cascade_value(self):
        assert FK_CASCADE == "CASCADE"

    def test_fk_cascade_type(self):
        assert isinstance(FK_CASCADE, str)

    def test_fk_workflow_executions_id(self):
        assert FK_WORKFLOW_EXECUTIONS_ID == "workflow_executions.id"

    def test_fk_stage_executions_id(self):
        assert FK_STAGE_EXECUTIONS_ID == "stage_executions.id"

    def test_fk_agent_executions_id(self):
        assert FK_AGENT_EXECUTIONS_ID == "agent_executions.id"

    def test_fk_table_names_contain_dot(self):
        """FK references must contain a dot separator."""
        for fk in (
            FK_WORKFLOW_EXECUTIONS_ID,
            FK_STAGE_EXECUTIONS_ID,
            FK_AGENT_EXECUTIONS_ID,
        ):
            assert "." in fk, f"{fk} must contain a dot"

    def test_fk_references_end_with_id(self):
        """FK table references should point to the id column."""
        for fk in (
            FK_WORKFLOW_EXECUTIONS_ID,
            FK_STAGE_EXECUTIONS_ID,
            FK_AGENT_EXECUTIONS_ID,
        ):
            assert fk.endswith(".id"), f"{fk} should end with '.id'"


class TestCascadeConstants:
    """Test relationship cascade option constants."""

    def test_cascade_all_delete_orphan_value(self):
        assert CASCADE_ALL_DELETE_ORPHAN == "all, delete-orphan"

    def test_cascade_simple_value(self):
        assert CASCADE_SIMPLE == "cascade"

    def test_all_constants_are_strings(self):
        assert isinstance(CASCADE_ALL_DELETE_ORPHAN, str)
        assert isinstance(CASCADE_SIMPLE, str)


class TestFieldNameConstants:
    """Test JSON column key constants."""

    def test_field_workflow_config_snapshot(self):
        assert FIELD_WORKFLOW_CONFIG_SNAPSHOT == "workflow_config_snapshot"

    def test_field_extra_metadata(self):
        assert FIELD_EXTRA_METADATA == "extra_metadata"

    def test_all_field_names_are_strings(self):
        fields = [
            FIELD_WORKFLOW_CONFIG_SNAPSHOT,
            FIELD_EXTRA_METADATA,
        ]
        for field in fields:
            assert isinstance(field, str)

    def test_field_names_are_lowercase_snake_case(self):
        """Field names should use lowercase snake_case for JSON column keys."""
        fields = [
            FIELD_WORKFLOW_CONFIG_SNAPSHOT,
            FIELD_EXTRA_METADATA,
        ]
        for field in fields:
            assert field == field.lower(), f"Field '{field}' should be lowercase"
            assert " " not in field, f"Field '{field}' should not contain spaces"


class TestStatusConstraint:
    """Test the STATUS_CONSTRAINT SQL fragment."""

    def test_status_constraint_is_string(self):
        assert isinstance(STATUS_CONSTRAINT, str)

    def test_status_constraint_contains_all_statuses(self):
        for status in ("running", "completed", "failed", "halted", "timeout"):
            assert (
                status in STATUS_CONSTRAINT
            ), f"'{status}' missing from STATUS_CONSTRAINT"

    def test_status_constraint_contains_in_clause(self):
        assert "IN" in STATUS_CONSTRAINT or "in" in STATUS_CONSTRAINT.lower()

    def test_status_constraint_references_status_column(self):
        assert "status" in STATUS_CONSTRAINT.lower()
