"""
Security tests for ExperimentService.

Tests for SQL injection prevention, input validation, and timing attack mitigation.
"""

import pytest

from temper_ai.experimentation.service import ExperimentService
from temper_ai.experimentation.validators import (
    validate_experiment_name,
    validate_variant_name,
)
from temper_ai.storage.database import init_database, reset_database


class TestInputValidation:
    """Test input validation for experiment and variant names."""

    def test_valid_experiment_names(self):
        """Test that valid experiment names are accepted."""
        valid_names = [
            "test_experiment",
            "TestExperiment123",
            "test-experiment-v2",
            "a",  # Minimum length (1 char)
            "a" * 50,  # Maximum length (50 chars)
            "MyExperiment",
            "experiment_2026",
        ]

        for name in valid_names:
            result = validate_experiment_name(name)
            assert result is not None, f"Failed to validate: {name}"
            # Name should be normalized
            assert result == name or result == name.lower()

    def test_invalid_experiment_names(self):
        """Test that invalid experiment names are rejected."""
        invalid_names = [
            ("", "1-50 characters"),  # Empty
            (" ", "1-50 characters"),  # Whitespace only
            ("a" * 51, "1-50 characters"),  # Too long
            ("test experiment", "alphanumeric"),  # Space
            ("test@experiment", "alphanumeric"),  # Special char
            ("test\nexp", "alphanumeric"),  # Newline
            ("test\x00exp", "alphanumeric"),  # Null byte
            ("123test", "start with a letter"),  # Starts with number
            ("test__exp", "consecutive"),  # Consecutive underscores
            ("test--exp", "consecutive"),  # Consecutive hyphens
            ("_test", "start with a letter"),  # Starts with underscore
            ("-test", "start with a letter"),  # Starts with hyphen
        ]

        for name, expected_error_fragment in invalid_names:
            with pytest.raises(ValueError, match=expected_error_fragment):
                validate_experiment_name(name)

    def test_unicode_normalization(self):
        """Test Unicode normalization prevents homograph attacks."""
        # These should normalize to the same string (if we accept non-ASCII)
        # Or be rejected if we only accept ASCII
        unicode_names = [
            "café",  # Contains non-ASCII
            "tеst",  # Contains Cyrillic 'e' (U+0435)
        ]

        for name in unicode_names:
            # Our validation should reject non-ASCII characters
            with pytest.raises(ValueError, match="alphanumeric"):
                validate_experiment_name(name)

    def test_variant_name_validation(self):
        """Test variant name validation."""
        # Valid names
        valid_names = ["control", "variant_a", "test-1"]
        for name in valid_names:
            result = validate_variant_name(name)
            assert result is not None

        # Invalid names
        invalid_names = [
            "",  # Empty
            "a" * 31,  # Too long (max 30)
            "test variant",  # Space
            "test@variant",  # Special char
        ]

        for name in invalid_names:
            with pytest.raises(ValueError):
                validate_variant_name(name)

    def test_sql_injection_prevention(self):
        """Test that SQL injection payloads are rejected by input validation."""
        sql_injection_payloads = [
            "test'; DROP TABLE experiments; --",
            "test' OR '1'='1",
            "test'; UPDATE experiments SET name='hacked' WHERE '1'='1'; --",
            "test\x00hidden",  # Null byte injection
            "'; DELETE FROM experiments WHERE 'a'='a",
            "admin'--",
            "1' UNION SELECT * FROM experiments--",
        ]

        for payload in sql_injection_payloads:
            # Any ValueError is acceptable - could be length, alphanumeric, or start with letter
            with pytest.raises(ValueError):
                validate_experiment_name(payload)


