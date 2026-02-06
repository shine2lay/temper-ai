"""Tests for ResourceLimitPolicy.

Tests cover:
- Policy initialization and configuration
- File size limit enforcement (read/write)
- Disk space limit enforcement
- Memory usage monitoring
- CPU time tracking
- Resource usage reporting
- Custom configuration
"""
import os
import tempfile
import time
from unittest.mock import Mock, patch

from src.safety.interfaces import ViolationSeverity
from src.safety.policies.resource_limit_policy import ResourceLimitPolicy


class TestResourceLimitPolicyBasics:
    """Basic tests for ResourceLimitPolicy."""

    def test_default_initialization(self):
        """Test policy with default configuration."""
        policy = ResourceLimitPolicy()

        assert policy.name == "resource_limit"
        assert policy.version == "1.0.0"
        assert policy.priority == 80

        # Check default limits
        assert policy.max_file_size_read == 100 * 1024 * 1024  # 100MB
        assert policy.max_file_size_write == 10 * 1024 * 1024  # 10MB
        assert policy.max_memory_per_operation == 500 * 1024 * 1024  # 500MB
        assert policy.max_cpu_time == 30.0
        assert policy.min_free_disk_space == 1024 * 1024 * 1024  # 1GB

    def test_custom_configuration(self):
        """Test policy with custom configuration."""
        config = {
            "max_file_size_read": 50 * 1024 * 1024,
            "max_file_size_write": 5 * 1024 * 1024,
            "max_memory_per_operation": 100 * 1024 * 1024,
            "max_cpu_time": 10.0,
            "min_free_disk_space": 500 * 1024 * 1024,
            "track_memory": False,
            "track_cpu": False
        }
        policy = ResourceLimitPolicy(config)

        assert policy.max_file_size_read == 50 * 1024 * 1024
        assert policy.max_file_size_write == 5 * 1024 * 1024
        assert policy.max_memory_per_operation == 100 * 1024 * 1024
        assert policy.max_cpu_time == 10.0
        assert policy.min_free_disk_space == 500 * 1024 * 1024
        assert policy.track_memory is False
        assert policy.track_cpu is False


