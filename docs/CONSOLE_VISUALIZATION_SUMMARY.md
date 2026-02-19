# Console Visualization Design - Summary

## Overview

This document provides a high-level summary of the UI/UX design for Rich console visualization of workflow traces. For detailed information, refer to the companion documents.

---

## Documentation Structure

### 1. Design Document
**File**: `/home/shinelay/meta-autonomous-framework/docs/CONSOLE_VISUALIZATION_DESIGN.md`

**Contents**:
- Detailed UI/UX recommendations for each verbosity level
- Color scheme and icon specifications
- Layout and hierarchical formatting approach
- Real-time update strategy using Rich's Live feature
- Edge case handling strategies
- Accessibility considerations

**Use When**: You need to understand the design philosophy, make design decisions, or extend the visualization system.

### 2. Reference Implementation
**File**: `/home/shinelay/meta-autonomous-framework/docs/CONSOLE_VISUALIZATION_REFERENCE.md`

**Contents**:
- Ready-to-use code snippets and patterns
- Constants and configuration values
- Enhanced formatting utilities
- Tree building patterns for different verbosity levels
- Production-ready streaming visualizer with optimizations
- Performance optimization techniques
- Testing utilities and mock factories

**Use When**: You're implementing new features, optimizing performance, or writing tests.

### 3. Visual Examples
**File**: `/home/shinelay/meta-autonomous-framework/docs/CONSOLE_VISUALIZATION_EXAMPLES.md`

**Contents**:
- Real-world output examples for all scenarios
- Examples for each verbosity level
- Streaming update demonstrations
- Error state visualizations
- Edge case handling examples
- Terminal width adaptations

**Use When**: You need to see what the output should look like, communicate with stakeholders, or validate implementations.

---

## Quick Reference

### Verbosity Levels

| Level | Purpose | Shows | Best For |
|-------|---------|-------|----------|
| **Minimal** | Quick status overview | Workflow + Stages | CI/CD, monitoring dashboards |
| **Standard** | Interactive development | Workflow + Stages + Agents | Default development, debugging |
| **Verbose** | Complete execution trace | Everything including LLM/Tool calls | Performance analysis, deep debugging |

### Color Scheme

```python
# Status Colors
"success"   → green
"failed"    → red
"running"   → yellow
"timeout"   → red
"pending"   → cyan

# Hierarchy Colors
"workflow"  → bold cyan
"stage"     → bold yellow
"agent"     → green
"llm"       → blue
"tool"      → magenta
```

### Status Icons

```python
✓  Success/Completed
✗  Failed
⏳  Running
⌛  Timeout
⏸  Paused/Halted
⋯  Pending
?  Unknown
```

### Performance Guidelines

```python
# Refresh Rates (updates per second)
Fast:    8 FPS  # Active development
Normal:  4 FPS  # Default
Slow:    2 FPS  # Long-running workflows

# Poll Intervals (seconds)
Fast:    0.1s   # Active development
Normal:  0.25s  # Default
Slow:    1.0s   # Long-running workflows
```

---

## Implementation Checklist

### Phase 1: Basic Visualization
- [ ] Implement status color and icon mapping
- [ ] Create basic tree builder for minimal mode
- [ ] Add duration formatting utilities
- [ ] Implement basic panel wrapper
- [ ] Write unit tests for formatters

### Phase 2: Standard Mode
- [ ] Extend tree builder for agent display
- [ ] Add token and cost formatting
- [ ] Implement synthesis/collaboration display
- [ ] Add responsive width adaptation
- [ ] Write integration tests

### Phase 3: Verbose Mode
- [ ] Add LLM call display
- [ ] Add tool execution display
- [ ] Implement detailed metadata display
- [ ] Add vote/decision display
- [ ] Test with complex workflows

### Phase 4: Real-Time Streaming
- [ ] Implement Live-based streaming visualizer
- [ ] Add database query optimization
- [ ] Implement state change detection
- [ ] Add error handling and recovery
- [ ] Performance test with long-running workflows

### Phase 5: Edge Cases & Polish
- [ ] Implement name truncation with path awareness
- [ ] Add depth limiting for deep nesting
- [ ] Handle very large numbers
- [ ] Add Unicode fallback for limited terminals
- [ ] Implement accessibility features

---

## Key Design Principles

### 1. Visual Hierarchy
- Use **color intensity** to show importance (bold for higher levels)
- Use **indentation** to show parent-child relationships
- Use **consistent spacing** for readability
- Use **tree characters** (├─ └─) for clear structure

### 2. Information Density
- **Minimal mode**: Status at a glance, ~5 lines per workflow
- **Standard mode**: Actionable information, ~15-20 lines per workflow
- **Verbose mode**: Complete trace, unlimited depth

### 3. Real-Time Responsiveness
- **Target latency**: < 250ms update lag
- **Smooth updates**: 4 FPS default refresh rate
- **Efficient polling**: Database query optimization
- **State caching**: Avoid unnecessary re-renders

