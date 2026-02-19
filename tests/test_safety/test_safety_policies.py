"""Tests for safety policies.

Tests the three main safety policies:
- BlastRadiusPolicy
- SecretDetectionPolicy
- RateLimiterPolicy
"""
from temper_ai.safety import (
    BlastRadiusPolicy,
    RateLimiterPolicy,
    SecretDetectionPolicy,
    ViolationSeverity,
)


class TestBlastRadiusPolicy:
    """Test BlastRadiusPolicy."""

    def test_initialization_with_defaults(self):
        """Test policy initializes with default values."""
        policy = BlastRadiusPolicy()

        assert policy.name == "blast_radius"
        assert policy.version == "1.0.0"
        assert policy.priority == 90
        assert policy.max_files == BlastRadiusPolicy.DEFAULT_MAX_FILES

    def test_initialization_with_custom_config(self):
        """Test policy initializes with custom config."""
        config = {
            "max_files_per_operation": 5,
            "max_lines_per_file": 100
        }
        policy = BlastRadiusPolicy(config)

        assert policy.max_files == 5
        assert policy.max_lines_per_file == 100

    def test_allows_small_file_changes(self):
        """Test policy allows small file changes."""
        policy = BlastRadiusPolicy()

        result = policy.validate(
            action={"files": ["a.py", "b.py"], "total_lines": 50},
            context={}
        )

        assert result.valid is True
        assert len(result.violations) == 0

    def test_blocks_too_many_files(self):
        """Test policy blocks when too many files are modified."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 3})

        result = policy.validate(
            action={"files": ["a.py", "b.py", "c.py", "d.py"]},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.HIGH
        assert "too many files" in result.violations[0].message.lower()

    def test_blocks_too_many_lines_per_file(self):
        """Test policy blocks when too many lines changed in one file."""
        policy = BlastRadiusPolicy({"max_lines_per_file": 100})

        result = policy.validate(
            action={"lines_changed": {"large.py": 500}},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.HIGH
        assert "too many lines" in result.violations[0].message.lower()

    def test_blocks_too_many_total_lines(self):
        """Test policy blocks when total lines changed is too high."""
        policy = BlastRadiusPolicy({"max_total_lines": 1000})

        result = policy.validate(
            action={"total_lines": 5000},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.HIGH

    def test_blocks_too_many_entities(self):
        """Test policy blocks when too many entities affected."""
        policy = BlastRadiusPolicy({"max_entities_affected": 50})

        result = policy.validate(
            action={"entities": [f"user-{i}" for i in range(100)]},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL

    def test_detects_forbidden_patterns(self):
        """Test policy detects forbidden patterns in content."""
        policy = BlastRadiusPolicy({
            "forbidden_patterns": ["DELETE FROM", "DROP TABLE"]
        })

        result = policy.validate(
            action={"content": "DELETE FROM users WHERE 1=1"},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        assert "forbidden pattern" in result.violations[0].message.lower()


class TestSecretDetectionPolicy:
    """Test SecretDetectionPolicy."""

    def test_initialization_with_defaults(self):
        """Test policy initializes with default values."""
        policy = SecretDetectionPolicy()

        assert policy.name == "secret_detection"
        assert policy.version == "1.0.0"
        assert policy.priority == 95
        assert len(policy.compiled_patterns) > 0

    def test_initialization_with_custom_patterns(self):
        """Test policy initializes with custom pattern selection."""
        config = {"enabled_patterns": ["generic_api_key", "generic_secret"]}
        policy = SecretDetectionPolicy(config)

        assert len(policy.compiled_patterns) == 2
        assert "generic_api_key" in policy.enabled_patterns

    def test_allows_clean_content(self):
        """Test policy allows content without secrets."""
        policy = SecretDetectionPolicy()

        result = policy.validate(
            action={"content": "def hello_world():\n    print('Hello!')"},
            context={}
        )

        assert result.valid is True
        assert len(result.violations) == 0

    def test_detects_api_key(self):
        """Test policy detects API keys."""
        policy = SecretDetectionPolicy()

        result = policy.validate(
            action={"content": "api_key='sk_live_abcdef123456789012345678901234567890'"},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) >= 1
        assert any("api" in v.message.lower() or "secret" in v.message.lower()
                  for v in result.violations)

    def test_detects_aws_access_key(self):
        """Test policy detects AWS access keys."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        result = policy.validate(
            action={"content": "AWS_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE"},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) >= 1

    def test_detects_github_token(self):
        """Test policy detects GitHub tokens."""
        policy = SecretDetectionPolicy()

        result = policy.validate(
            action={"content": "token = 'ghp_1234567890abcdefghijklmnopqrstuvwxyz'"},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) >= 1

    def test_detects_private_key(self):
        """Test policy detects private keys."""
        policy = SecretDetectionPolicy()

        result = policy.validate(
            action={"content": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."},
            context={}
        )

        assert result.valid is False
        assert len(result.violations) >= 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL

    def test_allows_test_secrets(self):
        """Test policy allows obvious test secrets."""
        policy = SecretDetectionPolicy({"allow_test_secrets": True})

        result = policy.validate(
            action={"content": "password='test123'"},
            context={}
        )

        # Should allow since it contains 'test'
        assert result.valid is True or all(v.severity < ViolationSeverity.HIGH for v in result.violations)

    def test_respects_excluded_paths(self):
        """Test policy respects excluded file paths."""
        policy = SecretDetectionPolicy({
            "excluded_paths": ["tests/", ".env.example"]
        })

        result = policy.validate(
            action={
                "file_path": "tests/fixtures/secrets.py",
                "content": "api_key='sk_live_very_secret_key_12345678'"
            },
            context={}
        )

        assert result.valid is True
        assert len(result.violations) == 0

    def test_calculates_entropy(self):
        """Test entropy calculation works."""
        policy = SecretDetectionPolicy()

        # High entropy (random string)
        high_entropy = policy._calculate_entropy("xK3mP9qLz2Yw8Rf5")
        # Low entropy (repeated characters)
        low_entropy = policy._calculate_entropy("aaaaaaaaaa")

        assert high_entropy > low_entropy
        assert high_entropy > 3.0
        assert low_entropy < 1.0


class TestRateLimiterPolicy:
    """Test RateLimiterPolicy."""

    def test_initialization_with_defaults(self):
        """Test policy initializes with default values."""
        policy = RateLimiterPolicy()

        assert policy.name == "rate_limiter"
        assert policy.version == "1.0.0"
        assert policy.priority == 85
        assert len(policy.limits) > 0

    def test_initialization_with_custom_limits(self):
        """Test policy initializes with custom limits."""
        config = {
            "limits": {
                "my_operation": {"max_per_minute": 10}
            }
        }
        policy = RateLimiterPolicy(config)

        assert "my_operation" in policy.limits
        assert policy.limits["my_operation"]["max_per_minute"] == 10

    def test_allows_operation_under_limit(self):
        """Test policy allows operations under rate limit."""
        policy = RateLimiterPolicy({
            "limits": {"test_op": {"max_per_minute": 10}}
        })

        # First operation should be allowed
        result = policy.validate(
            action={"operation": "test_op"},
            context={"agent_id": "agent-123"}
        )

        assert result.valid is True
        assert len(result.violations) == 0

    def test_blocks_operation_over_limit(self):
        """Test policy blocks operations over rate limit."""
        policy = RateLimiterPolicy({
            "limits": {"test_op": {"max_per_second": 2}}
        })

        # Make 3 rapid operations (should block 3rd)
        for i in range(3):
            result = policy.validate(
                action={"operation": "test_op"},
                context={"agent_id": "agent-123"}
            )

            if i < 2:
                assert result.valid is True
            else:
                assert result.valid is False
                assert len(result.violations) >= 1
                assert "rate limit" in result.violations[0].message.lower()

    def test_tracks_per_entity(self):
        """Test policy tracks limits per entity."""
        policy = RateLimiterPolicy({
            "limits": {"test_op": {"max_per_second": 2}},
            "per_entity": True
        })

        # Agent 1 makes 2 operations
        for _ in range(2):
            policy.validate(
                action={"operation": "test_op"},
                context={"agent_id": "agent-1"}
            )

        # Agent 2 should still be allowed (separate limit)
        result = policy.validate(
            action={"operation": "test_op"},
            context={"agent_id": "agent-2"}
        )

        assert result.valid is True

    def test_tracks_global_limit(self):
        """Test policy tracks global limits across entities."""
        policy = RateLimiterPolicy({
            "limits": {"test_op": {"max_per_second": 2}},
            "per_entity": False
        })

        # Different agents share same limit
        policy.validate(action={"operation": "test_op"}, context={"agent_id": "agent-1"})
        policy.validate(action={"operation": "test_op"}, context={"agent_id": "agent-2"})

        # Third operation should be blocked (global limit)
        result = policy.validate(
            action={"operation": "test_op"},
            context={"agent_id": "agent-3"}
        )

        assert result.valid is False

    def test_allows_unknown_operation(self):
        """Test policy allows operations with no defined limits."""
        policy = RateLimiterPolicy()

        result = policy.validate(
            action={"operation": "unknown_operation"},
            context={}
        )

        assert result.valid is True
        assert len(result.violations) == 0

    def test_reset_limits(self):
        """Test resetting rate limits."""
        policy = RateLimiterPolicy({
            "limits": {"test_op": {"max_per_second": 1}}
        })

        # Use up limit
        policy.validate(action={"operation": "test_op"}, context={})

        # Reset limits
        policy.reset_limits()

        # Should be allowed again
        result = policy.validate(action={"operation": "test_op"}, context={})
        assert result.valid is True

    def test_reset_specific_operation(self):
        """Test resetting specific operation limits."""
        policy = RateLimiterPolicy({
            "limits": {
                "op1": {"max_per_second": 1},
                "op2": {"max_per_second": 1}
            }
        })

        # Use up both limits
        policy.validate(action={"operation": "op1"}, context={"agent_id": "agent-1"})
        policy.validate(action={"operation": "op2"}, context={"agent_id": "agent-1"})

        # Reset only op1
        policy.reset_limits(operation="op1")

        # op1 should be allowed, op2 still blocked
        result1 = policy.validate(action={"operation": "op1"}, context={"agent_id": "agent-1"})
        result2 = policy.validate(action={"operation": "op2"}, context={"agent_id": "agent-1"})

        assert result1.valid is True
        assert result2.valid is False

    def test_format_window(self):
        """Test time window formatting."""
        policy = RateLimiterPolicy()

        assert "second" in policy._format_window(1)
        assert "minute" in policy._format_window(60)
        assert "hour" in policy._format_window(3600)

    def test_violation_includes_wait_time(self):
        """Test violation message includes wait time hint."""
        policy = RateLimiterPolicy({
            "limits": {"test_op": {"max_per_second": 1}}
        })

        # Use up limit
        policy.validate(action={"operation": "test_op"}, context={})

        # Next operation should be blocked with wait time
        result = policy.validate(action={"operation": "test_op"}, context={})

        assert result.valid is False
        assert "wait" in result.violations[0].remediation_hint.lower()
        assert "wait_seconds" in result.violations[0].context
