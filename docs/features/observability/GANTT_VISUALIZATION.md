# Hierarchical Gantt Chart Visualization

Visualize any execution trace as an interactive hierarchical Gantt chart showing the complete timeline of workflow → stages → agents → LLM calls → tool executions.

## Features

- **Hierarchical tree structure** with `▼ ├─ └─` characters showing parent-child relationships
- **Color-coded operations** (workflow=blue, stage=green, agent=orange, LLM=red, tool=yellow)
- **Interactive tooltips** with tokens, cost, duration, and metadata
- **Zoom & pan** to explore complex traces
- **Export to PNG** for documentation
- **Works with any execution trace** from the observability database

## Quick Start

### Visualize Latest Workflow

```bash
python -m src.observability.visualize_trace --latest
```

### Visualize Specific Workflow

```bash
python -m src.observability.visualize_trace <workflow-id>
```

### Visualize from JSON File

```bash
# Export trace to JSON
python examples/export_waterfall.py <workflow-id> > trace.json

# Visualize
python -m src.observability.visualize_trace --file trace.json
```

## Command-Line Options

```bash
python -m src.observability.visualize_trace [OPTIONS] [WORKFLOW_ID]

Options:
  --latest, -l          Visualize latest workflow execution
  --file FILE, -f FILE  Load trace from JSON file
  --output FILE, -o FILE  Output HTML file path
  --no-tree             Disable tree structure characters
  --no-open             Don't auto-open browser
```

## Programmatic Usage

```python
from src.observability.visualize_trace import visualize_trace, create_hierarchical_gantt
from examples.export_waterfall import export_waterfall_trace

# Get trace data
trace = export_waterfall_trace(workflow_id)

# Create visualization
fig = visualize_trace(
    trace,
    output_file="my_trace.html",
    show_tree_lines=True,
    auto_open=True
)

# Or for more control
fig = create_hierarchical_gantt(
    trace,
    title="Custom Title",
    show_tree_lines=True,
    output_file="custom.html"
)
fig.show()
```

## Integration with Demos

All demo scripts automatically generate Gantt charts:

### Milestone 1 Demo

```bash
python examples/milestone1_demo.py
# Creates: milestone1_execution_gantt.html
```

### Milestone 2 Demo

```bash
python examples/milestone2_demo.py
# Creates: milestone2_execution_gantt.html
```

### Workflow Execution

```bash
python examples/run_workflow.py configs/workflows/simple_research.yaml
# Creates: simple_research_gantt.html
# Auto-opens in browser
```

### Multi-Agent Example

```bash
python examples/visualize_multi_agent.py
# Creates: multi_agent_gantt.html
# Shows 3 agents running in parallel
```

## Example Visualization

```
▼ Market Analysis Workflow           ├─────────────────────────────┤
  ├─ ▼ Analysis Stage                ├────────────────────────────┤
     ├─ ▼ research_agent             ├──────────┤
     │  ├─ ollama/llama3.2:3b         ├────┤
     │  ├─ WebScraper                     ├──┤
     │  └─ ollama/llama3.2:3b                 ├─┤
     ├─ ▼ analysis_agent                  ├────────────┤
     │  ├─ ollama/llama3.2:3b              ├─────┤
     │  ├─ Calculator                          ├┤
     │  └─ ollama/llama3.2:3b                   ├────┤
     └─ ▼ synthesis_agent                         ├─────────┤
        ├─ ollama/llama3.2:3b                      ├───┤
        ├─ FileWriter                                  ├┤
        └─ ollama/llama3.2:3b                           ├─┤
```

## Chart Interpretation

### Colors

- **Blue** = Workflow (top-level)
- **Green** = Stage (grouping of agents)
- **Orange** = Agent (autonomous execution unit)
- **Red** = LLM calls (model inference)
- **Yellow** = Tool executions (external operations)

### Hierarchy

- **▼** = Expandable node with children
- **├─** = Middle child in tree
- **└─** = Last child in tree
- **│** = Continuation line

### Timeline

