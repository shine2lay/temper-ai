"""Tests for BlastRadiusPolicy.

Tests cover:
- Configuration and initialization
- File count limits (boundary and edge cases)
- Lines per file limits (single and multiple violations)
- Total lines limits (boundary conditions)
- Entity limits (CRITICAL violations)
- Forbidden pattern detection (case sensitivity, multiple patterns)
- Combined violations (multiple limit breaches in one action)
- Performance validation (<1ms per check)
- Edge cases (empty actions, missing fields, type mismatches)
- Violation metadata and remediation hints

Target Coverage: 95%+ for blast_radius.py
"""
import time

from src.safety.blast_radius import BlastRadiusPolicy
from src.safety.interfaces import ViolationSeverity


class TestBlastRadiusPolicyBasics:
    """Basic tests for BlastRadiusPolicy initialization and properties."""

    def test_default_initialization(self):
        """Test policy with default configuration."""
        policy = BlastRadiusPolicy()

        assert policy.name == "blast_radius"
        assert policy.version == "1.0.0"
        assert policy.priority == 90
        assert policy.max_files == 10
        assert policy.max_lines_per_file == 500
        assert policy.max_total_lines == 2000
        assert policy.max_entities == 100
        assert policy.max_ops_per_minute == 20
        assert policy.forbidden_patterns == []

    def test_custom_configuration(self):
        """Test policy with custom configuration."""
        config = {
            "max_files_per_operation": 5,
            "max_lines_per_file": 200,
            "max_total_lines": 1000,
            "max_entities_affected": 50,
            "max_operations_per_minute": 10,
            "forbidden_patterns": ["DELETE FROM", "DROP TABLE"]
        }
        policy = BlastRadiusPolicy(config)

        assert policy.max_files == 5
        assert policy.max_lines_per_file == 200
        assert policy.max_total_lines == 1000
        assert policy.max_entities == 50
        assert policy.max_ops_per_minute == 10
        assert len(policy.forbidden_patterns) == 2
        assert any(p.pattern == "DELETE FROM" for p in policy.forbidden_patterns)

    def test_partial_configuration(self):
        """Test that unspecified config values use defaults."""
        config = {
            "max_files_per_operation": 15
        }
        policy = BlastRadiusPolicy(config)

        # Custom value
        assert policy.max_files == 15
        # Defaults
        assert policy.max_lines_per_file == 500
        assert policy.max_total_lines == 2000
        assert policy.max_entities == 100

    def test_empty_config_uses_defaults(self):
        """Test that empty config dict uses all defaults."""
        policy = BlastRadiusPolicy({})

        assert policy.max_files == BlastRadiusPolicy.DEFAULT_MAX_FILES
        assert policy.max_lines_per_file == BlastRadiusPolicy.DEFAULT_MAX_LINES_PER_FILE
        assert policy.max_total_lines == BlastRadiusPolicy.DEFAULT_MAX_TOTAL_LINES
        assert policy.max_entities == BlastRadiusPolicy.DEFAULT_MAX_ENTITIES

    def test_none_config_uses_defaults(self):
        """Test that None config uses all defaults."""
        policy = BlastRadiusPolicy(None)

        assert policy.max_files == BlastRadiusPolicy.DEFAULT_MAX_FILES
        assert policy.max_lines_per_file == BlastRadiusPolicy.DEFAULT_MAX_LINES_PER_FILE


