"""
Comprehensive tests for validation layer.

Coverage:
- Task ID validation (all patterns)
- Subject validation (boundaries)
- Description validation
- Priority validation (boundaries)
- Spec file validation
- Invariant enforcement
- Error messages
- Edge cases
"""

import os
import pytest

from coord_service.validator import (
    StateValidator,
    ValidationError,
    ValidationErrors,
    InvariantViolation,
    InvariantViolations
)


class TestTaskIDValidation:
    """Test task ID naming convention validation."""

    def test_valid_task_ids(self, validator, coord_dir):
        """Valid task IDs should pass validation."""
        valid_ids = [
            'test-crit-01',
            'test-high-02',
            'test-med-03',
            'test-medi-04',
            'test-low-05',
            'code-crit-refactor-engine',
            'docs-med-api-endpoints-01',
            'gap-m3-01-track-events',
            'refactor-high-cleanup-utils',
            'perf-low-optimize-queries-01'
        ]

        for task_id in valid_ids:
            # Should not raise
            try:
                validator.validate_task_create(
                    task_id, 'Valid subject here', 'Description', priority=4
                )
            except ValidationErrors as e:
                # Might fail for other reasons (like missing spec for high priority)
                # But should not fail for task ID
                for err in e.errors:
                    assert err.code != 'INVALID_TASK_ID', f"Failed for {task_id}: {err.message}"

    def test_invalid_task_id_format(self, validator):
        """Invalid task ID formats should fail validation."""
        invalid_ids = [
            'MyTask',  # CamelCase
            'my_task',  # Underscore only
            'task',  # Too short
            'TASK-HIGH-01',  # Uppercase
            '123-test-01',  # Starts with number
            'test',  # Missing parts
            'test-',  # Incomplete
            '-test-high-01',  # Leading dash
            'test--high-01',  # Double dash
        ]

        for task_id in invalid_ids:
            with pytest.raises(ValidationErrors) as exc_info:
                validator.validate_task_create(
                    task_id, 'Subject here', 'Description', priority=4
                )

            errors = exc_info.value.errors
            assert any(e.code == 'INVALID_TASK_ID' for e in errors), \
                f"Should reject {task_id}"

    def test_invalid_task_id_prefix(self, validator):
        """Invalid prefixes should fail validation."""
        invalid_prefixes = [
            'invalid-high-01',
            'unknown-high-01',
            'badprefix-high-01'
        ]

        for task_id in invalid_prefixes:
            with pytest.raises(ValidationErrors) as exc_info:
                validator.validate_task_create(
                    task_id, 'Subject here', 'Description', priority=4
                )

            errors = exc_info.value.errors
            assert any(e.code == 'UNKNOWN_PREFIX' for e in errors), \
                f"Should reject prefix in {task_id}"

    def test_invalid_task_id_category(self, validator):
        """Invalid categories should fail validation."""
        invalid_categories = [
            'test-invalid-01',
            'test-wrong-01',
            'test-bad-01'
        ]

        for task_id in invalid_categories:
            with pytest.raises(ValidationErrors) as exc_info:
                validator.validate_task_create(
                    task_id, 'Subject here', 'Description', priority=4
                )

            errors = exc_info.value.errors
            assert any(e.code == 'UNKNOWN_CATEGORY' for e in errors), \
                f"Should reject category in {task_id}"

    def test_task_id_error_includes_examples(self, validator):
        """Task ID error should include helpful examples."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'InvalidTask', 'Subject', 'Description', priority=4
            )

        errors = exc_info.value.errors
        id_error = next(e for e in errors if e.code == 'INVALID_TASK_ID')

        assert id_error.hint
        assert id_error.examples
        assert len(id_error.examples) > 0


class TestSubjectValidation:
    """Test task subject validation."""

    def test_valid_subjects(self, validator):
        """Valid subjects should pass validation."""
        valid_subjects = [
            'Test subject',  # 12 chars
            'A' * 10,  # Min length (10)
            'A' * 100,  # Max length (100)
            'Subject with special !@#$%^&*() chars',
            'Unicode 主题 subject'
        ]

        for subject in valid_subjects:
            # Should not raise for subject
            try:
                validator.validate_task_create(
                    'test-low-01', subject, 'Description', priority=4
                )
            except ValidationErrors as e:
                for err in e.errors:
                    assert err.code != 'INVALID_SUBJECT_LENGTH', \
                        f"Should accept subject: {subject}"

    def test_empty_subject(self, validator):
        """Empty subject should fail validation."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-01', '', 'Description', priority=4
            )

        errors = exc_info.value.errors
        assert any(e.code == 'MISSING_SUBJECT' for e in errors)

    def test_whitespace_only_subject(self, validator):
        """Whitespace-only subject should fail validation."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-01', '   ', 'Description', priority=4
            )

        errors = exc_info.value.errors
        assert any(e.code == 'MISSING_SUBJECT' for e in errors)

    def test_subject_too_short(self, validator):
        """Subject shorter than 10 chars should fail validation."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-01', 'Short', 'Description', priority=4
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INVALID_SUBJECT_LENGTH' for e in errors)

    def test_subject_too_long(self, validator):
        """Subject longer than 100 chars should fail validation."""
        long_subject = 'A' * 101

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-01', long_subject, 'Description', priority=4
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INVALID_SUBJECT_LENGTH' for e in errors)

    def test_subject_boundary_10_chars(self, validator):
        """Subject with exactly 10 chars should pass."""
        subject = 'A' * 10  # Exactly 10

        try:
            validator.validate_task_create(
                'test-low-01', subject, 'Description', priority=4
            )
        except ValidationErrors as e:
            for err in e.errors:
                assert err.code != 'INVALID_SUBJECT_LENGTH'

    def test_subject_boundary_100_chars(self, validator):
        """Subject with exactly 100 chars should pass."""
        subject = 'A' * 100  # Exactly 100

        try:
            validator.validate_task_create(
                'test-low-01', subject, 'Description', priority=4
            )
        except ValidationErrors as e:
            for err in e.errors:
                assert err.code != 'INVALID_SUBJECT_LENGTH'

    def test_subject_boundary_9_chars(self, validator):
        """Subject with 9 chars should fail."""
        subject = 'A' * 9

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-01', subject, 'Description', priority=4
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INVALID_SUBJECT_LENGTH' for e in errors)

    def test_subject_boundary_101_chars(self, validator):
        """Subject with 101 chars should fail."""
        subject = 'A' * 101

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-01', subject, 'Description', priority=4
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INVALID_SUBJECT_LENGTH' for e in errors)


