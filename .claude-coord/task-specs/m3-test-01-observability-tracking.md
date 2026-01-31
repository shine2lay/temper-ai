# Task: Implement track_collaboration_event() Method and Tests

**Task ID:** m3-test-01  
**Priority:** P0 (Critical - Blocking Production)  
**Milestone:** M3 - Multi-Agent Collaboration  
**Type:** Implementation + Testing  
**Estimated Effort:** 4-6 hours

---

## Problem Statement

The `track_collaboration_event()` method is missing from the observability system, causing all multi-agent collaboration events to silently fail. The database schema exists but receives no writes.

**Impact:** Cannot debug multi-agent workflows, observability claims are incorrect.

**Evidence:**
- Database schema exists: `src/observability/models.py:255-283` (CollaborationEvent table)
- Executor calls fail silently: `src/compiler/executors/parallel.py:113,124` (with defensive hasattr checks)
- Adaptive executor calls fail: `src/compiler/executors/adaptive.py:85,167`
- Method does NOT exist in `src/observability/tracker.py` (713 lines, no such method)

---

## Acceptance Criteria

### Implementation
- [ ] Add `track_collaboration_event()` method to `ExecutionTracker` class
- [ ] Add abstract method to `ObservabilityBackend` interface
- [ ] Implement method in `SQLObservabilityBackend`
- [ ] Method signature matches executor expectations:
  ```python
  def track_collaboration_event(
      self,
      event_type: str,  # "parallel_start", "parallel_end", "synthesis", "convergence", "conflict"
      stage_id: int,
      agents_involved: List[str],
      event_data: Dict[str, Any],
      outcome: Optional[str] = None,
      confidence_score: Optional[float] = None
  ) -> None
  ```
- [ ] Events are written to `collaboration_events` table
- [ ] Foreign key relationship to `stage_executions` table maintained

### Testing
- [ ] Unit test: `track_collaboration_event()` writes to database
- [ ] Unit test: Event types validated (parallel_start, parallel_end, synthesis, convergence, conflict)
- [ ] Unit test: Stage ID foreign key constraint enforced
- [ ] Unit test: Agent names stored correctly
- [ ] Unit test: Event metadata serialized to JSON
- [ ] Integration test: Parallel execution writes collaboration events
- [ ] Integration test: Synthesis writes collaboration event
- [ ] Integration test: Convergence detection writes event
- [ ] Integration test: Query collaboration events by stage_id
- [ ] Integration test: Query collaboration events by event_type

### Verification
- [ ] Remove defensive `hasattr()` checks from executors (no longer needed)
- [ ] Run parallel execution workflow and verify events in database
- [ ] Run debate workflow and verify convergence events
- [ ] Check observability dashboard shows collaboration events

---

## Implementation Plan

### Step 1: Add Abstract Method to Backend Interface (30 min)
**File:** `src/observability/backend.py`

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class ObservabilityBackend(ABC):
    # ... existing methods ...
    
    @abstractmethod
    def track_collaboration_event(
        self,
        event_type: str,
        stage_id: int,
        agents_involved: List[str],
        event_data: Dict[str, Any],
        outcome: Optional[str] = None,
        confidence_score: Optional[float] = None
    ) -> None:
        """Track a multi-agent collaboration event.
        
        Args:
            event_type: Type of collaboration event (parallel_start, parallel_end, 
                       synthesis, convergence, conflict)
            stage_id: ID of the stage execution
            agents_involved: List of agent names participating
            event_data: Event-specific metadata (strategy used, votes, etc.)
            outcome: Optional outcome description
            confidence_score: Optional confidence score (0-1)
        """
        pass
```

### Step 2: Implement in SQLObservabilityBackend (1-2 hours)
**File:** `src/observability/backend.py` (or wherever SQL backend is implemented)

```python
import json
from datetime import datetime

def track_collaboration_event(
    self,
    event_type: str,
    stage_id: int,
    agents_involved: List[str],
    event_data: Dict[str, Any],
    outcome: Optional[str] = None,
    confidence_score: Optional[float] = None
) -> None:
    """Implementation for SQL backend."""
    from src.observability.models import CollaborationEvent
    
    # Validate event type
    valid_types = ["parallel_start", "parallel_end", "synthesis", "convergence", "conflict"]
    if event_type not in valid_types:
        raise ValueError(f"Invalid event_type: {event_type}. Must be one of {valid_types}")
    
    # Validate confidence score if provided
    if confidence_score is not None and not (0.0 <= confidence_score <= 1.0):
        raise ValueError(f"confidence_score must be between 0 and 1, got {confidence_score}")
    
    # Create event record
    event = CollaborationEvent(
        event_type=event_type,
        stage_id=stage_id,
        agents_involved=agents_involved,  # Already List[str], will serialize to JSON
        event_data=event_data,  # Dict, will serialize to JSON
        outcome=outcome,
        confidence_score=confidence_score,
        created_at=datetime.utcnow()
    )
    
    # Write to database
    with self.session_scope() as session:
        session.add(event)
        session.commit()
