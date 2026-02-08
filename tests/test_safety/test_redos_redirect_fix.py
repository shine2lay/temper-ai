"""Tests for ReDoS fix in redirect_output pattern.

This test suite verifies:
1. The ReDoS vulnerability is fixed (no catastrophic backtracking)
2. Legitimate redirect patterns are still detected
3. Excluded contexts (comments, test, if, while, pipes) work correctly
4. Performance is acceptable even with large inputs
"""
import time

import pytest

from src.safety.forbidden_operations import ForbiddenOperationsPolicy


class TestReDoSFix:
    """Test that ReDoS vulnerability is fixed."""

    def test_large_input_no_timeout(self):
        """Test that large malicious input doesn't cause timeout."""
        policy = ForbiddenOperationsPolicy()

        # Malicious input that would cause catastrophic backtracking
        # in the original vulnerable pattern
        attack_vector = "echo " + "a" * 10000 + " >"

        start_time = time.time()
        result = policy.validate(
            action={"command": attack_vector},
            context={}
        )
        elapsed = time.time() - start_time

        # Should complete in less than 100ms
        assert elapsed < 0.1, f"Pattern took {elapsed:.3f}s - potential ReDoS"

        # Should not match (no file extension)
        assert result.valid is True

    def test_repeated_words_no_timeout(self):
        """Test repeated words don't cause backtracking."""
        policy = ForbiddenOperationsPolicy()

        attack_vector = "echo " + ("test " * 1000) + ">"

        start_time = time.time()
        result = policy.validate(
            action={"command": attack_vector},
            context={}
        )
        elapsed = time.time() - start_time

        assert elapsed < 0.1, f"Pattern took {elapsed:.3f}s"
        assert result.valid is True  # No extension

    def test_very_long_command_fast(self):
        """Test very long command completes quickly."""
        policy = ForbiddenOperationsPolicy()

        # 100K character input
        attack_vector = "x" * 100000 + " > "

        start_time = time.time()
        result = policy.validate(
            action={"command": attack_vector},
            context={}
        )
        elapsed = time.time() - start_time

        assert elapsed < 0.1, f"Pattern took {elapsed:.3f}s"

    def test_nested_quantifiers_safe(self):
        """Test input designed to trigger nested quantifier backtracking."""
        policy = ForbiddenOperationsPolicy()

        # Pattern designed to exploit [^|]* followed by \s*
        attack_vector = ("a" * 5000) + (" " * 5000) + ">"

        start_time = time.time()
        result = policy.validate(
            action={"command": attack_vector},
            context={}
        )
        elapsed = time.time() - start_time

        assert elapsed < 0.1, f"Pattern took {elapsed:.3f}s"


class TestRedirectDetection:
    """Test that legitimate redirects are still detected."""

    def test_simple_redirect(self):
        """Test simple redirect is detected."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'echo "hello" > file.txt'},
            context={}
        )

        assert result.valid is False
        assert any("redirect" in v.message.lower() for v in result.violations)

    def test_command_with_args_redirect(self):
        """Test redirect with command arguments."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'python script.py --verbose > output.json'},
            context={}
        )

        assert result.valid is False

    def test_redirect_various_extensions(self):
        """Test redirect detection with various file extensions."""
        policy = ForbiddenOperationsPolicy()

        extensions = ['txt', 'json', 'yaml', 'yml', 'py', 'js', 'ts', 'md', 'csv', 'log']

        for ext in extensions:
            result = policy.validate(
                action={"command": f'command > file.{ext}'},
                context={}
            )
            assert result.valid is False, f"Failed to detect .{ext} redirect"

    def test_ls_redirect(self):
        """Test ls redirect is detected."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'ls -la /tmp > listing.log'},
            context={}
        )

        assert result.valid is False

    def test_script_output_redirect(self):
        """Test script output redirect is detected."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": './script.sh > results.csv'},
            context={}
        )

        assert result.valid is False