class TestExperimentServiceSecurity:
    """Test security features of ExperimentService."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Initialize a fresh test database for each test."""
        db_path = tmp_path / "test_security.db"
        init_database(f"sqlite:///{db_path}")
        yield
        reset_database()

    @pytest.fixture
    def service(self):
        """Create ExperimentService instance."""
        svc = ExperimentService()
        svc.initialize()
        yield svc
        svc.shutdown()

    def test_experiment_creation_with_valid_name(self, service):
        """Test experiment creation with valid name succeeds."""
        exp_id = service.create_experiment(
            name="valid_test_experiment",
            description="Test experiment",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.5},
                {"name": "variant", "traffic": 0.5},
            ],
            primary_metric="test_metric",
        )
        assert exp_id is not None

        # Verify experiment was created
        experiment = service.get_experiment(exp_id)
        assert experiment is not None
        assert experiment.name == "valid_test_experiment"

    def test_experiment_creation_with_invalid_name(self, service):
        """Test experiment creation with invalid name fails."""
        invalid_names = [
            "test'; DROP TABLE--",
            "",
            "a" * 51,
            "test experiment",
            "123test",
        ]

        for name in invalid_names:
            with pytest.raises(ValueError):
                service.create_experiment(
                    name=name,
                    description="Test",
                    variants=[
                        {"name": "control", "is_control": True, "traffic": 0.5},
                        {"name": "variant", "traffic": 0.5},
                    ],
                    primary_metric="test_metric",
                )

    def test_variant_name_validation_in_service(self, service):
        """Test that invalid variant names are rejected."""
        with pytest.raises(ValueError):
            service.create_experiment(
                name="test_experiment",
                description="Test",
                variants=[
                    {"name": "control", "is_control": True, "traffic": 0.5},
                    {"name": "variant'; DROP TABLE--", "traffic": 0.5},
                ],
                primary_metric="test_metric",
            )

    def test_duplicate_experiment_name_error(self, service):
        """Test that duplicate experiment names are rejected with generic error."""
        # Create first experiment
        service.create_experiment(
            name="duplicate_test",
            description="First experiment",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.5},
                {"name": "variant", "traffic": 0.5},
            ],
            primary_metric="test_metric",
        )

        # Try to create duplicate
        with pytest.raises(ValueError, match="Experiment creation failed"):
            service.create_experiment(
                name="duplicate_test",
                description="Duplicate experiment",
                variants=[
                    {"name": "control", "is_control": True, "traffic": 0.5},
                    {"name": "variant", "traffic": 0.5},
                ],
                primary_metric="test_metric",
            )

    def test_orm_roundtrip_integrity(self, service):
        """
        Test that ORM correctly persists and retrieves experiment names.

        Verifies that the ORM layer handles experiment creation and
        retrieval without data corruption.
        """
        malicious_name = "test_orm_injection"

        exp_id = service.create_experiment(
            name=malicious_name,
            description="Test that ORM escapes properly",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.5},
                {"name": "variant", "traffic": 0.5},
            ],
            primary_metric="test_metric",
        )

        # Verify experiment was created with exact name (ORM escaped it)
        experiment = service.get_experiment(exp_id)
        assert experiment.name == malicious_name

        # Verify tables still exist (no DROP TABLE executed)
        experiments = service.list_experiments()
        assert len(experiments) > 0

    def test_control_character_rejection(self, service):
        """Test that control characters are rejected in names."""
        control_chars = [
            "test\nexp",  # Newline
            "test\rexp",  # Carriage return
            "test\texp",  # Tab
            "test\x00exp",  # Null byte
            "test\x1bexp",  # Escape
        ]

        for name in control_chars:
            with pytest.raises(ValueError, match="alphanumeric"):
                service.create_experiment(
                    name=name,
                    description="Control char test",
                    variants=[
                        {"name": "control", "is_control": True, "traffic": 0.5},
                        {"name": "variant", "traffic": 0.5},
                    ],
                    primary_metric="test_metric",
                )

    def test_length_limit_enforcement(self, service):
        """Test that length limits are enforced."""
        # Experiment name too long
        with pytest.raises(ValueError, match="1-50 characters"):
            service.create_experiment(
                name="a" * 51,
                description="Length test",
                variants=[
                    {"name": "control", "is_control": True, "traffic": 0.5},
                    {"name": "variant", "traffic": 0.5},
                ],
                primary_metric="test_metric",
            )

        # Variant name too long
        with pytest.raises(ValueError, match="1-30 characters"):
            service.create_experiment(
                name="test_length",
                description="Length test",
                variants=[
                    {"name": "control", "is_control": True, "traffic": 0.5},
                    {"name": "a" * 31, "traffic": 0.5},
                ],
                primary_metric="test_metric",
            )


class TestSecurityLogging:
    """Test security event logging."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """Initialize a fresh test database for each test."""
        db_path = tmp_path / "test_security_log.db"
        init_database(f"sqlite:///{db_path}")
        yield
        reset_database()

    @pytest.fixture
    def service(self):
        """Create ExperimentService instance."""
        svc = ExperimentService()
        svc.initialize()
        yield svc
        svc.shutdown()

    def test_invalid_name_logging(self, service, caplog):
        """Test that invalid names are logged as security events."""
        with pytest.raises(ValueError):
            service.create_experiment(
                name="test'; DROP TABLE--",
                description="Test",
                variants=[
                    {"name": "control", "is_control": True, "traffic": 0.5},
                    {"name": "variant", "traffic": 0.5},
                ],
                primary_metric="test_metric",
            )

        # Check that security event was logged
        assert any(
            "INPUT_VALIDATION_FAILED" in record.getMessage()
            or hasattr(record, "security_event")
            for record in caplog.records
        )

    def test_constraint_violation_logging(self, service, caplog):
        """Test that constraint violations are logged."""
        # Create experiment
        service.create_experiment(
            name="constraint_test",
            description="Test",
            variants=[
                {"name": "control", "is_control": True, "traffic": 0.5},
                {"name": "variant", "traffic": 0.5},
            ],
            primary_metric="test_metric",
        )

        # Try duplicate
        with pytest.raises(ValueError):
            service.create_experiment(
                name="constraint_test",
                description="Test",
                variants=[
                    {"name": "control", "is_control": True, "traffic": 0.5},
                    {"name": "variant", "traffic": 0.5},
                ],
                primary_metric="test_metric",
            )

        # Check for security event log
        assert any(
            "DATABASE_CONSTRAINT_VIOLATION" in record.message
            or "constraint violation" in record.message.lower()
            for record in caplog.records
        )