```

### Step 3: Add Method to ExecutionTracker (30 min)
**File:** `src/observability/tracker.py`

```python
def track_collaboration_event(
    self,
    event_type: str,
    stage_id: int,
    agents_involved: List[str],
    event_data: Dict[str, Any],
    outcome: Optional[str] = None,
    confidence_score: Optional[float] = None
) -> None:
    """Track a multi-agent collaboration event.
    
    Delegates to backend implementation.
    """
    if self.backend is None:
        return  # No backend configured, skip tracking
    
    self.backend.track_collaboration_event(
        event_type=event_type,
        stage_id=stage_id,
        agents_involved=agents_involved,
        event_data=event_data,
        outcome=outcome,
        confidence_score=confidence_score
    )
```

### Step 4: Remove Defensive Checks from Executors (15 min)
**File:** `src/compiler/executors/parallel.py`

Remove `hasattr()` checks at lines 113, 124:
```python
# OLD (lines 113-118):
if hasattr(self.tracker, "track_collaboration_event"):
    self.tracker.track_collaboration_event(...)

# NEW:
self.tracker.track_collaboration_event(...)
```

**File:** `src/compiler/executors/adaptive.py`
Remove `hasattr()` checks at lines 85, 167.

### Step 5: Write Unit Tests (1-2 hours)
**File:** `tests/test_observability/test_collaboration_tracking.py` (new file)

```python
import pytest
from src.observability.tracker import ExecutionTracker
from src.observability.backend import SQLObservabilityBackend
from src.observability.models import CollaborationEvent

class TestCollaborationEventTracking:
    
    def test_track_parallel_start_event(self, db_session):
        """Test tracking parallel execution start event."""
        tracker = ExecutionTracker(backend=SQLObservabilityBackend(session=db_session))
        
        # Create workflow and stage for foreign key
        workflow_id = tracker.start_workflow("test_workflow", {})
        stage_id = tracker.start_stage(workflow_id, "parallel_stage", {})
        
        # Track collaboration event
        tracker.track_collaboration_event(
            event_type="parallel_start",
            stage_id=stage_id,
            agents_involved=["agent1", "agent2", "agent3"],
            event_data={"max_concurrent": 3, "strategy": "consensus"}
        )
        
        # Verify event written to database
        events = db_session.query(CollaborationEvent).filter_by(
            stage_id=stage_id,
            event_type="parallel_start"
        ).all()
        
        assert len(events) == 1
        assert events[0].agents_involved == ["agent1", "agent2", "agent3"]
        assert events[0].event_data["strategy"] == "consensus"
    
    def test_track_synthesis_event_with_confidence(self, db_session):
        """Test tracking synthesis event with confidence score."""
        tracker = ExecutionTracker(backend=SQLObservabilityBackend(session=db_session))
        
        workflow_id = tracker.start_workflow("test_workflow", {})
        stage_id = tracker.start_stage(workflow_id, "synthesis_stage", {})
        
        tracker.track_collaboration_event(
            event_type="synthesis",
            stage_id=stage_id,
            agents_involved=["agent1", "agent2"],
            event_data={
                "method": "consensus",
                "votes": {"option_a": 2},
                "conflicts": 0
            },
            outcome="option_a",
            confidence_score=0.85
        )
        
        events = db_session.query(CollaborationEvent).filter_by(
            event_type="synthesis"
        ).all()
        
        assert len(events) == 1
        assert events[0].outcome == "option_a"
        assert events[0].confidence_score == 0.85
        assert events[0].event_data["method"] == "consensus"
    
    def test_invalid_event_type_raises_error(self, db_session):
        """Test that invalid event type raises ValueError."""
        tracker = ExecutionTracker(backend=SQLObservabilityBackend(session=db_session))
        
        workflow_id = tracker.start_workflow("test_workflow", {})
        stage_id = tracker.start_stage(workflow_id, "test_stage", {})
        
        with pytest.raises(ValueError, match="Invalid event_type"):
            tracker.track_collaboration_event(
                event_type="invalid_type",
                stage_id=stage_id,
                agents_involved=["agent1"],
                event_data={}
            )
    
    def test_invalid_confidence_score_raises_error(self, db_session):
        """Test that confidence score outside [0,1] raises ValueError."""
        tracker = ExecutionTracker(backend=SQLObservabilityBackend(session=db_session))
        
        workflow_id = tracker.start_workflow("test_workflow", {})
        stage_id = tracker.start_stage(workflow_id, "test_stage", {})
        
        with pytest.raises(ValueError, match="confidence_score must be between 0 and 1"):
            tracker.track_collaboration_event(
                event_type="synthesis",
                stage_id=stage_id,
                agents_involved=["agent1"],
                event_data={},
                confidence_score=1.5
            )
    
    def test_foreign_key_constraint_enforced(self, db_session):
        """Test that invalid stage_id raises foreign key error."""
        tracker = ExecutionTracker(backend=SQLObservabilityBackend(session=db_session))
        
        # Use non-existent stage_id
        with pytest.raises(Exception):  # IntegrityError or similar
            tracker.track_collaboration_event(
                event_type="parallel_start",
                stage_id=99999,  # Doesn't exist
                agents_involved=["agent1"],
                event_data={}
            )
    
    def test_query_events_by_stage(self, db_session):
        """Test querying collaboration events by stage."""
        tracker = ExecutionTracker(backend=SQLObservabilityBackend(session=db_session))
        
        workflow_id = tracker.start_workflow("test_workflow", {})
        stage1_id = tracker.start_stage(workflow_id, "stage1", {})
        stage2_id = tracker.start_stage(workflow_id, "stage2", {})
        
        # Track events for both stages
        tracker.track_collaboration_event("parallel_start", stage1_id, ["a1"], {})
        tracker.track_collaboration_event("synthesis", stage1_id, ["a1"], {})
        tracker.track_collaboration_event("parallel_start", stage2_id, ["a2"], {})
        
        # Query by stage
        stage1_events = db_session.query(CollaborationEvent).filter_by(
            stage_id=stage1_id
        ).all()
        
        assert len(stage1_events) == 2
        assert all(e.stage_id == stage1_id for e in stage1_events)
