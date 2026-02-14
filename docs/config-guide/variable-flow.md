# Variable Flow

How data moves through the 3-layer hierarchy at runtime.

## Overview

```
Input YAML  -->  Workflow inputs  -->  Stage inputs (Jinja2)  -->  Agent prompt (Jinja2)
                                                                        |
                                                                   LLM response
                                                                        |
                                       Stage outputs  -->  Workflow outputs
                                             |
                               Next stage (via depends_on) gets prior outputs
```

## Layer by Layer

### 1. Input File -> Workflow

The input YAML provides values for `workflow.inputs.required`:

```yaml
# examples/research_input.yaml
topic: "AI in Healthcare"
focus_areas: ["diagnosis", "drug discovery"]
```

These become available as `workflow.inputs.*` in stage references.

### 2. Workflow -> Stage

Stage references use Jinja2 to pass workflow inputs:

```yaml
# In workflow config
stages:
  - name: research
    stage_ref: configs/stages/research_stage.yaml
    inputs:
      topic: "{{ workflow.inputs.topic }}"
      depth: "{{ workflow.inputs.depth | default('medium') }}"
```

### 3. Stage -> Agent

Stage inputs populate the agent's prompt template variables:

```yaml
# In agent config
prompt:
  inline: |
    You are a research analyst.
    Topic: {{ topic }}          # <-- comes from stage inputs
    Depth: {{ depth }}
```

### 4. Agent -> Stage Output

The agent's LLM response becomes the stage output. For multi-agent stages, outputs are synthesized based on the collaboration strategy.

### 5. Stage -> Next Stage

When a stage depends on a prior stage, the prior stage's output is available:

```yaml
# In workflow config
stages:
  - name: research
    stage_ref: configs/stages/research.yaml

  - name: analysis
    stage_ref: configs/stages/analysis.yaml
    depends_on: [research]
    # analysis stage gets research outputs via stage_outputs
```

In the analysis agent's prompt, prior outputs are available via `stage_outputs`:

```yaml
# In analysis agent config
prompt:
  inline: |
    Prior research findings:
    {{ stage_outputs.research }}

    Now analyze these findings...
```

### 6. Stage -> Workflow Output

Workflow outputs map stage results:

```yaml
outputs:
  - name: final_results
    source: research.insights    # stage_name.field_name
```

## Multi-Round Variables

In stages using `multi_round` collaboration, additional variables are auto-injected into agent prompts on re-invocation:

| Variable | Type | Description |
|----------|------|-------------|
| `dialogue_history` | list | Prior round outputs (full or windowed) |
| `round_number` | int | Current round (0-indexed) |
| `max_rounds` | int | Max rounds configured |
| `agent_role` | string | Role assigned in collaboration config |

### Dialogue History Format

Each entry in `dialogue_history`:

```python
{
    "round": 0,
    "agent": "optimist",
    "output": "I believe we should...",
    "confidence": 0.85
}
```

### Context Strategies

The `context_strategy` config controls what history agents see:

| Strategy | Behavior |
|----------|----------|
| `full` | All prior rounds included |
| `recent` | Only last N rounds (controlled by `context_window_size`) |
| `relevant` | Semantically relevant rounds |

## Condition Evaluation Context

Conditional stages and loop-back stages use Jinja2 expressions evaluated against the workflow state. The condition context includes all non-infrastructure state fields.

### Available Variables

| Variable | Type | Description |
|----------|------|-------------|
| `stage_outputs` | dict | Outputs from all completed stages |
| `stage_outputs.<name>.stage_status` | string | `"success"`, `"failed"`, or `"degraded"` |
| `stage_loop_counts` | dict | Current loop iteration count per stage |
| Workflow input variables | any | All inputs passed to the workflow |

### Filtered Variables

Infrastructure keys are automatically filtered from the condition context to prevent errors with non-serializable objects:
`tracker`, `tool_registry`, `config_loader`, `visualizer`, `show_details`, `detail_console`, `stream_callback`, `tool_executor`

### Condition Syntax

Conditions use the same Jinja2 `ImmutableSandboxedEnvironment` as prompt rendering. Missing keys return a silent undefined (falsy) instead of raising errors.

```yaml
# Check stage status
condition: "{{ stage_outputs.test.stage_status == 'failed' }}"

# Check with in operator
condition: "{{ stage_outputs.test.stage_status in ['failed', 'degraded'] }}"

# Check nested field with safe access
condition: "{{ stage_outputs.test.get('errors', [])|length > 0 }}"

# Boolean variable
skip_if: "{{ skip_validation }}"
```

### Loop Counter Variable

The `stage_loop_counts` dict tracks how many times each looping stage has iterated. This is managed automatically by the loop gate node and is available in conditions:

```yaml
# Example: stage_loop_counts = {"fix": 2} means fix has looped twice
```

## Environment Variable Substitution

Config values can reference environment variables:

```yaml
# Direct substitution
inference:
  model: ${LLM_MODEL}

# Secret references
inference:
  api_key_ref: "${env:OPENAI_API_KEY}"     # env var
  api_key_ref: "${vault:path/to/secret}"   # HashiCorp Vault
  api_key_ref: "${aws:secret-id}"          # AWS Secrets Manager
```