### 4. Error Communication
- Show **inline errors** at the point of failure
- Use **color coding** (red) for immediate recognition
- Include **error preview** (first 50 chars)
- Provide **context** (which agent, which stage)

### 5. Accessibility
- **Never rely on color alone** - always include icons and text
- **Support screen readers** with meaningful text alternatives
- **Provide high contrast mode** option
- **Support Unicode fallback** for limited terminals

---

## Integration Points

### Current Codebase Integration

The design integrates with existing code at these points:

```python
# Existing Models
from temper_ai.observability.models import (
    WorkflowExecution,    # Top-level workflow
    StageExecution,       # Workflow stages
    AgentExecution,       # Agent executions
    LLMCall,             # LLM call details
    ToolExecution,       # Tool execution details
)

# Existing Database
from temper_ai.observability.database import get_session

# Existing Formatters
from temper_ai.observability.formatters import (
    format_duration,
    format_tokens,
    format_cost,
    status_to_color,
    status_to_icon,
)

# Existing Console Visualizer
from temper_ai.observability.console import (
    WorkflowVisualizer,      # Static display
    StreamingVisualizer,     # Real-time streaming
)
```

### Usage Examples

**Static Visualization**:
```python
from temper_ai.observability.console import WorkflowVisualizer
from temper_ai.observability.database import get_session
from temper_ai.observability.models import WorkflowExecution

with get_session() as session:
    workflow = session.query(WorkflowExecution).filter_by(
        id="wf-001"
    ).first()

    visualizer = WorkflowVisualizer(verbosity="standard")
    visualizer.display_execution(workflow)
```

**Real-Time Streaming**:
```python
from temper_ai.observability.console import StreamingVisualizer

# Monitor workflow in real-time
with StreamingVisualizer("wf-001", verbosity="verbose") as viz:
    # Workflow executes...
    # Display updates automatically
    pass
```

**Batch Monitoring**:
```python
from temper_ai.observability.console import BatchStreamingVisualizer

# Monitor multiple workflows
visualizer = BatchStreamingVisualizer([
    "wf-001",
    "wf-002",
    "wf-003",
])
visualizer.start()
```

---

## Performance Considerations

### Database Optimization

```python
# Bad: N+1 query problem
workflow = session.query(WorkflowExecution).get(workflow_id)
for stage in workflow.stages:              # Query 1
    for agent in stage.agents:             # Query 2 per stage
        for call in agent.llm_calls:       # Query 3 per agent
            process(call)

# Good: Single query with eager loading
workflow = session.query(WorkflowExecution).options(
    joinedload(WorkflowExecution.stages)
    .joinedload(StageExecution.agents)
    .joinedload(AgentExecution.llm_calls)
).filter_by(id=workflow_id).first()
```

### Update Optimization

```python
# Bad: Rebuild entire tree every update
while workflow.status == "running":
    tree = build_full_tree(workflow)  # Expensive!
    live.update(tree)
    time.sleep(0.1)

# Good: Only update when state changes
last_hash = None
while workflow.status == "running":
    current_hash = hash_workflow_state(workflow)
    if current_hash != last_hash:
        tree = build_full_tree(workflow)
        live.update(tree)
        last_hash = current_hash
    time.sleep(0.25)
```

### Memory Management

```python
# Limit tree depth to prevent memory bloat
MAX_DEPTH = 5

# Implement pagination for very large workflows
def create_tree_paginated(workflow, page=1, page_size=20):
    start = (page - 1) * page_size
    end = start + page_size
    return create_tree(workflow.stages[start:end])
```

---

## Testing Strategy

### Unit Tests
```python
# Test formatters
def test_format_duration():
    assert format_duration(0.15) == "150ms"
    assert format_duration(65) == "1m 5s"

# Test tree builders
def test_minimal_tree_builder():
    workflow = create_mock_workflow()
    builder = TreeBuilder(verbosity="minimal")
    tree = builder.build(workflow)
    assert tree is not None
```

### Integration Tests
```python
# Test with real database
def test_streaming_visualizer_integration():
    with test_database() as db:
        workflow = create_test_workflow(db)
        with StreamingVisualizer(workflow.id) as viz:
            assert viz.live is not None
            time.sleep(1)
            assert viz.update_count > 0
```

### Visual Tests
```python
# Capture output for visual regression testing
def test_output_format():
    workflow = create_mock_workflow()
    output = capture_console_output(visualize, workflow)
    assert "Workflow:" in output
    assert "✓" in output or "✗" in output
```

---

## Common Patterns

### Pattern 1: Custom Metrics Display

```python
def format_custom_metrics(workflow):
    """Add custom metrics to summary."""
    base_summary = format_standard_summary(workflow)

    # Add custom metrics
    custom_metrics = [
        f"Cache hits: {workflow.metadata.get('cache_hits', 0)}",
        f"API calls: {workflow.metadata.get('api_calls', 0)}",
    ]

    return f"{base_summary} | {' | '.join(custom_metrics)}"
```

