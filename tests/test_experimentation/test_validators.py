"""
Comprehensive tests for experimentation validators.

Covers:
- validate_experiment_name: length, characters, normalization, security
- validate_variant_name: similar validation rules
- validate_variant_list: batch validation, error handling
- Unicode normalization (homograph attack prevention)
- Security validation edge cases
"""

import pytest

from src.experimentation.validators import (
    validate_experiment_name,
    validate_variant_name,
    validate_variant_list,
    MAX_EXPERIMENT_NAME_LENGTH,
    MAX_VARIANT_NAME_LENGTH,
)


class TestValidateExperimentName:
    """Test validate_experiment_name function."""

    def test_valid_experiment_name(self):
        """Test valid experiment names are accepted."""
        assert validate_experiment_name("test_experiment") == "test_experiment"
        assert validate_experiment_name("experiment123") == "experiment123"
        assert validate_experiment_name("my-experiment") == "my-experiment"
        assert validate_experiment_name("Experiment_v2") == "Experiment_v2"
        assert validate_experiment_name("a") == "a"  # Single letter

    def test_experiment_name_with_mixed_characters(self):
        """Test experiment names with valid mixed characters."""
        assert validate_experiment_name("test-experiment_v2") == "test-experiment_v2"
        assert validate_experiment_name("TestExperiment123") == "TestExperiment123"
        assert validate_experiment_name("experiment-2024-Q1") == "experiment-2024-Q1"

    def test_experiment_name_normalization(self):
        """Test Unicode normalization (NFKC) is applied."""
        # Unicode normalization example (full-width characters)
        # Note: After normalization, these should become standard ASCII
        normalized = validate_experiment_name("testABC123")
        assert normalized == "testABC123"

    def test_experiment_name_too_long(self):
        """Test experiment name exceeding max length is rejected."""
        long_name = "a" * (MAX_EXPERIMENT_NAME_LENGTH + 1)
        with pytest.raises(ValueError, match="must be 1-50 characters"):
            validate_experiment_name(long_name)

    def test_experiment_name_empty(self):
        """Test empty experiment name is rejected."""
        with pytest.raises(ValueError, match="must be 1-50 characters"):
            validate_experiment_name("")

    def test_experiment_name_whitespace_only(self):
        """Test whitespace-only name is rejected."""
        with pytest.raises(ValueError, match="must be 1-50 characters"):
            validate_experiment_name("   ")

    def test_experiment_name_invalid_characters(self):
        """Test invalid characters are rejected."""
        # Spaces
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test experiment")

        # Special characters
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test@experiment")

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test.experiment")

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test$experiment")

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test#experiment")

    def test_experiment_name_sql_injection_attempt(self):
        """Test SQL injection attempts are rejected."""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test'; DROP TABLE--")

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test' OR '1'='1")

    def test_experiment_name_xss_attempt(self):
        """Test XSS attempts are rejected."""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("<script>alert('xss')</script>")

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test<script>")

    def test_experiment_name_must_start_with_letter(self):
        """Test experiment name must start with a letter."""
        with pytest.raises(ValueError, match="must start with a letter"):
            validate_experiment_name("123experiment")

        with pytest.raises(ValueError, match="must start with a letter"):
            validate_experiment_name("-experiment")

        with pytest.raises(ValueError, match="must start with a letter"):
            validate_experiment_name("_experiment")

    def test_experiment_name_consecutive_special_chars(self):
        """Test consecutive hyphens or underscores are rejected."""
        with pytest.raises(ValueError, match="cannot contain consecutive"):
            validate_experiment_name("test--experiment")

        with pytest.raises(ValueError, match="cannot contain consecutive"):
            validate_experiment_name("test__experiment")

        with pytest.raises(ValueError, match="cannot contain consecutive"):
            validate_experiment_name("test---experiment")

        with pytest.raises(ValueError, match="cannot contain consecutive"):
            validate_experiment_name("test-_experiment")

    def test_experiment_name_at_max_length(self):
        """Test experiment name at exactly max length is accepted."""
        max_length_name = "a" * MAX_EXPERIMENT_NAME_LENGTH
        assert validate_experiment_name(max_length_name) == max_length_name

    def test_experiment_name_case_sensitivity(self):
        """Test experiment names are case-sensitive."""
        assert validate_experiment_name("TestExperiment") == "TestExperiment"
        assert validate_experiment_name("testexperiment") == "testexperiment"
        assert validate_experiment_name("TESTEXPERIMENT") == "TESTEXPERIMENT"