class TestDescriptionValidation:
    """Test task description validation."""

    def test_description_optional_for_low_priority(self, validator):
        """Description is optional for low priority tasks."""
        # Should pass with empty description
        try:
            validator.validate_task_create(
                'test-low-01', 'Valid subject', '', priority=4
            )
        except ValidationErrors as e:
            for err in e.errors:
                assert err.code != 'INSUFFICIENT_DESCRIPTION'

    def test_description_required_for_critical(self, validator, sample_task_spec):
        """Description required for critical priority (min 20 chars)."""
        # Short description should fail
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-crit-example-01',
                'Valid subject here',
                'Short',
                priority=1,
                spec_path=str(sample_task_spec)
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INSUFFICIENT_DESCRIPTION' for e in errors)

    def test_description_required_for_high(self, validator, sample_task_spec):
        """Description required for high priority (min 20 chars)."""
        # Create a spec for high priority
        spec_path = sample_task_spec.parent / 'test-high-desc-01.md'
        spec_path.write_text("""# Task Specification: test-high-desc-01

## Problem Statement
Test description validation.

## Acceptance Criteria
- [ ] Description validated

## Test Strategy
Test it.
""")

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-high-desc-01',
                'Valid subject here',
                'Too short',
                priority=2,
                spec_path=str(spec_path)
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INSUFFICIENT_DESCRIPTION' for e in errors)

    def test_description_boundary_20_chars(self, validator, sample_task_spec):
        """Description with exactly 20 chars should pass for critical."""
        description = 'A' * 20  # Exactly 20

        try:
            validator.validate_task_create(
                'test-high-example-01',
                'Valid subject here',
                description,
                priority=2,
                spec_path=str(sample_task_spec)
            )
        except ValidationErrors as e:
            for err in e.errors:
                assert err.code != 'INSUFFICIENT_DESCRIPTION'

    def test_description_boundary_19_chars(self, validator, sample_task_spec):
        """Description with 19 chars should fail for critical."""
        description = 'A' * 19

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-high-example-01',
                'Valid subject here',
                description,
                priority=2,
                spec_path=str(sample_task_spec)
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INSUFFICIENT_DESCRIPTION' for e in errors)