class TestFileCountLimits:
    """Tests for max_files_per_operation limit."""

    def test_within_file_limit(self):
        """Test action with files under the limit."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 5})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "files": ["a.py", "b.py", "c.py"]
            },
            context={}
        )

        assert result.valid
        assert len(result.violations) == 0

    def test_exactly_at_file_limit(self):
        """Test action with exactly max files (boundary condition)."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 3})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "files": ["a.py", "b.py", "c.py"]
            },
            context={}
        )

        assert result.valid
        assert len(result.violations) == 0

    def test_one_over_file_limit(self):
        """Test action with one file over the limit (boundary condition)."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 3})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "files": ["a.py", "b.py", "c.py", "d.py"]
            },
            context={}
        )

        assert not result.valid
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.HIGH
        assert "4 > 3" in result.violations[0].message
        assert result.violations[0].policy_name == "blast_radius"

    def test_far_over_file_limit(self):
        """Test action with many files over the limit."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 5})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "files": [f"file_{i}.py" for i in range(20)]
            },
            context={}
        )

        assert not result.valid
        assert "20 > 5" in result.violations[0].message

    def test_empty_files_list(self):
        """Test action with empty files list."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 5})

        result = policy.validate(
            action={"operation": "modify_files", "files": []},
            context={}
        )

        assert result.valid

    def test_files_not_a_list(self):
        """Test graceful handling when files is not a list."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 5})

        # String instead of list
        result = policy.validate(
            action={"operation": "modify_files", "files": "not_a_list"},
            context={}
        )

        # Should not crash, should be valid (type check fails gracefully)
        assert result.valid

    def test_files_field_missing(self):
        """Test action without files field."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 5})

        result = policy.validate(
            action={"operation": "other_operation"},
            context={}
        )

        assert result.valid

    def test_remediation_hint_for_file_limit(self):
        """Test that file limit violation includes remediation hint."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 5})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "files": [f"file_{i}.py" for i in range(10)]
            },
            context={}
        )

        assert result.violations[0].remediation_hint is not None
        assert "5 or less" in result.violations[0].remediation_hint


class TestLinesPerFileLimits:
    """Tests for max_lines_per_file limit."""

    def test_within_lines_per_file_limit(self):
        """Test files with line changes under the limit."""
        policy = BlastRadiusPolicy({"max_lines_per_file": 100})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "lines_changed": {
                    "file1.py": 50,
                    "file2.py": 80
                }
            },
            context={}
        )

        assert result.valid

    def test_exactly_at_lines_per_file_limit(self):
        """Test file with exactly max lines (boundary condition)."""
        policy = BlastRadiusPolicy({"max_lines_per_file": 100})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "lines_changed": {"file1.py": 100}
            },
            context={}
        )

        assert result.valid

    def test_one_over_lines_per_file_limit(self):
        """Test file with one line over the limit (boundary condition)."""
        policy = BlastRadiusPolicy({"max_lines_per_file": 100})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "lines_changed": {"file1.py": 101}
            },
            context={}
        )

        assert not result.valid
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.HIGH
        assert "101 > 100" in result.violations[0].message
        assert "file1.py" in result.violations[0].message

    def test_multiple_files_one_violation(self):
        """Test multiple files where only one exceeds limit."""
        policy = BlastRadiusPolicy({"max_lines_per_file": 100})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "lines_changed": {
                    "file1.py": 50,
                    "file2.py": 150,  # Violates
                    "file3.py": 80
                }
            },
            context={}
        )

        assert not result.valid
        assert len(result.violations) == 1
        assert "file2.py" in result.violations[0].message

    def test_multiple_files_multiple_violations(self):
        """Test multiple files exceeding the limit."""
        policy = BlastRadiusPolicy({"max_lines_per_file": 100})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "lines_changed": {
                    "file1.py": 150,  # Violates
                    "file2.py": 200,  # Violates
                    "file3.py": 50
                }
            },
            context={}
        )

        assert not result.valid
        assert len(result.violations) == 2
        # Check both files mentioned
        messages = [v.message for v in result.violations]
        assert any("file1.py" in m for m in messages)
        assert any("file2.py" in m for m in messages)

    def test_lines_changed_not_a_dict(self):
        """Test graceful handling when lines_changed is not a dict."""
        policy = BlastRadiusPolicy({"max_lines_per_file": 100})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "lines_changed": "not_a_dict"
            },
            context={}
        )

        # Should not crash
        assert result.valid

    def test_lines_changed_missing(self):
        """Test action without lines_changed field."""
        policy = BlastRadiusPolicy({"max_lines_per_file": 100})

        result = policy.validate(
            action={"operation": "modify_files"},
            context={}
        )

        assert result.valid

    def test_empty_lines_changed_dict(self):
        """Test action with empty lines_changed dict."""
        policy = BlastRadiusPolicy({"max_lines_per_file": 100})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "lines_changed": {}
            },
            context={}
        )

        assert result.valid

    def test_remediation_hint_for_lines_per_file(self):
        """Test remediation hint for lines per file violation."""
        policy = BlastRadiusPolicy({"max_lines_per_file": 100})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "lines_changed": {"file1.py": 200}
            },
            context={}
        )

        assert result.violations[0].remediation_hint is not None
        assert "multiple operations" in result.violations[0].remediation_hint.lower()