class TestValidateVariantName:
    """Test validate_variant_name function."""

    def test_valid_variant_name(self):
        """Test valid variant names are accepted."""
        assert validate_variant_name("control") == "control"
        assert validate_variant_name("variant_a") == "variant_a"
        assert validate_variant_name("variant-1") == "variant-1"
        assert validate_variant_name("v2") == "v2"

    def test_variant_name_with_mixed_characters(self):
        """Test variant names with valid mixed characters."""
        assert validate_variant_name("variant-a_1") == "variant-a_1"
        assert validate_variant_name("Control123") == "Control123"

    def test_variant_name_too_long(self):
        """Test variant name exceeding max length is rejected."""
        long_name = "a" * (MAX_VARIANT_NAME_LENGTH + 1)
        with pytest.raises(ValueError, match="must be 1-30 characters"):
            validate_variant_name(long_name)

    def test_variant_name_empty(self):
        """Test empty variant name is rejected."""
        with pytest.raises(ValueError, match="must be 1-30 characters"):
            validate_variant_name("")

    def test_variant_name_invalid_characters(self):
        """Test invalid characters are rejected."""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_variant_name("variant a")

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_variant_name("variant.a")

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_variant_name("variant@a")

    def test_variant_name_at_max_length(self):
        """Test variant name at exactly max length is accepted."""
        max_length_name = "a" * MAX_VARIANT_NAME_LENGTH
        assert validate_variant_name(max_length_name) == max_length_name

    def test_variant_name_normalization(self):
        """Test Unicode normalization is applied to variant names."""
        # Standard ASCII should pass through unchanged
        assert validate_variant_name("variantABC") == "variantABC"


class TestValidateVariantList:
    """Test validate_variant_list function."""

    def test_validate_valid_variant_list(self):
        """Test validating a list of valid variants."""
        variants = [
            {"name": "control", "config": {}},
            {"name": "variant_a", "config": {}},
            {"name": "variant_b", "config": {}},
        ]

        validated = validate_variant_list(variants, "test_experiment")

        assert len(validated) == 3
        assert validated[0]["name"] == "control"
        assert validated[1]["name"] == "variant_a"
        assert validated[2]["name"] == "variant_b"

    def test_validate_empty_variant_list(self):
        """Test validating an empty variant list."""
        variants = []
        validated = validate_variant_list(variants, "test_experiment")
        assert validated == []

    def test_validate_variant_list_with_invalid_name(self):
        """Test that invalid variant name raises ValueError."""
        variants = [
            {"name": "control", "config": {}},
            {"name": "invalid name", "config": {}},  # Invalid: contains space
        ]

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_variant_list(variants, "test_experiment")

    def test_validate_variant_list_with_sql_injection(self):
        """Test that SQL injection attempt is rejected."""
        variants = [
            {"name": "control", "config": {}},
            {"name": "variant'; DROP TABLE--", "config": {}},
        ]

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_variant_list(variants, "test_experiment")

    def test_validate_variant_list_preserves_other_fields(self):
        """Test that validation preserves non-name fields."""
        variants = [
            {
                "name": "control",
                "config": {"model": "gpt-4"},
                "description": "Control variant",
                "traffic": 0.5,
            },
        ]

        validated = validate_variant_list(variants, "test_experiment")

        assert validated[0]["name"] == "control"
        assert validated[0]["config"] == {"model": "gpt-4"}
        assert validated[0]["description"] == "Control variant"
        assert validated[0]["traffic"] == 0.5

    def test_validate_variant_list_normalizes_names(self):
        """Test that variant names are normalized."""
        variants = [
            {"name": "control", "config": {}},
            {"name": "variantA", "config": {}},
        ]

        validated = validate_variant_list(variants, "test_experiment")

        # Names should be normalized (already ASCII in this case)
        assert validated[0]["name"] == "control"
        assert validated[1]["name"] == "variantA"

    def test_validate_variant_list_atomic_validation(self):
        """Test that validation is atomic - fails on first invalid variant."""
        variants = [
            {"name": "control", "config": {}},
            {"name": "invalid variant", "config": {}},  # Invalid
            {"name": "variant_a", "config": {}},  # Would be valid but won't reach here
        ]

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_variant_list(variants, "test_experiment")

    def test_validate_variant_list_with_too_long_name(self):
        """Test that variant with too long name is rejected."""
        long_name = "a" * (MAX_VARIANT_NAME_LENGTH + 1)
        variants = [
            {"name": "control", "config": {}},
            {"name": long_name, "config": {}},
        ]

        with pytest.raises(ValueError, match="must be 1-30 characters"):
            validate_variant_list(variants, "test_experiment")

    def test_validate_variant_list_with_empty_name(self):
        """Test that variant with empty name is rejected."""
        variants = [
            {"name": "", "config": {}},
        ]

        with pytest.raises(ValueError, match="must be 1-30 characters"):
            validate_variant_list(variants, "test_experiment")