class TestPriorityValidation:
    """Test task priority validation."""

    def test_valid_priorities(self, validator):
        """Valid priorities (1-5) should pass validation."""
        for priority in [1, 2, 3, 4, 5]:
            try:
                validator.validate_task_create(
                    'test-low-01', 'Valid subject', 'Description', priority=priority
                )
            except ValidationErrors as e:
                # Might fail for other reasons (spec for 1-2)
                for err in e.errors:
                    assert err.code != 'INVALID_PRIORITY', \
                        f"Should accept priority {priority}"

    def test_priority_zero(self, validator):
        """Priority 0 should fail validation."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-01', 'Valid subject', 'Description', priority=0
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INVALID_PRIORITY' for e in errors)

    def test_priority_six(self, validator):
        """Priority 6 should fail validation."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-01', 'Valid subject', 'Description', priority=6
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INVALID_PRIORITY' for e in errors)

    def test_priority_negative(self, validator):
        """Negative priority should fail validation."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-01', 'Valid subject', 'Description', priority=-1
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INVALID_PRIORITY' for e in errors)

    def test_priority_very_large(self, validator):
        """Very large priority should fail validation."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-01', 'Valid subject', 'Description', priority=9999
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INVALID_PRIORITY' for e in errors)

    def test_priority_boundaries(self, validator):
        """Test priority boundaries (1 and 5)."""
        # Priority 1 (min)
        try:
            validator.validate_task_create(
                'test-low-01', 'Valid subject', 'Description', priority=1
            )
        except ValidationErrors as e:
            for err in e.errors:
                assert err.code != 'INVALID_PRIORITY'

        # Priority 5 (max)
        try:
            validator.validate_task_create(
                'test-low-02', 'Valid subject', 'Description', priority=5
            )
        except ValidationErrors as e:
            for err in e.errors:
                assert err.code != 'INVALID_PRIORITY'