class TestFileSizeLimits:
    """Tests for file size limit enforcement."""

    def test_small_file_read_allowed(self):
        """Test that small file reads are allowed."""
        policy = ResourceLimitPolicy()

        # Create a small temp file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("small content")
            temp_path = f.name

        try:
            result = policy.validate(
                action={"operation": "file_read", "path": temp_path},
                context={"agent_id": "agent-123"}
            )

            assert result.valid
            assert len(result.violations) == 0
        finally:
            os.unlink(temp_path)

    def test_large_file_read_blocked(self):
        """Test that large file reads are blocked."""
        config = {
            "max_file_size_read": 1024  # 1KB limit for testing
        }
        policy = ResourceLimitPolicy(config)

        # Create a file larger than limit
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("x" * 2048)  # 2KB
            temp_path = f.name

        try:
            result = policy.validate(
                action={"operation": "file_read", "path": temp_path},
                context={"agent_id": "agent-123"}
            )

            assert not result.valid
            assert len(result.violations) == 1
            assert result.violations[0].severity >= ViolationSeverity.HIGH
            assert "exceeds read limit" in result.violations[0].message.lower()
            assert result.violations[0].metadata["file_size"] == 2048
            assert result.violations[0].metadata["max_size"] == 1024
        finally:
            os.unlink(temp_path)

    def test_large_file_write_blocked(self):
        """Test that large file writes are blocked."""
        config = {
            "max_file_size_write": 512  # 512B limit for testing
        }
        policy = ResourceLimitPolicy(config)

        # Create a file larger than write limit
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("x" * 1024)  # 1KB
            temp_path = f.name

        try:
            result = policy.validate(
                action={"operation": "file_write", "path": temp_path},
                context={"agent_id": "agent-123"}
            )

            assert not result.valid
            assert len(result.violations) >= 1  # May also have disk space violation

            # Find file size violation
            file_violations = [v for v in result.violations if "exceeds write limit" in v.message.lower()]
            assert len(file_violations) == 1
            assert file_violations[0].metadata["operation"] == "write"
        finally:
            os.unlink(temp_path)

    def test_different_limits_for_read_write(self):
        """Test that read and write operations have different limits."""
        config = {
            "max_file_size_read": 2048,  # 2KB read limit
            "max_file_size_write": 512   # 512B write limit
        }
        policy = ResourceLimitPolicy(config)

        # Create a 1KB file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("x" * 1024)
            temp_path = f.name

        try:
            # Read should be allowed (1KB < 2KB limit)
            read_result = policy.validate(
                action={"operation": "file_read", "path": temp_path},
                context={"agent_id": "agent-123"}
            )
            assert read_result.valid

            # Write should be blocked (1KB > 512B limit)
            write_result = policy.validate(
                action={"operation": "file_write", "path": temp_path},
                context={"agent_id": "agent-123"}
            )
            # Check for file size violation specifically
            file_violations = [v for v in write_result.violations if "file size" in v.message.lower()]
            assert len(file_violations) == 1
        finally:
            os.unlink(temp_path)

    def test_nonexistent_file_no_violation(self):
        """Test that nonexistent files don't cause violations."""
        policy = ResourceLimitPolicy()

        result = policy.validate(
            action={"operation": "file_read", "path": "/nonexistent/file.txt"},
            context={"agent_id": "agent-123"}
        )

        # Should be valid (no file size violation since file doesn't exist)
        # Other policies will handle the missing file
        assert result.valid

    def test_operation_type_aliases(self):
        """Test that various operation types are recognized."""
        policy = ResourceLimitPolicy({"max_file_size_read": 100})

        # Create small temp file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("x" * 50)
            temp_path = f.name

        try:
            # Test read aliases
            for op in ["read", "read_file", "load", "open"]:
                result = policy.validate(
                    action={"operation": op, "path": temp_path},
                    context={}
                )
                assert result.valid, f"Operation {op} should be allowed"

            # Test write aliases
            for op in ["write", "write_file", "save", "create"]:
                result = policy.validate(
                    action={"operation": op, "path": temp_path},
                    context={}
                )
                # May have disk space violation, but should process write operations
                assert result.metadata["limits_checked"]["disk_space"]
        finally:
            os.unlink(temp_path)