class TestTotalLinesLimits:
    """Tests for max_total_lines limit."""

    def test_within_total_lines_limit(self):
        """Test action with total lines under the limit."""
        policy = BlastRadiusPolicy({"max_total_lines": 1000})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "total_lines": 500
            },
            context={}
        )

        assert result.valid

    def test_exactly_at_total_lines_limit(self):
        """Test action with exactly max total lines (boundary condition)."""
        policy = BlastRadiusPolicy({"max_total_lines": 1000})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "total_lines": 1000
            },
            context={}
        )

        assert result.valid

    def test_one_over_total_lines_limit(self):
        """Test action with one line over total limit (boundary condition)."""
        policy = BlastRadiusPolicy({"max_total_lines": 1000})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "total_lines": 1001
            },
            context={}
        )

        assert not result.valid
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.HIGH
        assert "1001 > 1000" in result.violations[0].message

    def test_far_over_total_lines_limit(self):
        """Test action far exceeding total lines limit."""
        policy = BlastRadiusPolicy({"max_total_lines": 1000})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "total_lines": 5000
            },
            context={}
        )

        assert not result.valid
        assert "5000 > 1000" in result.violations[0].message

    def test_zero_total_lines(self):
        """Test action with zero total lines."""
        policy = BlastRadiusPolicy({"max_total_lines": 1000})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "total_lines": 0
            },
            context={}
        )

        assert result.valid

    def test_total_lines_missing(self):
        """Test action without total_lines field."""
        policy = BlastRadiusPolicy({"max_total_lines": 1000})

        result = policy.validate(
            action={"operation": "modify_files"},
            context={}
        )

        assert result.valid

    def test_remediation_hint_for_total_lines(self):
        """Test remediation hint for total lines violation."""
        policy = BlastRadiusPolicy({"max_total_lines": 1000})

        result = policy.validate(
            action={
                "operation": "modify_files",
                "total_lines": 2000
            },
            context={}
        )

        assert result.violations[0].remediation_hint is not None
        assert "smaller batches" in result.violations[0].remediation_hint.lower()