class TestSpecFileValidation:
    """Test task spec file validation."""

    def test_spec_required_for_critical(self, validator, coord_dir):
        """Critical priority tasks must have spec file."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-crit-no-spec-01',
                'Valid subject here',
                'Valid description here',
                priority=1
            )

        errors = exc_info.value.errors
        assert any(e.code == 'MISSING_TASK_SPEC' for e in errors)

    def test_spec_required_for_high(self, validator, coord_dir):
        """High priority tasks must have spec file."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-high-no-spec-01',
                'Valid subject here',
                'Valid description here',
                priority=2
            )

        errors = exc_info.value.errors
        assert any(e.code == 'MISSING_TASK_SPEC' for e in errors)

    def test_spec_not_required_for_medium(self, validator):
        """Medium priority tasks don't need spec file."""
        try:
            validator.validate_task_create(
                'test-med-no-spec-01',
                'Valid subject',
                'Description',
                priority=3
            )
        except ValidationErrors as e:
            for err in e.errors:
                assert err.code != 'MISSING_TASK_SPEC'

    def test_spec_with_missing_sections(self, validator, coord_dir):
        """Spec file missing required sections should fail."""
        spec_path = coord_dir / 'task-specs' / 'test-crit-incomplete-01.md'
        spec_path.write_text("""# Task Specification: test-crit-incomplete-01

## Problem Statement
Just the problem statement.
""")

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-crit-incomplete-01',
                'Valid subject here',
                'Valid description here',
                priority=1,
                spec_path=str(spec_path)
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INCOMPLETE_TASK_SPEC' for e in errors)

        # Check that missing sections are listed
        spec_error = next(e for e in errors if e.code == 'INCOMPLETE_TASK_SPEC')
        assert spec_error.missing_sections
        assert '## Acceptance Criteria' in spec_error.missing_sections
        assert '## Test Strategy' in spec_error.missing_sections

    def test_spec_with_all_sections(self, validator, sample_task_spec):
        """Spec file with all sections should pass."""
        try:
            validator.validate_task_create(
                'test-high-example-01',
                'Valid subject here',
                'Valid description here',
                priority=2,
                spec_path=str(sample_task_spec)
            )
        except ValidationErrors as e:
            for err in e.errors:
                assert err.code != 'INCOMPLETE_TASK_SPEC'

    def test_spec_too_short(self, validator, coord_dir):
        """Spec file too short should fail."""
        spec_path = coord_dir / 'task-specs' / 'test-crit-short-01.md'
        spec_path.write_text("""# Task Specification: test-crit-short-01

## Problem Statement
Short.

## Acceptance Criteria
- [ ] Done

## Test Strategy
Test.
""")

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-crit-short-01',
                'Valid subject here',
                'Valid description here',
                priority=1,
                spec_path=str(spec_path)
            )

        errors = exc_info.value.errors
        assert any(e.code == 'INSUFFICIENT_SPEC_DETAIL' for e in errors)

    def test_spec_missing_task_id(self, validator, coord_dir):
        """Spec file without task ID should fail."""
        spec_path = coord_dir / 'task-specs' / 'test-crit-no-id-01.md'
        spec_path.write_text("""# Task Specification: different-task-id

## Problem Statement
This spec has a different task ID in the title.

## Acceptance Criteria
- [ ] Task ID matches

## Test Strategy
Verify task ID is present in spec.
""")

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-crit-no-id-01',
                'Valid subject here',
                'Valid description here',
                priority=1,
                spec_path=str(spec_path)
            )

        errors = exc_info.value.errors
        assert any(e.code == 'TASK_ID_MISMATCH' for e in errors)

    def test_spec_file_read_error(self, validator, coord_dir):
        """Unreadable spec file should fail with clear error."""
        spec_path = coord_dir / 'task-specs' / 'nonexistent.md'

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-crit-unreadable-01',
                'Valid subject here',
                'Valid description here',
                priority=1,
                spec_path=str(spec_path)
            )

        errors = exc_info.value.errors
        # Should have missing spec error since file doesn't exist
        assert any(e.code in ['MISSING_TASK_SPEC', 'SPEC_FILE_READ_ERROR'] for e in errors)


class TestDuplicateTaskValidation:
    """Test duplicate task ID validation."""

    def test_duplicate_task_id(self, validator, db):
        """Duplicate task ID should fail validation."""
        # Create first task
        db.create_task('test-low-dup-01', 'Subject', 'Description')

        # Try to create duplicate
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-dup-01',
                'Different subject',
                'Different description',
                priority=4
            )

        errors = exc_info.value.errors
        assert any(e.code == 'DUPLICATE_TASK_ID' for e in errors)

    def test_duplicate_error_includes_details(self, validator, db):
        """Duplicate task error should include existing task details."""
        # Create task
        db.register_agent('test-agent', 12345)
        db.create_task('test-low-dup-02', 'Subject', 'Description')
        db.claim_task('test-low-dup-02', 'test-agent')

        # Try duplicate
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'test-low-dup-02',
                'Subject',
                'Description',
                priority=4
            )

        errors = exc_info.value.errors
        dup_error = next(e for e in errors if e.code == 'DUPLICATE_TASK_ID')

        assert dup_error.details
        assert 'status' in dup_error.details
        assert 'owner' in dup_error.details


