# Task: m2-07-console-streaming - Implement real-time streaming console updates

**Priority:** HIGH
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Update the Rich console visualizer from M1 to support real-time streaming updates. As the workflow executes, the console should update live showing progress, not just display after completion.

---

## Files to Modify

- `src/observability/console.py` - Add live streaming support

---

## Files to Create

- `tests/test_observability/test_console_streaming.py` - Streaming tests

---

## Acceptance Criteria

### Streaming Updates
- [ ] Use Rich's Live() for real-time updates
- [ ] Update tree as execution progresses
- [ ] Show running status with spinners
- [ ] Update durations in real-time
- [ ] Show completed nodes with checkmarks
- [ ] Show failed nodes with X marks

### Display Features
- [ ] Workflow starts → show "Workflow: name (running) ⏳"
- [ ] Stage starts → add stage node with spinner
- [ ] Agent starts → add agent node with spinner
- [ ] LLM call starts → show "LLM: model (calling...)"
- [ ] LLM call completes → update with duration + tokens
- [ ] Tool call executes → show tool node
- [ ] Agent completes → update with final status
- [ ] Stage completes → update with metrics
- [ ] Workflow completes → show final summary

### Testing
- [ ] Test streaming updates with mock execution
- [ ] Test all status transitions
- [ ] Coverage > 80%

---

## Implementation

```python
"""Real-time console streaming."""
from rich.live import Live
from threading import Thread, Event
import time


class StreamingVisualizer:
    """Visualizes execution in real-time."""

    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self.stop_event = Event()
        self.live = Live(refresh_per_second=4)

    def start(self):
        """Start streaming updates."""
        self.live.start()
        self.update_thread = Thread(target=self._update_loop)
        self.update_thread.start()

    def stop(self):
        """Stop streaming."""
        self.stop_event.set()
        self.update_thread.join()
        self.live.stop()

    def _update_loop(self):
        """Poll database and update display."""
        while not self.stop_event.is_set():
            # Query latest execution state from DB
            with get_session() as session:
                workflow = session.query(WorkflowExecution).filter_by(
                    id=self.workflow_id
                ).first()

            # Update display
            if workflow:
                tree = self._create_workflow_tree(workflow)
                self.live.update(tree)

            time.sleep(0.25)  # Poll every 250ms
```

---

## Success Metrics

- [ ] Console updates in real-time as workflow runs
- [ ] All status transitions display correctly
- [ ] Spinners show for running tasks
- [ ] Tests pass > 80%

---

## Dependencies

- **Blocked by:** m2-06-obs-hooks (needs data in database), m1-02-observability-console (extends it)
- **Blocks:** m2-08-e2e-execution
- **Works with:** m2-06-obs-hooks (reads data it writes)

---

## Notes

- Poll database every 250ms for updates
- Use Rich's Live() context manager
- Keep performance in mind - don't query too frequently
- Consider event-based updates later (M3+)