class TestEntityLimits:
    """Tests for max_entities_affected limit (CRITICAL violations)."""

    def test_within_entity_limit(self):
        """Test action with entities under the limit."""
        policy = BlastRadiusPolicy({"max_entities_affected": 50})

        result = policy.validate(
            action={
                "operation": "update_users",
                "entities": [f"user_{i}" for i in range(30)]
            },
            context={}
        )

        assert result.valid

    def test_exactly_at_entity_limit(self):
        """Test action with exactly max entities (boundary condition)."""
        policy = BlastRadiusPolicy({"max_entities_affected": 50})

        result = policy.validate(
            action={
                "operation": "update_users",
                "entities": [f"user_{i}" for i in range(50)]
            },
            context={}
        )

        assert result.valid

    def test_one_over_entity_limit(self):
        """Test action with one entity over limit (boundary condition)."""
        policy = BlastRadiusPolicy({"max_entities_affected": 50})

        result = policy.validate(
            action={
                "operation": "update_users",
                "entities": [f"user_{i}" for i in range(51)]
            },
            context={}
        )

        assert not result.valid
        assert len(result.violations) == 1
        # CRITICAL severity for entities
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        assert "51 > 50" in result.violations[0].message

    def test_many_entities_over_limit(self):
        """Test action with many entities over the limit."""
        policy = BlastRadiusPolicy({"max_entities_affected": 50})

        result = policy.validate(
            action={
                "operation": "delete_users",
                "entities": [f"user_{i}" for i in range(500)]
            },
            context={}
        )

        assert not result.valid
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        assert "500 > 50" in result.violations[0].message

    def test_empty_entities_list(self):
        """Test action with empty entities list."""
        policy = BlastRadiusPolicy({"max_entities_affected": 50})

        result = policy.validate(
            action={"operation": "update_users", "entities": []},
            context={}
        )

        assert result.valid

    def test_entities_not_a_list(self):
        """Test graceful handling when entities is not a list."""
        policy = BlastRadiusPolicy({"max_entities_affected": 50})

        result = policy.validate(
            action={"operation": "update_users", "entities": "not_a_list"},
            context={}
        )

        # Should not crash
        assert result.valid

    def test_entities_field_missing(self):
        """Test action without entities field."""
        policy = BlastRadiusPolicy({"max_entities_affected": 50})

        result = policy.validate(
            action={"operation": "update_users"},
            context={}
        )

        assert result.valid

    def test_remediation_hint_for_entities(self):
        """Test remediation hint for entity limit violation."""
        policy = BlastRadiusPolicy({"max_entities_affected": 50})

        result = policy.validate(
            action={
                "operation": "update_users",
                "entities": [f"user_{i}" for i in range(100)]
            },
            context={}
        )

        assert result.violations[0].remediation_hint is not None
        assert "50 entities" in result.violations[0].remediation_hint.lower()


class TestForbiddenPatterns:
    """Tests for forbidden pattern detection (CRITICAL violations)."""

    def test_no_forbidden_patterns_configured(self):
        """Test that validation passes when no patterns configured."""
        policy = BlastRadiusPolicy({"forbidden_patterns": []})

        result = policy.validate(
            action={
                "operation": "execute",
                "content": "DELETE FROM users WHERE id = 1"
            },
            context={}
        )

        assert result.valid

    def test_forbidden_pattern_detected(self):
        """Test detection of forbidden pattern."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DELETE FROM", "DROP TABLE"]
        })

        result = policy.validate(
            action={
                "operation": "execute",
                "content": "DELETE FROM users WHERE id = 1"
            },
            context={}
        )

        assert not result.valid
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        assert "DELETE FROM" in result.violations[0].message

    def test_case_insensitive_pattern_matching(self):
        """Test that pattern matching is case-insensitive."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DELETE FROM"]
        })

        # Lowercase pattern, uppercase content
        result = policy.validate(
            action={
                "operation": "execute",
                "content": "delete from users"
            },
            context={}
        )

        assert not result.valid
        assert "DELETE FROM" in result.violations[0].message

        # Uppercase pattern, mixed case content
        result = policy.validate(
            action={
                "operation": "execute",
                "content": "DeLeTe FrOm users"
            },
            context={}
        )

        assert not result.valid

    def test_multiple_forbidden_patterns_detected(self):
        """Test detection of multiple forbidden patterns."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DELETE FROM", "DROP TABLE", "rm -rf"]
        })

        result = policy.validate(
            action={
                "operation": "execute",
                "content": "DELETE FROM users; DROP TABLE sessions; rm -rf /data"
            },
            context={}
        )

        assert not result.valid
        # Should have 3 violations (one per pattern)
        assert len(result.violations) == 3
        patterns_found = [v.message for v in result.violations]
        assert any("DELETE FROM" in m for m in patterns_found)
        assert any("DROP TABLE" in m for m in patterns_found)
        assert any("rm -rf" in m for m in patterns_found)

    def test_pattern_at_start_of_content(self):
        """Test pattern detection at start of content."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DROP TABLE"]
        })

        result = policy.validate(
            action={
                "operation": "execute",
                "content": "DROP TABLE users"
            },
            context={}
        )

        assert not result.valid

    def test_pattern_at_end_of_content(self):
        """Test pattern detection at end of content."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["rm -rf"]
        })

        result = policy.validate(
            action={
                "operation": "execute",
                "content": "cleanup with rm -rf"
            },
            context={}
        )

        assert not result.valid

    def test_pattern_in_middle_of_content(self):
        """Test pattern detection in middle of content."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DROP TABLE"]
        })

        result = policy.validate(
            action={
                "operation": "execute",
                "content": "First we DROP TABLE users then we proceed"
            },
            context={}
        )

        assert not result.valid

    def test_content_not_a_string(self):
        """Test graceful handling when content is not a string."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DELETE FROM"]
        })

        result = policy.validate(
            action={
                "operation": "execute",
                "content": 123  # Not a string
            },
            context={}
        )

        # Should not crash
        assert result.valid

    def test_content_field_missing(self):
        """Test action without content field."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DELETE FROM"]
        })

        result = policy.validate(
            action={"operation": "execute"},
            context={}
        )

        assert result.valid

    def test_empty_content_string(self):
        """Test action with empty content string."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DELETE FROM"]
        })

        result = policy.validate(
            action={
                "operation": "execute",
                "content": ""
            },
            context={}
        )

        assert result.valid

    def test_remediation_hint_for_forbidden_pattern(self):
        """Test remediation hint for forbidden pattern."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DROP TABLE"]
        })

        result = policy.validate(
            action={
                "operation": "execute",
                "content": "DROP TABLE users"
            },
            context={}
        )

        assert result.violations[0].remediation_hint is not None
        assert "DROP TABLE" in result.violations[0].remediation_hint