class TestDiskSpaceLimits:
    """Tests for disk space limit enforcement."""

    def test_sufficient_disk_space_allowed(self):
        """Test that operations with sufficient disk space are allowed."""
        config = {
            "min_free_disk_space": 100  # Very low limit (100 bytes)
        }
        policy = ResourceLimitPolicy(config)

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            temp_path = f.name

        try:
            result = policy.validate(
                action={"operation": "file_write", "path": temp_path},
                context={"agent_id": "agent-123"}
            )

            # Should be valid (plenty of disk space)
            assert result.valid
        finally:
            os.unlink(temp_path)

    @patch('psutil.disk_usage')
    def test_insufficient_disk_space_blocked(self, mock_disk_usage):
        """Test that operations with insufficient disk space are blocked."""
        # Mock disk usage to simulate low space
        mock_usage = Mock()
        mock_usage.total = 10 * 1024 * 1024 * 1024  # 10GB
        mock_usage.used = 9.5 * 1024 * 1024 * 1024  # 9.5GB
        mock_usage.free = 500 * 1024 * 1024  # 500MB free
        mock_usage.percent = 95.0
        mock_disk_usage.return_value = mock_usage

        config = {
            "min_free_disk_space": 1024 * 1024 * 1024  # 1GB required
        }
        policy = ResourceLimitPolicy(config)

        result = policy.validate(
            action={"operation": "file_write", "path": "/tmp/test.txt"},
            context={"agent_id": "agent-123"}
        )

        assert not result.valid
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL
        assert "insufficient disk space" in result.violations[0].message.lower()

    def test_disk_tracking_disabled(self):
        """Test that disk tracking can be disabled."""
        config = {
            "track_disk": False,
            "min_free_disk_space": 1024 * 1024 * 1024 * 1024  # Impossibly high
        }
        policy = ResourceLimitPolicy(config)

        result = policy.validate(
            action={"operation": "file_write", "path": "/tmp/test.txt"},
            context={}
        )

        # Should be valid even with impossibly high limit (tracking disabled)
        assert result.valid

    @patch('psutil.disk_usage')
    def test_disk_space_safety_margin(self, mock_disk_usage):
        """Test that 20% safety margin is applied to prevent TOCTOU race conditions.

        The safety margin accounts for:
        - Other processes writing to disk between check and write
        - File system metadata overhead
        - Buffer space needed for atomic writes

        Example scenario:
        - Required: 1GB (base)
        - With 20% margin: 1.2GB
        - Free space: 1.1GB
        - Result: BLOCKED (1.1GB < 1.2GB) despite being above base requirement
        """
        # Mock disk usage: free space is above base requirement but below margin
        mock_usage = Mock()
        mock_usage.total = 10 * 1024 * 1024 * 1024  # 10GB
        mock_usage.used = 8.9 * 1024 * 1024 * 1024  # 8.9GB
        mock_usage.free = 1.1 * 1024 * 1024 * 1024  # 1.1GB free
        mock_usage.percent = 89.0
        mock_disk_usage.return_value = mock_usage

        config = {
            "min_free_disk_space": 1024 * 1024 * 1024  # 1GB base requirement
        }
        policy = ResourceLimitPolicy(config)

        result = policy.validate(
            action={"operation": "file_write", "path": "/tmp/test.txt"},
            context={"agent_id": "agent-123"}
        )

        # Should be blocked: 1.1GB free < 1.2GB required (with 20% margin)
        assert not result.valid
        assert len(result.violations) == 1
        violation = result.violations[0]
        assert violation.severity == ViolationSeverity.CRITICAL
        assert "20% safety margin" in violation.message
        assert violation.metadata["safety_margin_percent"] == 20
        assert violation.metadata["required_space_base"] == 1024 * 1024 * 1024
        # Required with margin = 1GB * 1.2 = 1.2GB
        assert violation.metadata["required_space_with_margin"] == int(1024 * 1024 * 1024 * 1.2)


class TestMemoryMonitoring:
    """Tests for memory usage monitoring."""

    @patch('psutil.Process')
    @patch('psutil.virtual_memory')
    def test_normal_memory_usage_allowed(self, mock_virtual_memory, mock_process):
        """Test that normal memory usage is allowed."""
        # Mock process memory
        mock_proc = Mock()
        mock_mem_info = Mock()
        mock_mem_info.rss = 100 * 1024 * 1024  # 100MB
        mock_proc.memory_info.return_value = mock_mem_info
        mock_process.return_value = mock_proc

        # Mock system memory
        mock_sys_mem = Mock()
        mock_sys_mem.total = 16 * 1024 * 1024 * 1024  # 16GB
        mock_sys_mem.available = 8 * 1024 * 1024 * 1024  # 8GB
        mock_sys_mem.percent = 50.0
        mock_virtual_memory.return_value = mock_sys_mem

        policy = ResourceLimitPolicy()

        result = policy.validate(
            action={"operation": "compute"},
            context={"agent_id": "agent-123"}
        )

        assert result.valid

    @patch('psutil.Process')
    @patch('psutil.virtual_memory')
    def test_excessive_memory_usage_blocked(self, mock_virtual_memory, mock_process):
        """Test that excessive memory usage is blocked."""
        # Mock process using too much memory
        mock_proc = Mock()
        mock_mem_info = Mock()
        mock_mem_info.rss = 600 * 1024 * 1024  # 600MB (> 500MB limit)
        mock_proc.memory_info.return_value = mock_mem_info
        mock_process.return_value = mock_proc

        # Mock system memory
        mock_sys_mem = Mock()
        mock_sys_mem.total = 16 * 1024 * 1024 * 1024
        mock_sys_mem.available = 1 * 1024 * 1024 * 1024
        mock_sys_mem.percent = 93.75
        mock_virtual_memory.return_value = mock_sys_mem

        policy = ResourceLimitPolicy()

        result = policy.validate(
            action={"operation": "compute"},
            context={"agent_id": "agent-123"}
        )

        assert not result.valid
        assert len(result.violations) == 1
        assert "memory usage exceeds limit" in result.violations[0].message.lower()
        assert result.violations[0].severity >= ViolationSeverity.HIGH

    def test_memory_tracking_disabled(self):
        """Test that memory tracking can be disabled."""
        config = {
            "track_memory": False,
            "max_memory_per_operation": 1  # Impossibly low
        }
        policy = ResourceLimitPolicy(config)

        result = policy.validate(
            action={"operation": "compute"},
            context={}
        )

        # Should be valid even with impossibly low limit (tracking disabled)
        assert result.valid


