"""
Stress tests and extreme edge cases.

Coverage:
- High load scenarios
- Resource limits
- Boundary conditions
- Extreme concurrency
- Large data sets
- Memory pressure
"""

import os
import threading
import time
import pytest


class TestHighLoad:
    """Test system under high load."""

    @pytest.mark.slow
    def test_many_agents(self, running_daemon, client):
        """System should handle many agents."""
        # Register 200 agents
        for i in range(200):
            client.call('register', {
                'agent_id': f'load-agent-{i:03d}',
                'pid': os.getpid() + i
            })

        # Verify all registered
        status = client.call('status', {})
        assert status['agents'] >= 200

    @pytest.mark.slow
    def test_many_tasks(self, running_daemon, client):
        """System should handle many tasks."""
        # Create 1000 tasks
        for i in range(1000):
            client.call('task_create', {
                'task_id': f'test-low-load-{i:04d}',
                'subject': f'Load test task {i}',
                'description': 'Description',
                'priority': 4
            })

        # Verify count
        status = client.call('status', {})
        assert status['tasks']['pending'] >= 1000

    @pytest.mark.slow
    def test_many_locks(self, running_daemon, client):
        """System should handle many locks."""
        client.call('register', {'agent_id': 'lock-agent', 'pid': os.getpid()})

        # Acquire 500 locks
        for i in range(500):
            client.call('lock_acquire', {
                'agent_id': 'lock-agent',
                'file_path': f'file-{i:04d}.py'
            })

        # Verify
        locks = client.call('lock_list', {'agent_id': 'lock-agent'})
        assert len(locks['locks']) >= 500

    @pytest.mark.slow
    def test_high_throughput(self, running_daemon, client):
        """System should handle high operation throughput."""
        # Register agents
        for i in range(20):
            client.call('register', {
                'agent_id': f'throughput-agent-{i}',
                'pid': os.getpid() + i
            })

        # Create tasks
        for i in range(200):
            client.call('task_create', {
                'task_id': f'test-low-throughput-{i:03d}',
                'subject': f'Throughput test {i}',
                'description': 'Description',
                'priority': 4
            })

        # Concurrent claims and completions
        results = []

        def work(agent_idx):
            for task_idx in range(10):
                task_id = f'test-low-throughput-{agent_idx * 10 + task_idx:03d}'
                try:
                    client.call('task_claim', {
                        'agent_id': f'throughput-agent-{agent_idx}',
                        'task_id': task_id
                    })
                    client.call('task_complete', {
                        'agent_id': f'throughput-agent-{agent_idx}',
                        'task_id': task_id
                    })
                    results.append(('success', agent_idx, task_idx))
                except Exception as e:
                    results.append(('error', agent_idx, str(e)))

        threads = []
        for i in range(20):
            t = threading.Thread(target=work, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Most should succeed
        successes = [r for r in results if r[0] == 'success']
        assert len(successes) >= 180  # At least 90%


class TestExtremeConcurrency:
    """Test extreme concurrent scenarios."""

    @pytest.mark.slow
    def test_concurrent_same_task_claim(self, running_daemon, client):
        """Many agents racing for same task."""
        # Create one task
        client.call('task_create', {
            'task_id': 'test-low-race-target',
            'subject': 'Race target task',
            'description': 'Description',
            'priority': 4
        })

        # Register 100 agents
        for i in range(100):
            client.call('register', {
                'agent_id': f'race-agent-{i:03d}',
                'pid': os.getpid() + i
            })

        # All try to claim concurrently
        results = []

        def try_claim(agent_idx):
            try:
                client.call('task_claim', {
                    'agent_id': f'race-agent-{agent_idx:03d}',
                    'task_id': 'test-low-race-target'
                })
                results.append(('success', agent_idx))
            except Exception as e:
                results.append(('failed', agent_idx))

        threads = []
        for i in range(100):
            t = threading.Thread(target=try_claim, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Exactly one should succeed
        successes = [r for r in results if r[0] == 'success']
        assert len(successes) == 1

        # Task should have one owner
        task = client.call('task_get', {'task_id': 'test-low-race-target'})
        assert task['task']['status'] == 'in_progress'
        assert task['task']['owner'] is not None

    @pytest.mark.slow
    def test_concurrent_same_file_lock(self, running_daemon, client):
        """Many agents racing for same file lock."""
        # Register 50 agents
        for i in range(50):
            client.call('register', {
                'agent_id': f'file-race-agent-{i:02d}',
                'pid': os.getpid() + i
            })

        # All try to lock same file
        results = []

        def try_lock(agent_idx):
            try:
                client.call('lock_acquire', {
                    'agent_id': f'file-race-agent-{agent_idx:02d}',
                    'file_path': 'contested.py'
                })
                results.append(('success', agent_idx))
            except Exception as e:
                results.append(('failed', agent_idx))

        threads = []
        for i in range(50):
            t = threading.Thread(target=try_lock, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Exactly one should succeed
        successes = [r for r in results if r[0] == 'success']
        assert len(successes) == 1


class TestResourceLimits:
    """Test system resource limits."""

    def test_very_long_task_id(self, running_daemon, client):
        """Very long task ID should work or fail gracefully."""
        long_id = 'test-low-' + 'x' * 10000

        try:
            client.call('task_create', {
                'task_id': long_id,
                'subject': 'Long ID test subject',
                'description': 'Description',
                'priority': 4
            })

            # If it succeeds, verify we can retrieve it
            task = client.call('task_get', {'task_id': long_id})
            assert task['task']['id'] == long_id
        except Exception as e:
            # If it fails, should be a clear validation error
            assert 'validation' in str(e).lower() or 'invalid' in str(e).lower()

    def test_very_long_subject(self, running_daemon, client):
        """Very long subject should fail validation."""
        long_subject = 'x' * 10000

        with pytest.raises(RuntimeError) as exc_info:
            client.call('task_create', {
                'task_id': 'test-low-long-subject',
                'subject': long_subject,
                'description': 'Description',
                'priority': 4
            })

        assert 'length' in str(exc_info.value).lower()

    def test_very_long_description(self, running_daemon, client):
        """Very long description should work."""
        long_desc = 'x' * 1000000  # 1MB

        # Should work (no length limit on description)
        client.call('task_create', {
            'task_id': 'test-low-long-desc',
            'subject': 'Long description test',
            'description': long_desc,
            'priority': 4
        })

        task = client.call('task_get', {'task_id': 'test-low-long-desc'})
        assert len(task['task']['description']) == 1000000

    def test_very_long_file_path(self, running_daemon, client):
        """Very long file path should work."""
        client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})

        long_path = '/'.join(['dir'] * 1000) + '/file.py'

        # Should work
        client.call('lock_acquire', {
            'agent_id': 'test-agent',
            'file_path': long_path
        })

        locks = client.call('lock_list', {'agent_id': 'test-agent'})
        assert long_path in locks['locks']

    def test_unicode_edge_cases(self, running_daemon, client):
        """Unicode edge cases should be handled."""
        # Emoji in subject
        client.call('task_create', {
            'task_id': 'test-low-emoji',
            'subject': 'Task with emoji 🎉📝✅',
            'description': 'Description with emoji 🚀',
            'priority': 4
        })

        task = client.call('task_get', {'task_id': 'test-low-emoji'})
        assert '🎉' in task['task']['subject']
        assert '🚀' in task['task']['description']

        # CJK characters
        client.call('task_create', {
            'task_id': 'test-low-cjk',
            'subject': '中文日本語한국어 mixed',
            'description': '测试描述',
            'priority': 4
        })

        task = client.call('task_get', {'task_id': 'test-low-cjk'})
        assert '中文' in task['task']['subject']

    def test_special_characters_in_ids(self, running_daemon, client):
        """Special characters in IDs."""
        # Register agent with special chars
        special_agent = 'agent@with#special$chars'
        client.call('register', {
            'agent_id': special_agent,
            'pid': os.getpid()
        })

        # Lock file with special chars
        special_file = 'file@#$%.py'
        client.call('lock_acquire', {
            'agent_id': special_agent,
            'file_path': special_file
        })

        locks = client.call('lock_list', {'agent_id': special_agent})
        assert special_file in locks['locks']


class TestBoundaryConditions:
    """Test boundary conditions."""

    def test_zero_priority_rejected(self, running_daemon, client):
        """Priority 0 should be rejected."""
        with pytest.raises(RuntimeError):
            client.call('task_create', {
                'task_id': 'test-low-zero-priority',
                'subject': 'Zero priority test',
                'description': 'Description',
                'priority': 0
            })

    def test_priority_six_rejected(self, running_daemon, client):
        """Priority 6 should be rejected."""
        with pytest.raises(RuntimeError):
            client.call('task_create', {
                'task_id': 'test-low-six-priority',
                'subject': 'Six priority test',
                'description': 'Description',
                'priority': 6
            })

    def test_priority_boundaries(self, running_daemon, client):
        """Priority 1 and 5 should work."""
        # Priority 1 (will fail due to missing spec, but not due to priority)
        try:
            client.call('task_create', {
                'task_id': 'test-crit-boundary',
                'subject': 'Boundary test subject',
                'description': 'Valid description here',
                'priority': 1
            })
        except RuntimeError as e:
            # Should fail for spec, not priority
            assert 'priority' not in str(e).lower()

        # Priority 5 should work
        client.call('task_create', {
            'task_id': 'test-low-boundary-5',
            'subject': 'Boundary test subject',
            'description': 'Description',
            'priority': 5
        })

        task = client.call('task_get', {'task_id': 'test-low-boundary-5'})
        assert task['task']['priority'] == 5

    def test_subject_exact_10_chars(self, running_daemon, client):
        """Subject with exactly 10 chars should work."""
        subject = 'A' * 10  # Exactly 10

        client.call('task_create', {
            'task_id': 'test-low-10-char',
            'subject': subject,
            'description': 'Description',
            'priority': 4
        })

        task = client.call('task_get', {'task_id': 'test-low-10-char'})
        assert task['task']['subject'] == subject

    def test_subject_exact_100_chars(self, running_daemon, client):
        """Subject with exactly 100 chars should work."""
        subject = 'A' * 100  # Exactly 100

        client.call('task_create', {
            'task_id': 'test-low-100-char',
            'subject': subject,
            'description': 'Description',
            'priority': 4
        })

        task = client.call('task_get', {'task_id': 'test-low-100-char'})
        assert len(task['task']['subject']) == 100

    def test_subject_9_chars_rejected(self, running_daemon, client):
        """Subject with 9 chars should be rejected."""
        subject = 'A' * 9

        with pytest.raises(RuntimeError) as exc_info:
            client.call('task_create', {
                'task_id': 'test-low-9-char',
                'subject': subject,
                'description': 'Description',
                'priority': 4
            })

        assert 'length' in str(exc_info.value).lower()

    def test_subject_101_chars_rejected(self, running_daemon, client):
        """Subject with 101 chars should be rejected."""
        subject = 'A' * 101

        with pytest.raises(RuntimeError) as exc_info:
            client.call('task_create', {
                'task_id': 'test-low-101-char',
                'subject': subject,
                'description': 'Description',
                'priority': 4
            })

        assert 'length' in str(exc_info.value).lower()


class TestMemoryPressure:
    """Test behavior under memory pressure."""

    @pytest.mark.slow
    def test_large_batch_operations(self, running_daemon, client):
        """System should handle large batch operations."""
        # Create many tasks in quick succession
        start = time.time()

        for i in range(500):
            client.call('task_create', {
                'task_id': f'test-low-batch-{i:04d}',
                'subject': f'Batch task {i} subject',
                'description': f'Batch task {i} description',
                'priority': 4
            })

        elapsed = time.time() - start

        # Should complete reasonably fast
        assert elapsed < 30.0

        # Verify count
        status = client.call('status', {})
        assert status['tasks']['pending'] >= 500

    @pytest.mark.slow
    def test_large_metadata(self, running_daemon, client):
        """System should handle large metadata."""
        # Large metadata (100KB)
        large_metadata = {
            'data': 'x' * 100000,
            'nested': {
                'more': 'y' * 100000
            }
        }

        client.call('register', {
            'agent_id': 'large-metadata-agent',
            'pid': os.getpid(),
            'metadata': large_metadata
        })

        # Should work without issues
        status = client.call('status', {})
        assert status['agents'] >= 1


class TestErrorConditions:
    """Test various error conditions."""

    def test_nonexistent_task_get(self, running_daemon, client):
        """Getting nonexistent task should fail gracefully."""
        with pytest.raises(RuntimeError):
            client.call('task_get', {'task_id': 'nonexistent-task'})

    def test_unregistered_agent_operations(self, running_daemon, client):
        """Operations with unregistered agent should fail."""
        with pytest.raises(RuntimeError):
            client.call('task_claim', {
                'agent_id': 'unregistered',
                'task_id': 'some-task'
            })

    def test_double_unregister(self, running_daemon, client):
        """Unregistering twice should work or fail gracefully."""
        client.call('register', {
            'agent_id': 'double-unreg',
            'pid': os.getpid()
        })

        # First unregister
        client.call('unregister', {'agent_id': 'double-unreg'})

        # Second unregister - might succeed or fail gracefully
        try:
            client.call('unregister', {'agent_id': 'double-unreg'})
        except RuntimeError:
            pass  # Acceptable to fail

    def test_complete_task_wrong_owner(self, running_daemon, client):
        """Completing task with wrong owner should fail."""
        client.call('register', {'agent_id': 'owner', 'pid': os.getpid()})
        client.call('register', {'agent_id': 'intruder', 'pid': os.getpid() + 1})

        client.call('task_create', {
            'task_id': 'test-low-ownership',
            'subject': 'Ownership test',
            'description': 'Description',
            'priority': 4
        })

        client.call('task_claim', {
            'agent_id': 'owner',
            'task_id': 'test-low-ownership'
        })

        # Intruder tries to complete
        # This might succeed but not change state, or fail
        try:
            client.call('task_complete', {
                'agent_id': 'intruder',
                'task_id': 'test-low-ownership'
            })
        except RuntimeError:
            pass

        # Task should still be in_progress with original owner
        task = client.call('task_get', {'task_id': 'test-low-ownership'})
        # State should be consistent
        assert task['task']['owner'] == 'owner'

    def test_release_nonexistent_lock(self, running_daemon, client):
        """Releasing nonexistent lock should succeed silently."""
        client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})

        # Should not error
        result = client.call('lock_release', {
            'agent_id': 'test-agent',
            'file_path': 'nonexistent.py'
        })

        assert result['status'] == 'unlocked'