### Pattern 2: Conditional Display

```python
def should_display_details(node, verbosity):
    """Determine whether to show details for a node."""
    if verbosity == "minimal":
        return False
    elif verbosity == "standard":
        return node.type in ["workflow", "stage", "agent"]
    else:  # verbose
        return True
```

### Pattern 3: Progressive Disclosure

```python
class ExpandableTreeBuilder:
    """Tree builder with expand/collapse support."""

    def __init__(self):
        self.expanded_nodes = set()

    def toggle_node(self, node_id):
        """Toggle node expansion state."""
        if node_id in self.expanded_nodes:
            self.expanded_nodes.remove(node_id)
        else:
            self.expanded_nodes.add(node_id)

    def build(self, workflow):
        """Build tree with current expansion state."""
        # Build based on expanded_nodes set
        pass
```

---

## Future Enhancements

### Planned Features

1. **Interactive Mode**
   - Keyboard navigation (↑↓ to navigate, Enter to expand/collapse)
   - Search/filter functionality
   - Jump to error locations

2. **Export Options**
   - Export to HTML with interactive JavaScript
   - Export to PDF for reports
   - Export to JSON for external analysis

3. **Comparison Mode**
   - Side-by-side comparison of two workflow executions
   - Diff highlighting for changed values
   - Performance regression detection

4. **Advanced Filtering**
   - Show only failed agents
   - Filter by cost threshold
   - Filter by duration threshold
   - Custom filter expressions

5. **Metrics Dashboard**
   - Real-time metrics charts
   - Cost tracking over time
   - Token usage trends
   - Performance heat maps

---

## Troubleshooting

### Common Issues

**Issue**: Terminal displays broken box characters
```
Solution: Ensure terminal supports UTF-8 encoding
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
```

**Issue**: Colors not displaying
```
Solution: Check TERM environment variable
export TERM=xterm-256color
```

**Issue**: Slow updates
```
Solution: Reduce refresh rate or increase poll interval
visualizer = StreamingVisualizer(
    workflow_id,
    poll_interval=1.0,  # Increase from 0.25s
    refresh_rate=2      # Decrease from 4
)
```

**Issue**: Out of memory with large workflows
```
Solution: Use depth limiting
builder = TreeBuilder(verbosity="standard", max_depth=3)
```

---

## Support and Contribution

### Getting Help

1. **Documentation**: Start with the design and reference docs
2. **Examples**: Check the examples document for visual patterns
3. **Tests**: Look at test files for usage examples
4. **Code**: Review existing implementation in `temper_ai/observability/console.py`

### Contributing

When contributing visualization features:

1. Follow the existing color and icon scheme
2. Maintain consistency across verbosity levels
3. Add tests for new formatters
4. Update examples document with new patterns
5. Consider accessibility in all designs

### Code Style

```python
# Good: Clear, documented, testable
def format_agent_label(agent: AgentExecution) -> str:
    """
    Format agent node label with metrics.

    Args:
        agent: Agent execution model

    Returns:
        Rich-formatted label string
    """
    return f"[green]Agent: {agent.name}[/] ({format_duration(agent.duration)})"

# Bad: Unclear, no docs, hard to test
def fmt(a):
    return f"[green]{a.name}[/] ({a.duration}s)"
```

---

## Summary

This console visualization design provides:

✅ **Three clear verbosity levels** for different use cases
✅ **Consistent visual language** with colors and icons
✅ **Real-time streaming** with optimized performance
✅ **Comprehensive error handling** for production use
✅ **Accessibility support** for diverse users
✅ **Responsive layouts** for different terminal widths
✅ **Production-ready code** with tests and examples

The design is fully compatible with the existing codebase and leverages Rich library's powerful features while maintaining simplicity and usability.

---

## Related Files

**Primary Implementation**:
- `/home/shinelay/meta-autonomous-framework/temper_ai/observability/console.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/observability/formatters.py`
- `/home/shinelay/meta-autonomous-framework/temper_ai/observability/visualize_trace.py`

**Models**:
- `/home/shinelay/meta-autonomous-framework/temper_ai/observability/models.py`

**Tests**:
- `/home/shinelay/meta-autonomous-framework/tests/test_observability/test_console.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_observability/test_console_streaming.py`
- `/home/shinelay/meta-autonomous-framework/tests/test_observability/test_visualize_trace.py`

**Examples**:
- `/home/shinelay/meta-autonomous-framework/examples/query_trace.py`

**Documentation**:
- This summary document
- `CONSOLE_VISUALIZATION_DESIGN.md` - Detailed design specifications
- `CONSOLE_VISUALIZATION_REFERENCE.md` - Code reference and patterns
- `CONSOLE_VISUALIZATION_EXAMPLES.md` - Visual examples and mockups