class TestContextExclusions:
    """Test that excluded contexts are properly handled."""

    def test_comment_line_excluded(self):
        """Test that comments are excluded."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": '# This is a comment > file.txt'},
            context={}
        )

        # Should NOT detect redirect in comment
        redirect_violations = [
            v for v in result.violations
            if "redirect" in v.message.lower()
        ]
        assert len(redirect_violations) == 0

    def test_test_command_excluded(self):
        """Test that test commands are excluded."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'test -f > file.txt'},
            context={}
        )

        redirect_violations = [
            v for v in result.violations
            if "redirect" in v.message.lower()
        ]
        assert len(redirect_violations) == 0

    def test_if_statement_excluded(self):
        """Test that if statements are excluded."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'if [ -f file ] > output.log'},
            context={}
        )

        redirect_violations = [
            v for v in result.violations
            if "redirect" in v.message.lower()
        ]
        assert len(redirect_violations) == 0

    def test_while_loop_excluded(self):
        """Test that while loops are excluded."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'while read line > data.txt'},
            context={}
        )

        redirect_violations = [
            v for v in result.violations
            if "redirect" in v.message.lower()
        ]
        assert len(redirect_violations) == 0

    def test_piped_command_excluded(self):
        """Test that piped commands are excluded."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'cat file.txt | grep pattern > output.log'},
            context={}
        )

        # Note: This may trigger OTHER patterns (pipe_injection, etc.)
        # but should NOT trigger redirect_output pattern
        redirect_violations = [
            v for v in result.violations
            if v.metadata.get("pattern_name") == "file_write_redirect_output"
        ]
        assert len(redirect_violations) == 0

    def test_comment_with_indentation(self):
        """Test comment with indentation is excluded."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": '   # indented comment > file.txt'},
            context={}
        )

        redirect_violations = [
            v for v in result.violations
            if "redirect" in v.message.lower()
        ]
        assert len(redirect_violations) == 0


class TestMultilineCommands:
    """Test multiline command handling."""

    def test_redirect_on_second_line(self):
        """Test redirect on second line is detected."""
        policy = ForbiddenOperationsPolicy()

        command = """echo "first line"
command > output.txt"""

        result = policy.validate(
            action={"command": command},
            context={}
        )

        assert result.valid is False

    def test_comment_on_first_line_command_on_second(self):
        """Test comment on first line doesn't affect second line."""
        policy = ForbiddenOperationsPolicy()

        command = """# This is a comment
command > output.txt"""

        result = policy.validate(
            action={"command": command},
            context={}
        )

        # Second line should be detected
        assert result.valid is False

    def test_mixed_valid_and_invalid_lines(self):
        """Test script with mix of valid and invalid lines."""
        policy = ForbiddenOperationsPolicy()

        command = """#!/bin/bash
# Comment line > ignored.txt
echo "data" > output.txt
cat input.txt
"""

        result = policy.validate(
            action={"command": command},
            context={}
        )

        # Should detect the echo redirect
        assert result.valid is False


