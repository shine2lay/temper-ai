# Task: gap-m3-01-track-collab-event - Implement missing track_collaboration_event() method in ExecutionTracker

**Priority:** CRITICAL (P0 - Blocking M3 completion)
**Effort:** 4-6 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

The `track_collaboration_event()` method is called by parallel.py and adaptive.py executors but does not exist in ExecutionTracker, causing silent failures in collaboration tracking. The CollaborationEvent database table schema exists but receives no data because the tracking method is missing.

**Impact:** Cannot debug multi-agent collaboration, orphaned database schema, silent tracking failures.

---

## Files to Create

_None_ - Adding method to existing files

---

## Files to Modify

- `src/observability/tracker.py` - Add track_collaboration_event() method after track_safety_violation()
- `src/observability/backend.py` - Add track_collaboration_event() method to ObservabilityBackend interface
- `src/observability/backends/sql_backend.py` - Implement SQL backend tracking for collaboration events

---

## Acceptance Criteria

### Core Functionality
- [ ] Method signature matches executor calls: `track_collaboration_event(stage_id, event_type, agents_involved, event_data, round_number, resolution_strategy, outcome, confidence_score, extra_metadata)`
- [ ] Returns collaboration event ID (str) for tracking
- [ ] Creates record in CollaborationEvent table with all fields populated
- [ ] Handles all event types: vote, conflict, resolution, consensus, debate_round
- [ ] Integrates with ExecutionContext for workflow/stage tracking
- [ ] Handles optional parameters correctly (round_number, resolution_strategy, outcome, confidence_score, extra_metadata)
- [ ] Uses utcnow() for timestamp consistency
- [ ] Defensive parameter validation (event_type, agents_involved non-empty)

### Backend Integration
- [ ] Add method to ObservabilityBackend ABC interface
- [ ] Implement in SQLObservabilityBackend using SQLModel
- [ ] Support batch writes if buffer is enabled
- [ ] Handle database connection errors gracefully
- [ ] Log tracking failures without breaking workflow execution

### Testing
- [ ] Unit tests for ExecutionTracker.track_collaboration_event()
- [ ] Tests cover all event types (vote, conflict, resolution, consensus, debate_round)
- [ ] Tests verify CollaborationEvent record creation
- [ ] Tests verify optional parameters (None handling)
- [ ] Tests verify foreign key relationships (stage_execution_id)
- [ ] Integration test: verify executor calls succeed (parallel.py:113,124, adaptive.py:85,167)
- [ ] Verify database writes occur correctly
- [ ] Test error handling (invalid stage_id, database errors)

### Code Quality
- [ ] Follow existing pattern from track_safety_violation()
- [ ] Comprehensive docstring with example usage
- [ ] Type hints for all parameters and return value
- [ ] Consistent with other tracking methods

---

## Implementation Details

**Method Location:** Add after `track_safety_violation()` at line 713 in tracker.py

**Method Signature:**
```python
def track_collaboration_event(
    self,
    stage_id: str,
    event_type: str,
    agents_involved: List[str],
    event_data: Optional[Dict[str, Any]] = None,
    round_number: Optional[int] = None,
    resolution_strategy: Optional[str] = None,
    outcome: Optional[str] = None,
    confidence_score: Optional[float] = None,
    extra_metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Track collaboration event for multi-agent interactions.

    Records collaboration events such as voting, conflicts, resolutions,
    consensus building, and debate rounds for analysis and monitoring.

    Args:
        stage_id: ID of the stage where collaboration occurred
        event_type: Type of event (vote, conflict, resolution, consensus, debate_round)
        agents_involved: List of agent IDs participating
        event_data: Event-specific data (votes, positions, arguments)
        round_number: Round number for multi-round collaborations
        resolution_strategy: Strategy used for conflict resolution
        outcome: Final outcome of the collaboration event
        confidence_score: Confidence score of outcome (0.0-1.0)
        extra_metadata: Additional metadata for custom tracking

    Returns:
        str: ID of created collaboration event record

    Example:
        >>> tracker.track_collaboration_event(
        ...     stage_id="stage-123",
        ...     event_type="vote",
        ...     agents_involved=["agent-1", "agent-2", "agent-3"],
        ...     event_data={"votes": {"option_a": 2, "option_b": 1}},
        ...     resolution_strategy="consensus",
        ...     outcome="option_a",
        ...     confidence_score=0.85
        ... )
        'collab-event-456'
    """
    return self.backend.track_collaboration_event(
        stage_id=stage_id,
        event_type=event_type,
        agents_involved=agents_involved,
        event_data=event_data,
        round_number=round_number,
        resolution_strategy=resolution_strategy,
        outcome=outcome,
        confidence_score=confidence_score,
        extra_metadata=extra_metadata,
        timestamp=utcnow()
    )
```