class TestCombinedViolations:
    """Tests for multiple violations in a single action."""

    def test_files_and_total_lines_violations(self):
        """Test violation of both file count and total lines."""
        policy = BlastRadiusPolicy({
            "max_files_per_operation": 3,
            "max_total_lines": 500
        })

        result = policy.validate(
            action={
                "operation": "modify_files",
                "files": ["a.py", "b.py", "c.py", "d.py", "e.py"],  # 5 > 3
                "total_lines": 1000  # 1000 > 500
            },
            context={}
        )

        assert not result.valid
        assert len(result.violations) == 2
        # Check both violation types present
        messages = [v.message for v in result.violations]
        assert any("files" in m.lower() for m in messages)
        assert any("total lines" in m.lower() for m in messages)

    def test_all_limits_violated(self):
        """Test violation of all limits simultaneously."""
        policy = BlastRadiusPolicy({
            "max_files_per_operation": 2,
            "max_lines_per_file": 100,
            "max_total_lines": 200,
            "max_entities_affected": 10,
            "forbidden_patterns": ["DROP TABLE"]
        })

        result = policy.validate(
            action={
                "operation": "dangerous_operation",
                "files": ["a.py", "b.py", "c.py"],  # 3 > 2
                "lines_changed": {
                    "a.py": 150,  # 150 > 100
                    "b.py": 120   # 120 > 100
                },
                "total_lines": 500,  # 500 > 200
                "entities": [f"user_{i}" for i in range(20)],  # 20 > 10
                "content": "DROP TABLE users"  # Forbidden pattern
            },
            context={}
        )

        assert not result.valid
        # Should have 6 violations: files, 2x lines_per_file, total_lines, entities, pattern
        assert len(result.violations) == 6

        # Check severity distribution
        critical_violations = [v for v in result.violations if v.severity == ViolationSeverity.CRITICAL]
        high_violations = [v for v in result.violations if v.severity == ViolationSeverity.HIGH]

        # Entities and pattern are CRITICAL
        assert len(critical_violations) == 2
        # Files, lines_per_file (2x), total_lines are HIGH
        assert len(high_violations) == 4

    def test_combined_violations_invalid_overall(self):
        """Test that any HIGH/CRITICAL violation makes result invalid."""
        policy = BlastRadiusPolicy({
            "max_files_per_operation": 3,
            "max_total_lines": 500
        })

        result = policy.validate(
            action={
                "operation": "modify_files",
                "files": ["a.py", "b.py", "c.py", "d.py"]  # 4 > 3
            },
            context={}
        )

        assert not result.valid
        assert result.violations[0].severity >= ViolationSeverity.HIGH


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_action(self):
        """Test validation of empty action dict."""
        policy = BlastRadiusPolicy()

        result = policy.validate(action={}, context={})

        # Should pass (no violations detected)
        assert result.valid

    def test_action_with_only_operation(self):
        """Test action with only operation field."""
        policy = BlastRadiusPolicy()

        result = policy.validate(
            action={"operation": "some_operation"},
            context={}
        )

        assert result.valid

    def test_all_limits_at_zero(self):
        """Test policy rejects zero limits via validation."""
        import pytest
        with pytest.raises(ValueError, match="must be >= 1"):
            BlastRadiusPolicy({
                "max_files_per_operation": 0,
                "max_lines_per_file": 0,
                "max_total_lines": 0,
                "max_entities_affected": 0
            })

    def test_very_large_limits(self):
        """Test policy rejects limits above maximum via validation."""
        import pytest
        with pytest.raises(ValueError, match="must be <="):
            BlastRadiusPolicy({
                "max_files_per_operation": 1000000,
                "max_lines_per_file": 1000000,
                "max_total_lines": 10000000,
                "max_entities_affected": 1000000
            })

    def test_max_allowed_limits(self):
        """Test policy with maximum allowed limits."""
        policy = BlastRadiusPolicy({
            "max_files_per_operation": 10000,
            "max_lines_per_file": 10000,
            "max_total_lines": 10000,
            "max_entities_affected": 10000
        })

        # Normal action should pass
        result = policy.validate(
            action={
                "files": ["a.py"],
                "total_lines": 100,
                "entities": ["user1"]
            },
            context={}
        )

        assert result.valid

    def test_context_included_in_violations(self):
        """Test that context is included in violation objects."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 2})

        context = {"agent": "test_agent", "workflow_id": "wf_123"}
        result = policy.validate(
            action={
                "files": ["a.py", "b.py", "c.py"]
            },
            context=context
        )

        assert not result.valid
        assert result.violations[0].context == context

    def test_action_string_representation_in_violation(self):
        """Test that action is serialized to string in violation."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 2})

        action = {"files": ["a.py", "b.py", "c.py"]}
        result = policy.validate(action, context={})

        assert not result.valid
        # Action should be converted to string
        assert isinstance(result.violations[0].action, str)