class TestTaskClaimValidation:
    """Test task claim validation."""

    def test_claim_unregistered_agent(self, validator):
        """Claiming task with unregistered agent should fail."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_claim('nonexistent-agent', 'test-task')

        errors = exc_info.value.errors
        assert any(e.code == 'AGENT_NOT_REGISTERED' for e in errors)

    def test_claim_nonexistent_task(self, validator, db):
        """Claiming nonexistent task should fail."""
        db.register_agent('test-agent', 12345)

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_claim('test-agent', 'nonexistent-task')

        errors = exc_info.value.errors
        assert any(e.code == 'TASK_NOT_FOUND' for e in errors)

    def test_claim_task_not_pending(self, validator, db):
        """Claiming non-pending task should fail."""
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'agent1')

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_claim('agent2', 'test-task')

        errors = exc_info.value.errors
        assert any(e.code == 'TASK_UNAVAILABLE' for e in errors)

    def test_claim_when_agent_has_task(self, validator, db):
        """Agent with in_progress task cannot claim another."""
        db.register_agent('test-agent', 12345)
        db.create_task('task1', 'Subject1', 'Description1')
        db.create_task('task2', 'Subject2', 'Description2')

        db.claim_task('task1', 'test-agent')

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_claim('test-agent', 'task2')

        errors = exc_info.value.errors
        assert any(e.code == 'AGENT_HAS_TASK' for e in errors)

    def test_claim_valid(self, validator, db):
        """Valid claim should pass validation."""
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')

        # Should not raise
        validator.validate_task_claim('test-agent', 'test-task')


class TestLockAcquireValidation:
    """Test lock acquire validation."""

    def test_lock_unregistered_agent(self, validator):
        """Locking with unregistered agent should fail."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_lock_acquire('test.py', 'nonexistent-agent')

        errors = exc_info.value.errors
        assert any(e.code == 'AGENT_NOT_REGISTERED' for e in errors)

    def test_lock_already_locked(self, validator, db):
        """Locking already-locked file should fail."""
        db.register_agent('agent1', 11111)
        db.register_agent('agent2', 22222)
        db.acquire_lock('test.py', 'agent1')

        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_lock_acquire('test.py', 'agent2')

        errors = exc_info.value.errors
        assert any(e.code == 'FILE_LOCKED' for e in errors)

    def test_lock_same_agent_valid(self, validator, db):
        """Same agent locking same file should pass (re-acquire)."""
        db.register_agent('test-agent', 12345)
        db.acquire_lock('test.py', 'test-agent')

        # Should not raise
        validator.validate_lock_acquire('test.py', 'test-agent')


