"""
Comprehensive integration tests for coordination daemon.

Coverage:
- End-to-end workflows
- Multi-agent scenarios
- Concurrent operations
- State consistency
- Error recovery
- Performance benchmarks
"""

import json
import os
import threading
import time
import pytest

from coord_service.validator import ValidationErrors


class TestBasicWorkflow:
    """Test basic coordination workflow."""

    def test_agent_lifecycle(self, running_daemon, client):
        """Test full agent lifecycle."""
        # Register
        result = client.call('register', {
            'agent_id': 'test-agent',
            'pid': os.getpid()
        })
        assert result['status'] == 'registered'

        # Heartbeat
        result = client.call('heartbeat', {'agent_id': 'test-agent'})
        assert result['status'] == 'ok'

        # Unregister
        result = client.call('unregister', {'agent_id': 'test-agent'})
        assert result['status'] == 'unregistered'

    def test_task_workflow(self, running_daemon, client, sample_task_spec):
        """Test full task workflow."""
        # Register agent
        client.call('register', {
            'agent_id': 'test-agent',
            'pid': os.getpid()
        })

        # Create task
        result = client.call('task_create', {
            'task_id': 'test-high-example-01',
            'subject': 'Example task here',
            'description': 'Detailed description for testing',
            'priority': 2,
            'spec_path': str(sample_task_spec)
        })
        assert result['status'] == 'created'

        # Claim task
        result = client.call('task_claim', {
            'agent_id': 'test-agent',
            'task_id': 'test-high-example-01'
        })
        assert result['status'] == 'claimed'

        # Complete task
        result = client.call('task_complete', {
            'agent_id': 'test-agent',
            'task_id': 'test-high-example-01'
        })
        assert result['status'] == 'completed'

    def test_file_locking_workflow(self, running_daemon, client):
        """Test file locking workflow."""
        # Register agent
        client.call('register', {
            'agent_id': 'test-agent',
            'pid': os.getpid()
        })

        # Acquire lock
        result = client.call('lock_acquire', {
            'agent_id': 'test-agent',
            'file_path': 'test.py'
        })
        assert result['status'] == 'locked'

        # Release lock
        result = client.call('lock_release', {
            'agent_id': 'test-agent',
            'file_path': 'test.py'
        })
        assert result['status'] == 'unlocked'


class TestMultiAgentScenarios:
    """Test multi-agent coordination scenarios."""

    def test_two_agents_different_tasks(self, running_daemon, client):
        """Two agents working on different tasks."""
        # Register agents
        client.call('register', {'agent_id': 'agent1', 'pid': os.getpid()})
        client.call('register', {'agent_id': 'agent2', 'pid': os.getpid() + 1})

        # Create tasks
        client.call('task_create', {
            'task_id': 'test-low-task1',
            'subject': 'Task 1 subject',
            'description': 'Description',
            'priority': 4
        })
        client.call('task_create', {
            'task_id': 'test-low-task2',
            'subject': 'Task 2 subject',
            'description': 'Description',
            'priority': 4
        })

        # Both agents claim their tasks
        client.call('task_claim', {
            'agent_id': 'agent1',
            'task_id': 'test-low-task1'
        })
        client.call('task_claim', {
            'agent_id': 'agent2',
            'task_id': 'test-low-task2'
        })

        # Both complete
        client.call('task_complete', {
            'agent_id': 'agent1',
            'task_id': 'test-low-task1'
        })
        client.call('task_complete', {
            'agent_id': 'agent2',
            'task_id': 'test-low-task2'
        })

        # Verify status
        status = client.call('status', {})
        assert status['agents'] >= 2

    def test_two_agents_lock_conflict(self, running_daemon, client):
        """Two agents trying to lock same file."""
        # Register agents
        client.call('register', {'agent_id': 'agent1', 'pid': os.getpid()})
        client.call('register', {'agent_id': 'agent2', 'pid': os.getpid() + 1})

        # Agent1 locks file
        client.call('lock_acquire', {
            'agent_id': 'agent1',
            'file_path': 'conflict.py'
        })

        # Agent2 tries to lock same file - should fail
        with pytest.raises(RuntimeError) as exc_info:
            client.call('lock_acquire', {
                'agent_id': 'agent2',
                'file_path': 'conflict.py'
            })

        assert 'locked' in str(exc_info.value).lower()

    def test_two_agents_task_race(self, running_daemon, client):
        """Two agents racing to claim same task."""
        # Register agents
        client.call('register', {'agent_id': 'agent1', 'pid': os.getpid()})
        client.call('register', {'agent_id': 'agent2', 'pid': os.getpid() + 1})

        # Create one task
        client.call('task_create', {
            'task_id': 'test-low-race',
            'subject': 'Race task subject',
            'description': 'Description',
            'priority': 4
        })

        # Agent1 claims
        client.call('task_claim', {
            'agent_id': 'agent1',
            'task_id': 'test-low-race'
        })

        # Agent2 tries to claim - should fail
        with pytest.raises(RuntimeError) as exc_info:
            client.call('task_claim', {
                'agent_id': 'agent2',
                'task_id': 'test-low-race'
            })

        assert 'unavailable' in str(exc_info.value).lower()