class TestValidationResultStructure:
    """Tests for ValidationResult structure and metadata."""

    def test_valid_result_structure(self):
        """Test structure of valid result."""
        policy = BlastRadiusPolicy()

        result = policy.validate(
            action={"files": ["a.py"]},
            context={}
        )

        assert result.valid is True
        assert result.violations == []
        assert result.policy_name == "blast_radius"

    def test_invalid_result_structure(self):
        """Test structure of invalid result."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 2})

        result = policy.validate(
            action={"files": ["a.py", "b.py", "c.py"]},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) > 0
        assert result.policy_name == "blast_radius"

    def test_violation_has_timestamp(self):
        """Test that violations include timestamp."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 2})

        result = policy.validate(
            action={"files": ["a.py", "b.py", "c.py"]},
            context={}
        )

        violation = result.violations[0]
        assert violation.timestamp is not None
        assert isinstance(violation.timestamp, str)
        # Should be ISO format with Z
        assert "T" in violation.timestamp
        assert violation.timestamp.endswith("Z")

    def test_violation_to_dict(self):
        """Test violation serialization to dict."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 2})

        result = policy.validate(
            action={"files": ["a.py", "b.py", "c.py"]},
            context={"test": "value"}
        )

        violation_dict = result.violations[0].to_dict()

        assert violation_dict["policy_name"] == "blast_radius"
        assert violation_dict["severity"] == "HIGH"
        assert violation_dict["severity_value"] == 4
        assert "message" in violation_dict
        assert "action" in violation_dict
        assert "context" in violation_dict
        assert "timestamp" in violation_dict
        assert "remediation_hint" in violation_dict


class TestPerformanceRequirements:
    """Tests for performance requirements (<1ms per validation)."""

    def test_validation_performance_simple_action(self):
        """Test validation completes in <1ms for simple action."""
        policy = BlastRadiusPolicy()
        action = {"files": ["a.py", "b.py"]}

        start = time.perf_counter()
        result = policy.validate(action, context={})
        duration = time.perf_counter() - start

        assert result.valid
        # Should complete in less than 1ms (0.001 seconds)
        assert duration < 0.001

    def test_validation_performance_complex_action(self):
        """Test validation completes in <1ms for complex action."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DELETE FROM", "DROP TABLE", "rm -rf"]
        })

        action = {
            "files": [f"file_{i}.py" for i in range(10)],
            "lines_changed": {f"file_{i}.py": 50 for i in range(10)},
            "total_lines": 500,
            "entities": [f"user_{i}" for i in range(50)],
            "content": "SELECT * FROM users"
        }

        start = time.perf_counter()
        result = policy.validate(action, context={})
        duration = time.perf_counter() - start

        assert result.valid
        # Should complete in less than 1ms
        assert duration < 0.001

    def test_validation_performance_with_violations(self):
        """Test validation completes in <1ms even with violations."""
        policy = BlastRadiusPolicy({
            "max_files_per_operation": 5,
            "max_lines_per_file": 100,
            "max_total_lines": 500,
            "max_entities_affected": 20,
            "forbidden_patterns": ["DELETE FROM"]
        })

        # Action that violates all limits
        action = {
            "files": [f"file_{i}.py" for i in range(10)],
            "lines_changed": {f"file_{i}.py": 150 for i in range(5)},
            "total_lines": 1000,
            "entities": [f"user_{i}" for i in range(50)],
            "content": "DELETE FROM users"
        }

        start = time.perf_counter()
        result = policy.validate(action, context={})
        duration = time.perf_counter() - start

        assert not result.valid
        assert len(result.violations) > 0
        # Should still complete in less than 1ms
        assert duration < 0.001

    def test_validation_performance_many_patterns(self):
        """Test validation with many forbidden patterns."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": [
                f"PATTERN_{i}" for i in range(20)
            ]
        })

        action = {
            "content": "Safe content that doesn't match any patterns"
        }

        start = time.perf_counter()
        result = policy.validate(action, context={})
        duration = time.perf_counter() - start

        assert result.valid
        # Should complete in less than 1ms even with 20 patterns
        assert duration < 0.001


class TestDefaultConstants:
    """Tests for default constant values."""

    def test_default_constants_match_docstring(self):
        """Test that default constants match documented values."""
        # From docstring
        assert BlastRadiusPolicy.DEFAULT_MAX_FILES == 10
        assert BlastRadiusPolicy.DEFAULT_MAX_LINES_PER_FILE == 500
        assert BlastRadiusPolicy.DEFAULT_MAX_TOTAL_LINES == 2000
        assert BlastRadiusPolicy.DEFAULT_MAX_ENTITIES == 100
        assert BlastRadiusPolicy.DEFAULT_MAX_OPS_PER_MINUTE == 20

    def test_defaults_used_when_no_config(self):
        """Test that defaults are applied when config is missing."""
        policy = BlastRadiusPolicy()

        assert policy.max_files == BlastRadiusPolicy.DEFAULT_MAX_FILES
        assert policy.max_lines_per_file == BlastRadiusPolicy.DEFAULT_MAX_LINES_PER_FILE
        assert policy.max_total_lines == BlastRadiusPolicy.DEFAULT_MAX_TOTAL_LINES
        assert policy.max_entities == BlastRadiusPolicy.DEFAULT_MAX_ENTITIES
        assert policy.max_ops_per_minute == BlastRadiusPolicy.DEFAULT_MAX_OPS_PER_MINUTE
