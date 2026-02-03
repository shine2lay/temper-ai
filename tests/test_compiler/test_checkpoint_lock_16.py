"""Tests for code-high-checkpoint-lock-16.

Verifies that FileCheckpointBackend.save_checkpoint() uses atomic file writes
(tempfile + os.replace) to prevent corrupted checkpoints from concurrent writes
or crashes mid-write.
"""

import json
import os
import threading
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.compiler.domain_state import WorkflowDomainState
from src.compiler.checkpoint_backends import FileCheckpointBackend


@pytest.fixture
def temp_dir():
    """Create temporary directory for checkpoints."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def backend(temp_dir):
    """Create file backend with temp directory."""
    return FileCheckpointBackend(checkpoint_dir=temp_dir)


@pytest.fixture
def domain_state():
    """Create sample domain state for testing."""
    domain = WorkflowDomainState(
        workflow_id="wf-lock-test",
        input="test atomic writes"
    )
    domain.set_stage_output("stage1", {"result": "data"})
    return domain


class TestAtomicWritePattern:
    """Verify save_checkpoint uses tempfile + os.replace atomic pattern."""

    def test_uses_os_replace(self, backend, domain_state):
        """save_checkpoint should call os.replace for atomic rename."""
        with patch("src.compiler.checkpoint_backends.os.replace", wraps=os.replace) as mock_replace:
            cp_id = backend.save_checkpoint("wf-lock-test", domain_state)

            mock_replace.assert_called_once()
            # Verify the target path is the checkpoint file
            args = mock_replace.call_args[0]
            assert args[1].name.endswith(".json") or str(args[1]).endswith(".json")

    def test_uses_tempfile(self, backend, domain_state):
        """save_checkpoint should write to a temp file first."""
        with patch("src.compiler.checkpoint_backends.tempfile.mkstemp", wraps=tempfile.mkstemp) as mock_mkstemp:
            cp_id = backend.save_checkpoint("wf-lock-test", domain_state)

            mock_mkstemp.assert_called_once()
            # Temp file should be in the same directory as the checkpoint
            call_kwargs = mock_mkstemp.call_args
            assert call_kwargs[1].get('suffix') == '.tmp' or call_kwargs[1].get('suffix', '').endswith('.tmp')

    def test_temp_file_cleaned_up_on_success(self, backend, domain_state, temp_dir):
        """After successful save, no temp files should remain."""
        backend.save_checkpoint("wf-lock-test", domain_state)

        # Check for leftover temp files
        workflow_dir = Path(temp_dir) / "wf-lock-test"
        tmp_files = list(workflow_dir.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Temp files remain after save: {tmp_files}"


class TestAtomicWriteIntegrity:
    """Verify checkpoint file integrity after atomic writes."""

    def test_checkpoint_valid_json_after_save(self, backend, domain_state):
        """Checkpoint file should always contain valid JSON."""
        cp_id = backend.save_checkpoint("wf-lock-test", domain_state)

        # Load directly from file to verify JSON validity
        loaded = backend.load_checkpoint("wf-lock-test", cp_id)
        assert loaded.workflow_id == "wf-lock-test"
        assert loaded.input == "test atomic writes"

    def test_concurrent_saves_produce_valid_files(self, temp_dir, domain_state):
        """10 threads writing simultaneously should all produce valid JSON."""
        backend = FileCheckpointBackend(checkpoint_dir=temp_dir)
        errors = []
        checkpoint_ids = []
        barrier = threading.Barrier(10)
        lock = threading.Lock()

        def save_worker(thread_id):
            try:
                barrier.wait(timeout=5)
                ds = WorkflowDomainState(
                    workflow_id="wf-concurrent",
                    input=f"thread-{thread_id}"
                )
                ds.set_stage_output("stage1", {"thread": thread_id})
                cp_id = backend.save_checkpoint(
                    "wf-concurrent", ds,
                    checkpoint_id=f"cp-thread-{thread_id}"
                )
                with lock:
                    checkpoint_ids.append(cp_id)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=save_worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert len(checkpoint_ids) == 10

        # Verify all checkpoint files are valid JSON
        for cp_id in checkpoint_ids:
            loaded = backend.load_checkpoint("wf-concurrent", cp_id)
            assert loaded.workflow_id == "wf-concurrent"

    def test_no_temp_files_after_concurrent_saves(self, temp_dir, domain_state):
        """After concurrent saves, no temp files should remain."""
        backend = FileCheckpointBackend(checkpoint_dir=temp_dir)
        barrier = threading.Barrier(5)

        def save_worker(thread_id):
            barrier.wait(timeout=5)
            ds = WorkflowDomainState(workflow_id="wf-tmp", input=f"t-{thread_id}")
            backend.save_checkpoint("wf-tmp", ds, checkpoint_id=f"cp-t-{thread_id}")

        threads = [threading.Thread(target=save_worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        workflow_dir = Path(temp_dir) / "wf-tmp"
        tmp_files = list(workflow_dir.glob("*.tmp")) + list(workflow_dir.glob(".cp-*"))
        assert len(tmp_files) == 0, f"Temp files remain: {tmp_files}"


class TestCrashRecovery:
    """Verify previous checkpoint survives a simulated crash during write."""

    def test_previous_checkpoint_intact_on_write_failure(self, backend, domain_state):
        """If write fails mid-way, the previous checkpoint should be intact."""
        # Save initial checkpoint
        cp_id = backend.save_checkpoint(
            "wf-crash", domain_state, checkpoint_id="cp-good"
        )

        # Verify initial checkpoint
        loaded = backend.load_checkpoint("wf-crash", "cp-good")
        assert loaded.input == "test atomic writes"

        # Simulate a crash during the second save to the SAME checkpoint ID
        # by making json.dump raise mid-write
        original_dump = json.dump

        def crashing_dump(data, f, **kwargs):
            f.write("{corrupted")
            raise IOError("Simulated disk failure")

        with patch("src.compiler.checkpoint_backends.json.dump", side_effect=crashing_dump):
            with pytest.raises(IOError):
                new_ds = WorkflowDomainState(workflow_id="wf-crash", input="bad data")
                backend.save_checkpoint("wf-crash", new_ds, checkpoint_id="cp-good")

        # Original checkpoint should still be intact and loadable
        loaded = backend.load_checkpoint("wf-crash", "cp-good")
        assert loaded.input == "test atomic writes"

    def test_temp_file_cleaned_on_failure(self, backend, temp_dir):
        """Temp file should be removed if write fails."""
        ds = WorkflowDomainState(workflow_id="wf-cleanup", input="test")

        with patch("src.compiler.checkpoint_backends.json.dump", side_effect=IOError("disk full")):
            with pytest.raises(IOError):
                backend.save_checkpoint("wf-cleanup", ds)

        # No temp files should remain
        workflow_dir = Path(temp_dir) / "wf-cleanup"
        if workflow_dir.exists():
            tmp_files = list(workflow_dir.glob("*.tmp")) + list(workflow_dir.glob(".cp-*"))
            assert len(tmp_files) == 0, f"Temp files remain after failure: {tmp_files}"


class TestFsyncCalled:
    """Verify fsync is called to flush data to disk before rename."""

    def test_fsync_called_before_replace(self, backend, domain_state):
        """os.fsync should be called before os.replace for durability."""
        call_order = []

        original_fsync = os.fsync
        original_replace = os.replace

        def tracking_fsync(fd):
            call_order.append("fsync")
            return original_fsync(fd)

        def tracking_replace(src, dst):
            call_order.append("replace")
            return original_replace(src, dst)

        with patch("src.compiler.checkpoint_backends.os.fsync", side_effect=tracking_fsync):
            with patch("src.compiler.checkpoint_backends.os.replace", side_effect=tracking_replace):
                backend.save_checkpoint("wf-lock-test", domain_state)

        assert "fsync" in call_order, "os.fsync was not called"
        assert "replace" in call_order, "os.replace was not called"
        assert call_order.index("fsync") < call_order.index("replace"), (
            f"fsync must be called before replace, got order: {call_order}"
        )