class TestConcurrentOperations:
    """Test concurrent operations."""

    def test_concurrent_task_claims(self, running_daemon, client):
        """Multiple agents claiming tasks concurrently."""
        # Create 10 tasks
        for i in range(10):
            client.call('task_create', {
                'task_id': f'test-low-concurrent-{i:02d}',
                'subject': f'Task {i} subject',
                'description': 'Description',
                'priority': 4
            })

        # Register 10 agents and claim tasks concurrently
        results = []
        errors = []

        def claim_task(agent_idx):
            try:
                agent_id = f'agent-{agent_idx}'
                task_id = f'test-low-concurrent-{agent_idx:02d}'

                # Register
                client.call('register', {
                    'agent_id': agent_id,
                    'pid': os.getpid() + agent_idx
                })

                # Claim
                result = client.call('task_claim', {
                    'agent_id': agent_id,
                    'task_id': task_id
                })

                results.append((agent_id, task_id, 'success'))
            except Exception as e:
                errors.append((agent_idx, str(e)))

        threads = []
        for i in range(10):
            t = threading.Thread(target=claim_task, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All should succeed (different tasks)
        assert len(results) == 10
        assert len(errors) == 0

    def test_concurrent_file_locks(self, running_daemon, client):
        """Multiple agents locking different files concurrently."""
        # Register agents
        for i in range(10):
            client.call('register', {
                'agent_id': f'agent-{i}',
                'pid': os.getpid() + i
            })

        # Lock different files concurrently
        results = []

        def lock_file(agent_idx):
            try:
                client.call('lock_acquire', {
                    'agent_id': f'agent-{agent_idx}',
                    'file_path': f'file-{agent_idx}.py'
                })
                results.append(('success', agent_idx))
            except Exception as e:
                results.append(('error', str(e)))

        threads = []
        for i in range(10):
            t = threading.Thread(target=lock_file, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All should succeed
        successes = [r for r in results if r[0] == 'success']
        assert len(successes) == 10

    def test_concurrent_registrations(self, running_daemon, client):
        """Many agents registering concurrently."""
        results = []

        def register_agent(idx):
            try:
                client.call('register', {
                    'agent_id': f'bulk-agent-{idx}',
                    'pid': os.getpid() + idx
                })
                results.append(('success', idx))
            except Exception as e:
                results.append(('error', str(e)))

        threads = []
        for i in range(50):
            t = threading.Thread(target=register_agent, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All should succeed
        successes = [r for r in results if r[0] == 'success']
        assert len(successes) == 50


class TestStateConsistency:
    """Test state consistency under various conditions."""

    def test_task_status_consistency(self, running_daemon, client):
        """Task status should remain consistent."""
        # Create and claim task
        client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})
        client.call('task_create', {
            'task_id': 'test-low-status',
            'subject': 'Status test subject',
            'description': 'Description',
            'priority': 4
        })

        # Verify pending
        task = client.call('task_get', {'task_id': 'test-low-status'})
        assert task['task']['status'] == 'pending'

        # Claim
        client.call('task_claim', {
            'agent_id': 'test-agent',
            'task_id': 'test-low-status'
        })

        # Verify in_progress
        task = client.call('task_get', {'task_id': 'test-low-status'})
        assert task['task']['status'] == 'in_progress'
        assert task['task']['owner'] == 'test-agent'

        # Complete
        client.call('task_complete', {
            'agent_id': 'test-agent',
            'task_id': 'test-low-status'
        })

        # Verify completed
        task = client.call('task_get', {'task_id': 'test-low-status'})
        assert task['task']['status'] == 'completed'

    def test_lock_consistency(self, running_daemon, client):
        """Lock state should remain consistent."""
        client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})

        # Initially no locks
        locks = client.call('lock_list', {'agent_id': 'test-agent'})
        assert locks['locks'] == []

        # Acquire lock
        client.call('lock_acquire', {
            'agent_id': 'test-agent',
            'file_path': 'test.py'
        })

        # Verify lock exists
        locks = client.call('lock_list', {'agent_id': 'test-agent'})
        assert 'test.py' in locks['locks']

        # Release lock
        client.call('lock_release', {
            'agent_id': 'test-agent',
            'file_path': 'test.py'
        })

        # Verify lock gone
        locks = client.call('lock_list', {'agent_id': 'test-agent'})
        assert 'test.py' not in locks['locks']