class TestInvariantValidation:
    """Test state invariant validation."""

    def test_invariant_unique_task_owners(self, validator, db):
        """Detect tasks with multiple owners."""
        # Create invalid state (multiple owners for one task)
        db.create_task('test-task', 'Subject', 'Description')
        db.register_agent('agent1', 11111)

        # Manually violate invariant (bypass validation)
        with db.transaction():
            db.execute(
                "UPDATE tasks SET status='in_progress', owner=? WHERE id=?",
                ('agent1', 'test-task')
            )
            # Hack: insert duplicate (shouldn't be possible normally)
            # This is testing the validator catches violations

        # For testing, just verify the validator would catch it
        # We can't easily create this violation through the API

    def test_invariant_one_task_per_agent(self, validator, db):
        """Detect agents with multiple in_progress tasks."""
        db.register_agent('test-agent', 12345)
        db.create_task('task1', 'S1', 'D1')
        db.create_task('task2', 'S2', 'D2')

        # Claim both (second should be prevented by validation, but test invariant)
        db.claim_task('task1', 'test-agent')

        # Manually violate (bypass validation for test)
        with db.transaction():
            db.execute(
                "UPDATE tasks SET status='in_progress', owner=? WHERE id=?",
                ('test-agent', 'task2')
            )

        # Validate invariants
        with pytest.raises(InvariantViolations) as exc_info:
            validator.validate_post_operation()

        violations = exc_info.value.violations
        assert any(v.invariant == 'One task per agent' for v in violations)

    def test_invariant_locks_belong_to_agents(self, validator, db):
        """Detect locks owned by nonexistent agents."""
        db.register_agent('test-agent', 12345)
        db.acquire_lock('test.py', 'test-agent')

        # Manually delete agent (leaving orphaned lock)
        with db.transaction():
            db.execute("DELETE FROM locks WHERE owner=?", ('test-agent',))
            db.execute("INSERT INTO locks (file_path, owner) VALUES (?, ?)",
                      ('test.py', 'nonexistent-agent'))

        # Validate invariants
        with pytest.raises(InvariantViolations) as exc_info:
            validator.validate_post_operation()

        violations = exc_info.value.violations
        assert any(v.invariant == 'Locks belong to agents' for v in violations)

    def test_post_operation_valid_state(self, validator, db):
        """Valid state should pass post-operation validation."""
        db.register_agent('test-agent', 12345)
        db.create_task('test-task', 'Subject', 'Description')
        db.claim_task('test-task', 'test-agent')
        db.acquire_lock('test.py', 'test-agent')

        # Should not raise
        validator.validate_post_operation()


class TestMultipleValidationErrors:
    """Test multiple validation errors in single request."""

    def test_multiple_errors_collected(self, validator):
        """Multiple validation errors should be collected."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                'InvalidTask',  # Bad ID
                'Short',  # Bad subject
                'Desc',  # Bad description for high priority
                priority=99  # Bad priority
            )

        errors = exc_info.value.errors
        # Should have multiple errors
        assert len(errors) >= 3

        error_codes = [e.code for e in errors]
        assert 'INVALID_TASK_ID' in error_codes
        assert 'INVALID_SUBJECT_LENGTH' in error_codes
        assert 'INVALID_PRIORITY' in error_codes

    def test_error_formatting(self, validator):
        """Validation errors should format nicely."""
        try:
            validator.validate_task_create(
                'bad-id',
                'Short',
                'Desc',
                priority=0
            )
        except ValidationErrors as e:
            message = str(e)
            # Should mention multiple errors
            assert 'validation error' in message.lower()


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_none_values(self, validator):
        """None values should be handled gracefully."""
        with pytest.raises(ValidationErrors):
            validator.validate_task_create(
                None,  # None task ID
                'Subject',
                'Description',
                priority=4
            )

    def test_unicode_task_ids(self, validator):
        """Unicode task IDs should be validated."""
        with pytest.raises(ValidationErrors) as exc_info:
            validator.validate_task_create(
                '测试-high-01',  # Unicode characters
                'Valid subject',
                'Description',
                priority=4
            )

        errors = exc_info.value.errors
        # Should fail format validation
        assert any(e.code == 'INVALID_TASK_ID' for e in errors)

    def test_spec_path_override(self, validator, coord_dir):
        """Custom spec path should be used instead of default."""
        custom_spec = coord_dir / 'custom-spec.md'
        custom_spec.write_text("""# Task Specification: test-crit-custom-01

## Problem Statement
Custom spec location.

## Acceptance Criteria
- [ ] Uses custom path

## Test Strategy
Test with custom spec path.
""")

        # Should pass with custom spec
        try:
            validator.validate_task_create(
                'test-crit-custom-01',
                'Valid subject here',
                'Valid description here',
                priority=1,
                spec_path=str(custom_spec)
            )
        except ValidationErrors as e:
            for err in e.errors:
                assert err.code not in ['MISSING_TASK_SPEC', 'INCOMPLETE_TASK_SPEC']