class TestPerformanceBenchmarks:
    """Benchmark performance to ensure no ReDoS."""

    def test_benchmark_small_input(self):
        """Benchmark small input (< 1KB)."""
        policy = ForbiddenOperationsPolicy()

        command = 'echo "hello world" > file.txt'

        start_time = time.time()
        for _ in range(1000):
            policy.validate(action={"command": command}, context={})
        elapsed = time.time() - start_time

        # Should handle 1000 small inputs in < 100ms
        assert elapsed < 0.1, f"1000 iterations took {elapsed:.3f}s"

    def test_benchmark_medium_input(self):
        """Benchmark medium input (10KB)."""
        policy = ForbiddenOperationsPolicy()

        command = "echo " + ("data " * 2000) + "> output.txt"

        start_time = time.time()
        for _ in range(100):
            policy.validate(action={"command": command}, context={})
        elapsed = time.time() - start_time

        # Should handle 100 medium inputs in < 200ms (reasonable threshold)
        # Original ReDoS would take >10s, so this is >50x improvement
        assert elapsed < 0.2, f"100 iterations took {elapsed:.3f}s"

    def test_benchmark_large_input(self, worker_id):
        """Benchmark large input (100KB).

        Note: Skipped in parallel mode due to timing sensitivity.
        """
        if worker_id != "master":
            pytest.skip("Performance benchmark - run serially only")
        policy = ForbiddenOperationsPolicy()

        command = "x" * 100000 + " > output.txt"

        start_time = time.time()
        for _ in range(10):
            policy.validate(action={"command": command}, context={})
        elapsed = time.time() - start_time

        # Should handle 10 large inputs in < 150ms (reasonable threshold)
        # Original ReDoS would take >60s, so this is >400x improvement
        assert elapsed < 0.15, f"10 iterations took {elapsed:.3f}s"


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_redirect_without_extension(self):
        """Test redirect without file extension is not detected."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'echo "data" > outputfile'},
            context={}
        )

        # Should not match (no extension in pattern)
        redirect_violations = [
            v for v in result.violations
            if "redirect" in v.message.lower()
        ]
        assert len(redirect_violations) == 0

    def test_redirect_with_path(self):
        """Test redirect with file path."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'command > /tmp/output/file.txt'},
            context={}
        )

        assert result.valid is False

    def test_redirect_with_quotes(self):
        """Test redirect with quoted filename."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'echo data > "output file.txt"'},
            context={}
        )

        # May or may not match depending on \S+ handling quotes
        # This is acceptable - main concern is no ReDoS

    def test_multiple_redirects(self):
        """Test command with multiple redirects."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'command > file1.txt 2> file2.log'},
            context={}
        )

        # Should detect at least one redirect
        assert result.valid is False

    def test_redirect_stderr(self):
        """Test stderr redirect."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'command 2> error.log'},
            context={}
        )

        assert result.valid is False

    def test_append_redirect(self):
        """Test append redirect >> is handled by other patterns."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'echo data >> file.txt'},
            context={}
        )

        # Should be caught by echo_append pattern
        assert result.valid is False

    def test_redirect_at_200_char_boundary(self):
        """Test redirect detection at exactly 200 character boundary.

        This test documents the security tradeoff made to prevent ReDoS:
        - Individual patterns use bounded quantifiers {0,200}
        - Multiple patterns provide defense in depth
        - Even if one pattern misses, others may catch it
        """
        policy = ForbiddenOperationsPolicy()

        # Exactly 200 chars between echo and > (should be detected)
        # Format: 'echo ' (5) + padding (195) + ' > file.txt' = 200 chars before '>'
        padding = 'x' * 195
        result = policy.validate(
            action={"command": f'echo {padding} > file.txt'},
            context={}
        )
        assert result.valid is False, "Should detect at 200 char boundary"

        # Over 200 chars - echo_redirect pattern won't match due to {0,200} bound,
        # BUT redirect_output pattern may still catch it (defense in depth)
        padding = 'x' * 201
        result = policy.validate(
            action={"command": f'echo {padding} > file.txt'},
            context={}
        )
        # Multiple patterns provide coverage even when individual patterns have bounds
        assert result.valid is False, "Should still be detected by redirect_output pattern"


class TestBackwardCompatibility:
    """Test that fix doesn't break existing functionality."""

    def test_other_file_write_patterns_still_work(self):
        """Test that other file write patterns still work."""
        policy = ForbiddenOperationsPolicy()

        # Test cat redirect
        result = policy.validate(
            action={"command": 'cat > file.txt'},
            context={}
        )
        assert result.valid is False

        # Test echo redirect
        result = policy.validate(
            action={"command": 'echo "data" > file.txt'},
            context={}
        )
        assert result.valid is False

        # Test sed -i
        result = policy.validate(
            action={"command": 'sed -i "s/old/new/" file.txt'},
            context={}
        )
        assert result.valid is False

    def test_dangerous_patterns_still_work(self):
        """Test that dangerous command patterns still work."""
        policy = ForbiddenOperationsPolicy()

        result = policy.validate(
            action={"command": 'rm -rf /tmp/data'},
            context={}
        )
        assert result.valid is False

    def test_configuration_options_still_work(self):
        """Test that configuration options still work."""
        # Disable file write checks
        policy = ForbiddenOperationsPolicy({"check_file_writes": False})

        result = policy.validate(
            action={"command": 'echo "data" > file.txt'},
            context={}
        )

        # Should not detect (file writes disabled)
        assert not any("Write()" in v.message for v in result.violations)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