class TestVelocityTracking:
    """Test velocity metrics tracking."""

    def test_velocity_after_completions(self, running_daemon, client):
        """Velocity should track completed tasks."""
        client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})

        # Complete 5 tasks
        for i in range(5):
            task_id = f'test-low-velocity-{i:02d}'
            client.call('task_create', {
                'task_id': task_id,
                'subject': f'Velocity test {i}',
                'description': 'Description',
                'priority': 4
            })
            client.call('task_claim', {
                'agent_id': 'test-agent',
                'task_id': task_id
            })
            client.call('task_complete', {
                'agent_id': 'test-agent',
                'task_id': task_id
            })

        # Get velocity
        velocity = client.call('velocity', {'period': '1 hour'})

        assert velocity['completed_tasks'] >= 5
        assert velocity['tasks_per_hour'] > 0

    def test_file_hotspots_tracking(self, running_daemon, client):
        """File hotspots should track lock frequency."""
        client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})

        # Lock and unlock file multiple times
        for i in range(5):
            client.call('lock_acquire', {
                'agent_id': 'test-agent',
                'file_path': 'hotspot.py'
            })
            client.call('lock_release', {
                'agent_id': 'test-agent',
                'file_path': 'hotspot.py'
            })

        # Get hotspots
        hotspots = client.call('file_hotspots', {'limit': 10})

        # Should have hotspot.py
        hotspot_files = [h['file_path'] for h in hotspots['hotspots']]
        assert 'hotspot.py' in hotspot_files

    def test_task_timing_tracking(self, running_daemon, client):
        """Task timing should track duration."""
        client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})

        # Create and complete task with some delay
        client.call('task_create', {
            'task_id': 'test-low-timing',
            'subject': 'Timing test subject',
            'description': 'Description',
            'priority': 4
        })

        time.sleep(0.1)  # Wait time

        client.call('task_claim', {
            'agent_id': 'test-agent',
            'task_id': 'test-low-timing'
        })

        time.sleep(0.1)  # Work time

        # Lock a file
        client.call('lock_acquire', {
            'agent_id': 'test-agent',
            'file_path': 'work.py'
        })

        time.sleep(0.1)  # Active time

        client.call('lock_release', {
            'agent_id': 'test-agent',
            'file_path': 'work.py'
        })

        client.call('task_complete', {
            'agent_id': 'test-agent',
            'task_id': 'test-low-timing'
        })

        # Get timing
        timing = client.call('task_timing', {'task_id': 'test-low-timing'})

        assert timing['timing']['created_at'] is not None
        assert timing['timing']['claimed_at'] is not None
        assert timing['timing']['completed_at'] is not None


class TestStateExportImport:
    """Test state export and import."""

    def test_export_state(self, running_daemon, client, temp_dir):
        """Export state to JSON."""
        # Setup state
        client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})
        client.call('task_create', {
            'task_id': 'test-low-export',
            'subject': 'Export test subject',
            'description': 'Description',
            'priority': 4
        })

        # Export
        export_path = os.path.join(temp_dir, 'export-test.json')
        result = client.call('export_json', {'output_path': export_path})

        assert result['status'] == 'exported'
        assert os.path.exists(export_path)

        # Verify content
        with open(export_path) as f:
            state = json.load(f)

        assert 'agents' in state
        assert 'tasks' in state
        assert 'test-agent' in state['agents']
        assert 'test-low-export' in state['tasks']

    def test_import_state(self, running_daemon, client, temp_dir):
        """Import state from JSON."""
        # Create state file
        state = {
            'agents': {
                'imported-agent': {
                    'pid': 99999,
                    'registered_at': '2026-01-31 10:00:00',
                    'last_heartbeat': '2026-01-31 10:00:00'
                }
            },
            'tasks': {
                'test-low-import': {
                    'subject': 'Imported task',
                    'description': 'Description',
                    'priority': 4,
                    'status': 'pending',
                    'owner': None,
                    'created_at': '2026-01-31 10:00:00',
                    'started_at': None,
                    'completed_at': None
                }
            },
            'locks': {}
        }

        import_path = os.path.join(temp_dir, 'import-test.json')
        with open(import_path, 'w') as f:
            json.dump(state, f)

        # Import
        result = client.call('import_json', {'json_path': import_path})
        assert result['status'] == 'imported'

        # Verify imported data
        task = client.call('task_get', {'task_id': 'test-low-import'})
        assert task['task']['subject'] == 'Imported task'