- **X-axis** = Time in seconds from workflow start
- **Bar length** = Operation duration
- **Bar position** = Start time

### Hover Tooltips

Each bar shows:
- Operation name and type
- Duration in seconds
- Status (success/failed/running)
- Tokens used (for LLM calls)
- Cost (for LLM calls)
- Tool name and parameters (for tools)

## Use Cases

### 1. Performance Optimization

Identify bottlenecks by finding the longest bars:
- LLM calls taking too long?
- Tool executions blocking progress?
- Unnecessary sequential operations?

### 2. Multi-Agent Analysis

For Milestone 3 workflows:
- Which agents run in parallel?
- Which agent is the bottleneck?
- How much speedup from parallelism?

### 3. Cost Attribution

Hover over LLM calls to see:
- Token usage per call
- Cost per operation
- Total workflow cost breakdown

### 4. Debugging Failures

Filter by status to find:
- Which operation failed?
- What was the error?
- What ran before the failure?

### 5. Documentation

Export charts as PNG to:
- Document workflow execution
- Share performance analysis
- Create architecture diagrams

## Trace Data Format

The visualizer accepts hierarchical trace data:

```json
{
  "id": "workflow-123",
  "name": "Workflow Name",
  "type": "workflow|stage|agent|llm|tool",
  "start": "2026-01-26T10:00:00Z",
  "end": "2026-01-26T10:00:05Z",
  "duration": 5.0,
  "status": "completed",
  "metadata": {
    "total_tokens": 1000,
    "total_cost_usd": 0.002
  },
  "children": [...]
}
```

This format is automatically generated by:
- `export_waterfall_trace(workflow_id)` from database
- Demo scripts during execution
- Custom trace generators

## Requirements

```bash
pip install plotly
```

Optional for database access:
```bash
pip install sqlmodel
```

## Browser Support

Works in all modern browsers:
- Chrome/Edge (recommended)
- Firefox
- Safari

## File Size

- Small workflows (<10 agents): ~500KB
- Medium workflows (10-50 agents): ~2MB
- Large workflows (50+ agents): ~5-10MB

For very large workflows, consider filtering or collapsing sections.

## Troubleshooting

### "Plotly not installed"

```bash
pip install plotly
```

### "No workflow executions found"

Run a demo first:
```bash
python examples/milestone2_demo.py
```

### "Could not export trace"

Ensure workflow exists:
```bash
sqlite3 workflow_execution.db "SELECT id, workflow_name FROM workflow_executions"
```

### Chart not opening in browser

Manually open the HTML file:
```bash
open multi_agent_gantt.html  # macOS
xdg-open multi_agent_gantt.html  # Linux
start multi_agent_gantt.html  # Windows
```

## Advanced Usage

### Custom Styling

Modify `src/observability/visualize_trace.py` to change:
- Color scheme (line 47-53)
- Height calculation (line 80)
- Font and margins (line 102-103)

### Filtering

Filter operations by type before visualization:
```python
def filter_trace(trace, types=['agent', 'llm']):
    """Keep only specified operation types"""
    filtered = trace.copy()
    filtered['children'] = [
        c for c in trace.get('children', [])
        if c['type'] in types
    ]
    return filtered

trace = export_waterfall_trace(workflow_id)
filtered = filter_trace(trace, ['agent', 'llm'])
visualize_trace(filtered)
```

### Comparison

Compare multiple workflows:
```python
traces = [
    export_waterfall_trace(id1),
    export_waterfall_trace(id2)
]

for i, trace in enumerate(traces):
    visualize_trace(trace, output_file=f"comparison_{i}.html")
```

## Related Tools

- `examples/export_waterfall.py` - Export trace data
- `examples/show_waterfall_format.py` - Show trace format
- `src/observability/console.py` - Console visualization
- `examples/query_trace.py` - Query execution data

## References

- Inspired by Chrome DevTools Network Timeline
- Similar to Jaeger/Zipkin distributed tracing
- Plotly timeline documentation: https://plotly.com/python/gantt/