class TestOperationTracking:
    """Tests for operation start/end tracking."""

    def test_start_end_operation_cpu_time(self):
        """Test CPU time tracking for operations."""
        policy = ResourceLimitPolicy()

        policy.start_operation("task-123")
        time.sleep(0.1)  # Simulate work
        stats = policy.end_operation("task-123")

        assert stats["operation_id"] == "task-123"
        assert stats["cpu_time"] is not None
        assert stats["cpu_time"] >= 0.1
        assert stats["cpu_exceeded"] is False  # 0.1s < 30s limit

    def test_cpu_time_exceeded(self):
        """Test detection of CPU time limit exceeded."""
        config = {
            "max_cpu_time": 0.05  # 50ms limit
        }
        policy = ResourceLimitPolicy(config)

        policy.start_operation("slow-task")
        time.sleep(0.1)  # 100ms work
        stats = policy.end_operation("slow-task")

        assert stats["cpu_exceeded"] is True

    @patch('psutil.Process')
    def test_memory_delta_tracking(self, mock_process):
        """Test memory delta tracking for operations."""
        # Mock memory growth during operation
        mock_proc = Mock()
        call_count = [0]

        def mock_memory_info():
            call_count[0] += 1
            mem_info = Mock()
            if call_count[0] == 1:
                mem_info.rss = 100 * 1024 * 1024  # 100MB at start
            else:
                mem_info.rss = 150 * 1024 * 1024  # 150MB at end
            return mem_info

        mock_proc.memory_info = mock_memory_info
        mock_process.return_value = mock_proc

        policy = ResourceLimitPolicy()

        policy.start_operation("memory-task")
        stats = policy.end_operation("memory-task")

        assert stats["memory_delta"] is not None
        assert stats["memory_delta"] == 50 * 1024 * 1024  # 50MB increase

    def test_operation_not_started(self):
        """Test ending an operation that wasn't started."""
        policy = ResourceLimitPolicy()

        stats = policy.end_operation("nonexistent-task")

        assert stats["cpu_time"] is None
        assert stats["memory_delta"] is None


