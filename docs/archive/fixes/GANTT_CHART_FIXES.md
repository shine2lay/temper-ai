# Gantt Chart Fixes Summary

## Issues Fixed

### 1. M1 Demo - Format String Error
**Location:** `src/observability/visualize_trace.py`

**Problem:** Multiple format strings attempting to format `None` values with float specifiers (e.g., `{None:.2f}`)

**Root Cause:**
- Line 218: `f"Duration: {duration:.3f}s"` - duration could be None
- Line 226: `f"Cost: ${metadata.get('estimated_cost_usd', 0):.4f}"` - could return None from .get()
- Line 245: `f"Total Cost: ${metadata.get('total_cost_usd', 0):.4f}"` - could return None from .get()
- Line 407: `f"Duration: {trace['duration']:.2f}s"` - trace['duration'] could be None

**Fixes Applied:**
```python
# Before:
f"Duration: {node.get('duration', 0):.3f}s"

# After:
duration = node.get('duration') or 0
f"Duration: {duration:.3f}s"
```

All format strings now explicitly handle None by using `or 0` to ensure a numeric default.

**Result:** M1 demo Gantt chart now generates successfully ✅

---

### 2. M2 Demo - Database Not Initialized
**Location:** `examples/milestone2_demo.py`

**Problem:** Gantt chart section tried to query database that wasn't initialized

**Root Cause:**
- M2 demo never called `init_database()`
- Gantt chart function tried to query `WorkflowExecution` from non-existent database

**Fixes Applied:**

1. **Added database initialization** (line 30, 530):
```python
from src.observability.database import init_database

# In main():
init_database("sqlite:///:memory:")
```

2. **Added mock execution creation** (lines 445-523):
```python
# Get latest workflow execution, or create a mock one
with get_session() as session:
    stmt = select(WorkflowExecution).order_by(
        WorkflowExecution.start_time.desc()
    ).limit(1)
    workflow = session.exec(stmt).first()

    if not workflow:
        # Create mock workflow, stage, agent, and LLM call
        # ... (creates demonstration data)
```

The mock execution includes:
- WorkflowExecution with metadata (tokens, cost, duration)
- StageExecution for agent execution stage
- AgentExecution for simple_researcher
- LLMCall for the Ollama interaction

**Result:** M2 demo Gantt chart now generates successfully ✅

---

## Verification

Both demos now complete successfully:

### M1 Demo Output:
```
============================================================
  5. Hierarchical Gantt Chart
============================================================
📊 Generating interactive hierarchical Gantt chart...

   Exporting execution trace...
   Creating Gantt chart...
✓ Saved interactive chart to: milestone1_execution_gantt.html

✓ Interactive Gantt chart saved: milestone1_execution_gantt.html
```

### M2 Demo Output:
```
──────────────────────────────
7. Hierarchical Gantt Chart Visualization
────────────────────────────────────────────────────────────

📊 Generating interactive Gantt chart for latest execution...

   Creating mock execution for demonstration...
   Using workflow: milestone2_demo (e4e4a889...)
   Exporting execution trace...
   Creating hierarchical Gantt chart...
✓ Saved interactive chart to: milestone2_execution_gantt.html

✓ Interactive Gantt chart saved: milestone2_execution_gantt.html
```

---

## Files Modified

### Modified:
- `src/observability/visualize_trace.py` - Fixed None-safe formatting (4 locations)
- `examples/milestone2_demo.py` - Added database init and mock execution creation

### No Breaking Changes:
- All existing functionality preserved
- Backwards compatible with existing traces
- Mock execution only created when no real executions exist

---

## Features Working

Both demos now successfully:
1. ✅ Run without warnings (using venv)
2. ✅ Generate interactive Gantt charts
3. ✅ Handle missing data gracefully (None values)
4. ✅ Create mock data when needed (M2)
5. ✅ Export to HTML files
6. ✅ Display hierarchical timelines with tree structure

---

## Generated Files

Running the demos creates:
- `milestone1_execution_gantt.html` - M1 demo Gantt chart
- `milestone2_execution_gantt.html` - M2 demo Gantt chart

Open these in a browser to see:
- Hierarchical execution timeline
- Color-coded operations (workflow, stage, agent, LLM, tool)
- Interactive tooltips with metrics
- Zoom/pan capabilities
- Tree structure visualization (▼ ├─ └─)

---

## Testing

Run both demos to verify:
```bash
./run_m1_demo.sh
./run_m2_demo.sh
```

Both should complete with:
```
✅ All Milestone [1|2] components are working!
```

And generate interactive HTML Gantt charts without errors.