**Backend Method** (ObservabilityBackend):
```python
@abstractmethod
def track_collaboration_event(
    self,
    stage_id: str,
    event_type: str,
    agents_involved: List[str],
    event_data: Optional[Dict[str, Any]] = None,
    round_number: Optional[int] = None,
    resolution_strategy: Optional[str] = None,
    outcome: Optional[str] = None,
    confidence_score: Optional[float] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    timestamp: datetime = None
) -> str:
    """Track collaboration event to backend."""
    pass
```

**SQL Backend Implementation:**
```python
def track_collaboration_event(
    self,
    stage_id: str,
    event_type: str,
    agents_involved: List[str],
    event_data: Optional[Dict[str, Any]] = None,
    round_number: Optional[int] = None,
    resolution_strategy: Optional[str] = None,
    outcome: Optional[str] = None,
    confidence_score: Optional[float] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    timestamp: datetime = None
) -> str:
    """Track collaboration event to SQL database."""
    event_id = f"collab-{uuid.uuid4().hex[:12]}"

    event = CollaborationEvent(
        id=event_id,
        stage_execution_id=stage_id,
        event_type=event_type,
        timestamp=timestamp or utcnow(),
        round_number=round_number,
        agents_involved=agents_involved,
        event_data=event_data,
        resolution_strategy=resolution_strategy,
        outcome=outcome,
        confidence_score=confidence_score,
        extra_metadata=extra_metadata
    )

    self.session.add(event)
    self.session.commit()

    return event_id
```

---

## Test Strategy

**Unit Tests** (`tests/test_observability/test_tracker.py`):
- Test method exists and callable
- Test with all event types
- Test with optional parameters (None values)
- Test return value (event ID format)
- Test backend integration (mock backend)

**Integration Tests** (`tests/integration/test_m3_multi_agent.py`):
- Verify executor calls succeed (remove hasattr defensive checks if needed)
- Verify database records created
- Verify foreign key relationships
- End-to-end: collaboration → tracking → database → query

**Edge Cases**:
- Empty agents_involved list (should validate)
- Invalid event_type (should validate or pass through)
- Very long event_data (JSON limits)
- Database connection failures (graceful degradation)

---

## Success Metrics

- [ ] Method implemented in tracker.py, backend.py, sql_backend.py
- [ ] All unit tests pass (10+ tests)
- [ ] Integration test verifies executor calls succeed
- [ ] CollaborationEvent table receives data during M3 workflows
- [ ] No silent failures (remove hasattr defensive checks in executors)
- [ ] Performance: <5ms tracking overhead per event
- [ ] Code review approved

---

## Dependencies

- **Blocked by:** _None_ (can start immediately)
- **Blocks:** gap-m3-03-quality-gates-retry, gap-m3-05-enable-e2e-tests (observability needed for testing)
- **Integrates with:**
  - src/compiler/executors/parallel.py (calls at lines 113, 124)
  - src/compiler/executors/adaptive.py (calls at lines 85, 167)
  - src/observability/models.py (CollaborationEvent model)

---

## Design References

- Gap Analysis Report: `.claude-coord/reports/milestone-gaps-20260130-173000.md` (M3 section)
- Agent a4b6163 Audit Output: Critical gap identified in M3 observability tracking
- CollaborationEvent Model: `src/observability/models.py:255-283`
- Existing Pattern: `track_safety_violation()` in tracker.py:668-713

---

## Notes

**CRITICAL:** This is the #1 blocking issue for M3 production deployment. Silent failures are occurring right now in parallel and adaptive executors.

**Defensive Code to Remove:** After implementing this method, consider removing `hasattr()` checks in executors:
- `parallel.py:113, 124` - Currently fails silently if method missing
- `adaptive.py:85, 167` - Currently fails silently if method missing

**Database Schema Already Exists:** The CollaborationEvent table is fully defined and ready to receive data. This task just adds the missing tracking method.

**Performance Consideration:** Collaboration events can be frequent in multi-agent workflows. Consider batch writing if performance becomes an issue (use observability buffer).