class TestResourceUsageReporting:
    """Tests for resource usage reporting."""

    @patch('psutil.Process')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    @patch('psutil.cpu_percent')
    @patch('psutil.cpu_count')
    def test_get_current_usage(
        self, mock_cpu_count, mock_cpu_percent, mock_disk_usage,
        mock_virtual_memory, mock_process
    ):
        """Test getting current resource usage."""
        # Mock process memory
        mock_proc = Mock()
        mock_mem_info = Mock()
        mock_mem_info.rss = 200 * 1024 * 1024
        mock_mem_info.vms = 400 * 1024 * 1024
        mock_proc.memory_info.return_value = mock_mem_info
        mock_process.return_value = mock_proc

        # Mock system memory
        mock_sys_mem = Mock()
        mock_sys_mem.total = 16 * 1024 * 1024 * 1024
        mock_sys_mem.available = 8 * 1024 * 1024 * 1024
        mock_sys_mem.used = 8 * 1024 * 1024 * 1024
        mock_sys_mem.percent = 50.0
        mock_virtual_memory.return_value = mock_sys_mem

        # Mock disk usage
        mock_disk = Mock()
        mock_disk.total = 500 * 1024 * 1024 * 1024
        mock_disk.used = 200 * 1024 * 1024 * 1024
        mock_disk.free = 300 * 1024 * 1024 * 1024
        mock_disk.percent = 40.0
        mock_disk_usage.return_value = mock_disk

        # Mock CPU
        mock_cpu_percent.return_value = 25.0
        mock_cpu_count.return_value = 8

        policy = ResourceLimitPolicy()
        usage = policy.get_current_usage()

        # Check memory stats
        assert usage["memory"] is not None
        assert usage["memory"]["process_rss"] == 200 * 1024 * 1024
        assert usage["memory"]["system_total"] == 16 * 1024 * 1024 * 1024
        assert usage["memory"]["percent"] == 50.0

        # Check disk stats
        assert usage["disk"] is not None
        assert usage["disk"]["total"] == 500 * 1024 * 1024 * 1024
        assert usage["disk"]["percent"] == 40.0

        # Check CPU stats
        assert usage["cpu"] is not None
        assert usage["cpu"]["percent"] == 25.0
        assert usage["cpu"]["count"] == 8


class TestHelperMethods:
    """Tests for helper methods."""

    def test_format_bytes(self):
        """Test byte formatting for human readability."""
        policy = ResourceLimitPolicy()

        assert policy._format_bytes(512) == "512.0 B"
        assert policy._format_bytes(1024) == "1.0 KB"
        assert policy._format_bytes(1536) == "1.5 KB"
        assert policy._format_bytes(1024 * 1024) == "1.0 MB"
        assert policy._format_bytes(10 * 1024 * 1024) == "10.0 MB"
        assert policy._format_bytes(1024 * 1024 * 1024) == "1.0 GB"
        assert policy._format_bytes(1024 * 1024 * 1024 * 1024) == "1.0 TB"


class TestIntegration:
    """Integration tests for ResourceLimitPolicy."""

    def test_multiple_violations(self):
        """Test that multiple violations can be detected simultaneously."""
        config = {
            "max_file_size_write": 100,  # 100 bytes
            "min_free_disk_space": 1024 * 1024 * 1024 * 1024  # 1TB (likely exceeded)
        }
        policy = ResourceLimitPolicy(config)

        # Create a file larger than limit
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("x" * 200)  # 200 bytes
            temp_path = f.name

        try:
            result = policy.validate(
                action={"operation": "file_write", "path": temp_path},
                context={"agent_id": "agent-123"}
            )

            assert not result.valid
            # Should have both file size and disk space violations
            assert len(result.violations) >= 1  # At least file size violation
        finally:
            os.unlink(temp_path)

    def test_unknown_operation_type(self):
        """Test that unknown operation types don't cause errors."""
        policy = ResourceLimitPolicy()

        result = policy.validate(
            action={"operation": "unknown_op"},
            context={}
        )

        # Should be valid (no specific checks for unknown operations)
        assert result.valid

    def test_metadata_includes_limits_checked(self):
        """Test that metadata includes information about which limits were checked."""
        policy = ResourceLimitPolicy()

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            temp_path = f.name

        try:
            result = policy.validate(
                action={"operation": "file_write", "path": temp_path},
                context={}
            )

            assert "limits_checked" in result.metadata
            assert result.metadata["limits_checked"]["file_size"] is True
            assert result.metadata["limits_checked"]["disk_space"] is True
            assert result.metadata["limits_checked"]["memory"] is True
        finally:
            os.unlink(temp_path)