class TestErrorRecovery:
    """Test error handling and recovery."""

    def test_invalid_operation_doesnt_corrupt_state(self, running_daemon, client):
        """Invalid operations should not corrupt state."""
        # Create valid state
        client.call('register', {'agent_id': 'test-agent', 'pid': os.getpid()})
        client.call('task_create', {
            'task_id': 'test-low-valid',
            'subject': 'Valid task subject',
            'description': 'Description',
            'priority': 4
        })

        # Try invalid operation
        try:
            client.call('task_claim', {
                'agent_id': 'nonexistent-agent',
                'task_id': 'test-low-valid'
            })
        except:
            pass  # Expected to fail

        # State should still be valid
        task = client.call('task_get', {'task_id': 'test-low-valid'})
        assert task['task']['status'] == 'pending'  # Not corrupted

    def test_validation_error_provides_hints(self, running_daemon, client):
        """Validation errors should provide helpful hints."""
        try:
            client.call('task_create', {
                'task_id': 'InvalidTask',
                'subject': 'Test',
                'description': 'Desc',
                'priority': 1
            })
        except RuntimeError as e:
            error_msg = str(e)
            # Should mention validation and provide hint
            assert 'validation' in error_msg.lower() or 'invalid' in error_msg.lower()


class TestPerformance:
    """Test performance characteristics."""

    def test_task_creation_performance(self, running_daemon, client):
        """Task creation should be fast."""
        start = time.time()

        for i in range(100):
            client.call('task_create', {
                'task_id': f'test-low-perf-{i:03d}',
                'subject': f'Performance test {i}',
                'description': 'Description',
                'priority': 4
            })

        elapsed = time.time() - start

        # Should complete 100 tasks in reasonable time (<10s)
        assert elapsed < 10.0

        # Average <100ms per task
        avg = elapsed / 100
        assert avg < 0.1

    def test_concurrent_performance(self, running_daemon, client):
        """Concurrent operations should scale."""
        # Register agents
        for i in range(10):
            client.call('register', {
                'agent_id': f'perf-agent-{i}',
                'pid': os.getpid() + i
            })

        # Create tasks
        for i in range(50):
            client.call('task_create', {
                'task_id': f'test-low-concurrent-perf-{i:02d}',
                'subject': f'Concurrent perf {i}',
                'description': 'Description',
                'priority': 4
            })

        # Claim and complete concurrently
        start = time.time()

        def claim_and_complete(agent_idx, task_idx):
            client.call('task_claim', {
                'agent_id': f'perf-agent-{agent_idx}',
                'task_id': f'test-low-concurrent-perf-{task_idx:02d}'
            })
            client.call('task_complete', {
                'agent_id': f'perf-agent-{agent_idx}',
                'task_id': f'test-low-concurrent-perf-{task_idx:02d}'
            })

        threads = []
        for i in range(50):
            agent_idx = i % 10
            t = threading.Thread(target=claim_and_complete, args=(agent_idx, i))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        elapsed = time.time() - start

        # Should handle 50 concurrent operations reasonably fast (<5s)
        assert elapsed < 5.0


class TestServiceStatus:
    """Test service status reporting."""

    def test_status_reflects_current_state(self, running_daemon, client):
        """Status should reflect current state."""
        # Initial status
        status = client.call('status', {})
        initial_agents = status['agents']

        # Register agent
        client.call('register', {'agent_id': 'status-agent', 'pid': os.getpid()})

        # Status should update
        status = client.call('status', {})
        assert status['agents'] == initial_agents + 1

        # Create tasks
        client.call('task_create', {
            'task_id': 'test-low-status-1',
            'subject': 'Status test 1',
            'description': 'Description',
            'priority': 4
        })
        client.call('task_create', {
            'task_id': 'test-low-status-2',
            'subject': 'Status test 2',
            'description': 'Description',
            'priority': 4
        })

        status = client.call('status', {})
        assert status['tasks']['pending'] >= 2

        # Claim one
        client.call('task_claim', {
            'agent_id': 'status-agent',
            'task_id': 'test-low-status-1'
        })

        status = client.call('status', {})
        assert status['tasks']['in_progress'] >= 1