```

### Step 6: Write Integration Tests (1-2 hours)
**File:** `tests/integration/test_m3_collaboration_tracking.py` (new file)

```python
import pytest
from src.compiler.langgraph_compiler import LangGraphCompiler
from src.observability.tracker import ExecutionTracker
from src.observability.models import CollaborationEvent

class TestM3CollaborationTracking:
    
    def test_parallel_execution_writes_events(self, db_session, tmp_path):
        """Test that parallel execution writes collaboration events."""
        # Create workflow config with parallel execution
        workflow_config = create_parallel_workflow_config()
        
        # Execute workflow with observability
        compiler = LangGraphCompiler(observability_tracker=ExecutionTracker(db_session))
        result = compiler.compile_and_run(workflow_config)
        
        # Verify collaboration events written
        events = db_session.query(CollaborationEvent).all()
        
        assert len(events) >= 2  # At least parallel_start and parallel_end
        assert any(e.event_type == "parallel_start" for e in events)
        assert any(e.event_type == "parallel_end" for e in events)
    
    def test_synthesis_writes_event(self, db_session):
        """Test that synthesis writes collaboration event."""
        # Create workflow with synthesis
        workflow_config = create_consensus_workflow_config()
        
        compiler = LangGraphCompiler(observability_tracker=ExecutionTracker(db_session))
        result = compiler.compile_and_run(workflow_config)
        
        # Verify synthesis event
        synthesis_events = db_session.query(CollaborationEvent).filter_by(
            event_type="synthesis"
        ).all()
        
        assert len(synthesis_events) >= 1
        assert synthesis_events[0].event_data is not None
        assert "method" in synthesis_events[0].event_data
    
    def test_convergence_detection_writes_event(self, db_session):
        """Test that convergence detection writes event."""
        # Create workflow with debate strategy
        workflow_config = create_debate_workflow_config()
        
        compiler = LangGraphCompiler(observability_tracker=ExecutionTracker(db_session))
        result = compiler.compile_and_run(workflow_config)
        
        # Verify convergence event
        convergence_events = db_session.query(CollaborationEvent).filter_by(
            event_type="convergence"
        ).all()
        
        # May or may not converge, so just verify schema if event exists
        if convergence_events:
            assert convergence_events[0].confidence_score is not None
```

---

## Test Execution

### Run Unit Tests
```bash
pytest tests/test_observability/test_collaboration_tracking.py -v
```

**Expected:** All tests pass (10/10)

### Run Integration Tests
```bash
pytest tests/integration/test_m3_collaboration_tracking.py -v
```

**Expected:** All tests pass (3/3)

### Manual Verification
```bash
# Run example workflow
python examples/run_multi_agent_workflow.py parallel-research

# Query database to verify events
sqlite3 observability.db "SELECT * FROM collaboration_events;"
```

**Expected:** See collaboration events in database

---

## Files to Modify

1. **src/observability/backend.py** - Add abstract method and SQL implementation
2. **src/observability/tracker.py** - Add delegation method
3. **src/compiler/executors/parallel.py** - Remove defensive hasattr checks
4. **src/compiler/executors/adaptive.py** - Remove defensive hasattr checks
5. **tests/test_observability/test_collaboration_tracking.py** - New unit tests
6. **tests/integration/test_m3_collaboration_tracking.py** - New integration tests

---

## Success Criteria

- [ ] All 10 unit tests pass
- [ ] All 3 integration tests pass
- [ ] Manual workflow execution writes events to database
- [ ] No more defensive `hasattr()` checks needed
- [ ] Observability claims in M3 completion report are accurate

---

## Dependencies

None - this is a standalone implementation task.

---

## Related Tasks

- m3-test-02: Fix example workflow import (depends on this for full demo)
- m3-test-05: Enable E2E integration tests (will use collaboration events)

---

**Created:** 2026-01-29  
**Updated:** 2026-01-29  
**Status:** Ready for Implementation