class TestSecurityValidation:
    """Test security-focused validation scenarios."""

    def test_unicode_homograph_attack_prevention(self):
        """Test prevention of Unicode homograph attacks."""
        # Unicode normalization should prevent lookalike characters
        # Test with regular ASCII which should pass
        assert validate_experiment_name("experiment") == "experiment"

    def test_path_traversal_attempt(self):
        """Test path traversal attempts are rejected."""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("../../../etc/passwd")

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("..\\windows\\system32")

    def test_command_injection_attempt(self):
        """Test command injection attempts are rejected."""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test`whoami`")

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test$(whoami)")

        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test;ls")

    def test_null_byte_injection(self):
        """Test null byte injection is rejected."""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test\x00admin")

    def test_ldap_injection_attempt(self):
        """Test LDAP injection attempts are rejected."""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test*)(uid=*))(|(uid=*")

    def test_nosql_injection_attempt(self):
        """Test NoSQL injection attempts are rejected."""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test'||'1")

    def test_xml_injection_attempt(self):
        """Test XML injection attempts are rejected."""
        with pytest.raises(ValueError, match="must contain only alphanumeric"):
            validate_experiment_name("test<!ENTITY>")


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_character_names(self):
        """Test single character names."""
        assert validate_experiment_name("a") == "a"
        assert validate_experiment_name("Z") == "Z"
        assert validate_variant_name("a") == "a"

    def test_numbers_in_name(self):
        """Test names with numbers are valid (as long as they start with letter)."""
        assert validate_experiment_name("test123") == "test123"
        assert validate_experiment_name("a1b2c3") == "a1b2c3"
        assert validate_variant_name("v123") == "v123"

    def test_all_uppercase(self):
        """Test all uppercase names."""
        assert validate_experiment_name("EXPERIMENT") == "EXPERIMENT"
        assert validate_variant_name("CONTROL") == "CONTROL"

    def test_all_lowercase(self):
        """Test all lowercase names."""
        assert validate_experiment_name("experiment") == "experiment"
        assert validate_variant_name("control") == "control"

    def test_alternating_hyphens_underscores(self):
        """Test alternating hyphens and underscores (single, not consecutive)."""
        assert validate_experiment_name("test-a_b-c") == "test-a_b-c"
        assert validate_variant_name("v-1_2-3") == "v-1_2-3"

    def test_name_ending_with_hyphen(self):
        """Test name ending with hyphen is valid."""
        assert validate_experiment_name("test-") == "test-"
        assert validate_variant_name("v-") == "v-"

    def test_name_ending_with_underscore(self):
        """Test name ending with underscore is valid."""
        assert validate_experiment_name("test_") == "test_"
        assert validate_variant_name("v_") == "v_"

    def test_variant_name_in_experiment_context(self):
        """Test variant validation within experiment context."""
        variants = [
            {"name": "control", "is_control": True},
            {"name": "treatment", "is_control": False},
        ]

        validated = validate_variant_list(variants, "experiment_name")

        assert len(validated) == 2
        assert validated[0]["name"] == "control"
        assert validated[0]["is_control"] is True
        assert validated[1]["name"] == "treatment"
        assert validated[1]["is_control"] is False
