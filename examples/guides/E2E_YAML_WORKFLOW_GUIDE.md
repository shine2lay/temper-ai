# End-to-End YAML Workflow Guide

**Date**: 2026-01-27
**Purpose**: Complete guide to running M3 workflows from YAML config → Execution → Output

---

## Overview

This guide demonstrates the **complete M3 pipeline**:

1. 📄 **YAML Configuration** - Define workflow
2. 🚀 **Execution** - Run with LLM agents
3. 📊 **Output** - Structured JSON results

---

## Complete E2E Flow

### Step 1: YAML Configuration

#### **Workflow Config**: `configs/workflows/e2e_simple_debate.yaml`

```yaml
workflow:
  name: e2e_simple_debate
  description: "Simple multi-agent debate workflow (E2E demo)"
  version: "1.0"

  # LLM provider
  llm_provider:
    provider: ollama
    base_url: http://localhost:11434
    model: llama3.2:3b
    temperature: 0.7
    max_tokens: 300

  # Workflow stages
  stages:
    - name: simple_debate
      config_path: configs/stages/e2e_simple_debate_stage.yaml
      inputs:
        scenario: "{{ workflow.inputs.scenario }}"
        options: "{{ workflow.inputs.options }}"
        context: "{{ workflow.inputs.context }}"

  # Workflow inputs
  inputs:
    required:
      - scenario
      - options
    optional:
      - context

  # Workflow outputs
  outputs:
    - name: final_decision
      source: simple_debate.decision
    - name: agent_perspectives
      source: simple_debate.agent_outputs
    - name: execution_trace
      fields:
        - agents_executed
        - total_tokens
        - total_latency_ms
```

**Key Features**:
- `llm_provider`: Configures LLM (Ollama, OpenAI, etc.)
- `stages`: References stage config files
- `inputs`: Template variables like `{{ workflow.inputs.X }}`
- `outputs`: Structured output schema

---

#### **Stage Config**: `configs/stages/e2e_simple_debate_stage.yaml`

```yaml
stage:
  name: e2e_simple_debate_stage
  description: "Simple debate stage with 3 LLM agents"
  version: "1.0"

  type: multi_agent_consensus

  # Agent configuration
  agents:
    - name: product_manager
      role: Product Manager
      persona: "You're business-focused and care about market timing,
                competitive advantage, and revenue."
      llm_config:
        temperature: 0.7
        max_tokens: 300

    - name: engineering_lead
      role: Engineering Lead
      persona: "You're technical and quality-focused. You care about
                code stability, security, and maintainability."
      llm_config:
        temperature: 0.7
        max_tokens: 300

    - name: data_analyst
      role: Data Analyst
      persona: "You're data-driven and analytical. You prefer
                evidence-based decisions and controlled experiments."
      llm_config:
        temperature: 0.7
        max_tokens: 300

  # Collaboration strategy
  collaboration:
    strategy: consensus
    config:
      threshold: 0.5  # Simple majority
      require_unanimous: false
      tie_breaker: confidence

  # Error handling
  error_handling:
    min_successful_agents: 2  # Need 2/3
    on_agent_failure: continue
    on_stage_failure: halt
```

**Key Features**:
- `agents`: Each agent has name, role, persona, LLM config
- `collaboration.strategy`: consensus | debate_and_synthesize | merit_weighted
- `error_handling`: Fault tolerance settings

---

### Step 2: Execution

Run the E2E workflow:

```bash
python3 examples/e2e_yaml_debate.py
```

**Execution Flow**:

```
1. Load YAML config
   ├─ Parse workflow.yaml
   ├─ Load stage.yaml
   └─ Initialize LLM provider

2. Execute workflow
   └─ For each stage:
      ├─ Execute agents
      │  ├─ product_manager (LLM call #1)
      │  ├─ engineering_lead (LLM call #2)
      │  └─ data_analyst (LLM call #3)
      └─ Synthesize results
         └─ Apply consensus strategy

3. Generate output
   ├─ Collect agent outputs
   ├─ Calculate metrics
   └─ Save JSON file
```

---

### Step 3: Output

#### **Console Output**

```
Loading config: configs/workflows/e2e_simple_debate.yaml
✓ Config loaded: e2e_simple_debate
  Description: Simple multi-agent debate workflow (E2E demo)

╭────────────────────────────────────────────────────────────╮
│ M3 End-to-End YAML Workflow                                │
│ Workflow: e2e_simple_debate                                │
│ Description: Simple multi-agent debate workflow (E2E demo) │
╰────────────────────────────────────────────────────────────╯

Initializing LLM provider:
  Provider: ollama
  Model: llama3.2:3b
  Base URL: http://localhost:11434
  Temperature: 0.7

✓ LLM ready

Loading stage config: configs/stages/e2e_simple_debate_stage.yaml
✓ Stage loaded: e2e_simple_debate_stage

================================================================================
Executing Stage: e2e_simple_debate_stage
================================================================================

🤖 Executing agent: product_manager (Product Manager)
  ✓ Decision: Wait 1 Month
  Reasoning: We should wait to address bugs and iterate based on feedback...
  Latency: 1068ms | Tokens: 402

🤖 Executing agent: engineering_lead (Engineering Lead)
  ✓ Decision: Wait 1 Month
  Reasoning: Delaying allows for thorough testing and bug fixing...
  Latency: 1093ms | Tokens: 403

🤖 Executing agent: data_analyst (Data Analyst)
  ✓ Decision: Launch Beta
  Reasoning: Controlled environment allows for bug fixing and iteration...
  Latency: 652ms | Tokens: 363

Synthesizing agent outputs...

╭────────────────────────────╮
│ Synthesis Complete         │
│                            │
│ Decision: Wait 1 Month     │
│ Confidence: 67%            │
│ Method: consensus          │
╰────────────────────────────╯

                Vote Distribution
┏━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┓
┃ Option        ┃ Votes ┃ Percentage ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━┩
│ Wait 1 Month  │     2 │      66.7% │
│ Launch Beta   │     1 │      33.3% │
└───────────────┴───────┴────────────┘

Reasoning: Consensus reached: 'Wait 1 Month' with 66.7% support (2/3 agents).

================================================================================
Generating Workflow Output
================================================================================

╭───────────────────────────╮
│ Workflow Complete!        │
│                           │
│ Final Decision: Wait 1    │
│ Month                     │
│ Confidence: 67%           │
│ Total Agents: 3           │
│ Total Tokens: 1168        │
│ Total Latency: 2813ms     │
╰───────────────────────────╯

✓ Output saved to: output_e2e_simple_debate_1769504039.json
```

---

#### **JSON Output File**: `output_e2e_simple_debate_1769504039.json`

```json
{
  "workflow_name": "e2e_simple_debate",
  "workflow_version": "1.0",
  "execution_timestamp": "2026-01-27 00:53:59",

  "stages": [
    {
      "stage_name": "e2e_simple_debate_stage",
      "stage_type": "multi_agent_consensus",

      "agents": [
        {
          "name": "product_manager",
          "role": "Product Manager",
          "decision": "Wait 1 Month",
          "reasoning": "We should wait to address bugs and iterate...",
          "confidence": 0.8,
          "latency_ms": 1068,
          "tokens": 402
        },
        {
          "name": "engineering_lead",
          "role": "Engineering Lead",
          "decision": "Wait 1 Month",
          "reasoning": "Delaying allows for thorough testing...",
          "confidence": 0.8,
          "latency_ms": 1093,
          "tokens": 403
        },
        {
          "name": "data_analyst",
          "role": "Data Analyst",
          "decision": "Launch Beta",
          "reasoning": "Controlled environment allows iteration...",
          "confidence": 0.8,
          "latency_ms": 652,
          "tokens": 363
        }
      ],

      "synthesis": {
        "decision": "Wait 1 Month",
        "confidence": 0.67,
        "method": "consensus",
        "votes": {
          "Wait 1 Month": 2,
          "Launch Beta": 1
        },
        "reasoning": "Consensus reached with 66.7% support"
      }
    }
  ],

  "final_decision": "Wait 1 Month",
  "final_confidence": 0.67,

  "metrics": {
    "total_agents_executed": 3,
    "total_tokens": 1168,
    "total_latency_ms": 2813,
    "stages_executed": 1
  }
}
```

**Output Structure**:
- **Workflow metadata**: Name, version, timestamp
- **Stages**: Complete stage execution trace
  - **Agents**: Each agent's decision, reasoning, metrics
  - **Synthesis**: Final consensus, votes, confidence
- **Final results**: Decision, confidence
- **Metrics**: Tokens, latency, count

---

## Key Features Demonstrated

### 1. **YAML-Driven Configuration**

✅ Declarative workflow definition
✅ Template variable substitution (`{{ workflow.inputs.X }}`)
✅ Modular stage configs
✅ Reusable components

### 2. **LLM Integration**

✅ Real LLM API calls (Ollama, OpenAI, etc.)
✅ Per-agent LLM configuration
✅ Persona-based prompting
✅ Structured output (JSON)

### 3. **Multi-Agent Execution**

✅ 3 agents with different perspectives
✅ Sequential execution
✅ Individual agent metrics (tokens, latency)
✅ Error handling and fallbacks

### 4. **Synthesis Strategy**

✅ Consensus voting (majority wins)
✅ Confidence calculation
✅ Vote distribution tracking
✅ Weak consensus detection

### 5. **Structured Output**

✅ JSON format
✅ Complete execution trace
✅ Per-agent details
✅ Aggregated metrics
✅ Timestamped results

---

## Usage

### Basic Usage

```bash
# Run E2E workflow
python3 examples/e2e_yaml_debate.py
```

### With Custom Inputs

Edit `examples/e2e_yaml_debate.py`:

```python
workflow_inputs = {
    'scenario': 'Your custom scenario',
    'options': ['Option A', 'Option B', 'Option C'],
    'context': 'Additional context...'
}
```

### Output Location

Output files are saved as:
```
output_<workflow_name>_<timestamp>.json
```

Example: `output_e2e_simple_debate_1769504039.json`

---

## File Structure

```
meta-autonomous-framework/
├── configs/
│   ├── workflows/
│   │   └── e2e_simple_debate.yaml       # Workflow config
│   └── stages/
│       └── e2e_simple_debate_stage.yaml  # Stage config
├── examples/
│   └── e2e_yaml_debate.py                # E2E runner script
└── output_*.json                          # Generated outputs
```

---

## Execution Metrics

**Performance** (3 agents, local LLM):
- Total execution time: ~2.8 seconds
- Per-agent latency: ~650-1100ms
- Total tokens: ~1168
- Stages executed: 1

**Cost** (if using paid LLM):
- At GPT-3.5 rates: ~$0.001-0.002
- At GPT-4 rates: ~$0.01-0.02
- Local Ollama: Free

---

## Customization

### Add More Agents

In `configs/stages/e2e_simple_debate_stage.yaml`:

```yaml
agents:
  - name: agent_4
    role: Security Expert
    persona: "You focus on security and compliance..."
    llm_config:
      temperature: 0.7
      max_tokens: 300
```

### Change Strategy

In `configs/stages/e2e_simple_debate_stage.yaml`:

```yaml
collaboration:
  strategy: debate_and_synthesize  # Multi-round debate
  config:
    max_rounds: 3
    convergence_threshold: 0.8
```

### Add Quality Gates

In `configs/stages/e2e_simple_debate_stage.yaml`:

```yaml
quality_gates:
  enabled: true
  min_confidence: 0.7
  min_findings: 5
  on_failure: escalate
```

### Use Different LLM

In `configs/workflows/e2e_simple_debate.yaml`:

```yaml
llm_provider:
  provider: openai  # or anthropic
  api_key: sk-...
  model: gpt-4
  temperature: 0.7
```

---

## Comparison: Standalone Demo vs E2E YAML

| Aspect | Standalone Demo | E2E YAML |
|--------|----------------|----------|
| **Configuration** | Hardcoded in Python | YAML files |
| **Workflow** | Python script | Declarative YAML |
| **Reusability** | Low (script-specific) | High (config-based) |
| **Modularity** | Monolithic | Stage-based |
| **Production** | Demo only | Production-ready |
| **Output** | Console only | JSON + Console |
| **Traceability** | Limited | Complete trace |

---

## Next Steps

### 1. **Extend the Workflow**

Add more stages:
```yaml
stages:
  - name: initial_analysis
    config_path: configs/stages/analysis_stage.yaml

  - name: debate
    config_path: configs/stages/debate_stage.yaml

  - name: final_decision
    config_path: configs/stages/decision_stage.yaml
```

### 2. **Integrate with Production**

```python
from examples.e2e_yaml_debate import YAMLWorkflowRunner

# Load workflow
runner = YAMLWorkflowRunner('configs/workflows/my_workflow.yaml')

# Run with inputs
output = runner.run({
    'scenario': request.scenario,
    'options': request.options
})

# Return to API
return JSONResponse(output)
```

### 3. **Add Monitoring**

```python
# Track metrics in observability platform
metrics.track({
    'workflow_name': output['workflow_name'],
    'latency_ms': output['metrics']['total_latency_ms'],
    'tokens': output['metrics']['total_tokens'],
    'confidence': output['final_confidence']
})
```

---

## Troubleshooting

### LLM Connection Failed

```
✗ LLM connection failed: Connection refused
```

**Solution**:
```bash
# Start Ollama
ollama serve

# Download model
ollama pull llama3.2:3b
```

### Config Not Found

```
✗ Config file not found: configs/workflows/...
```

**Solution**:
```bash
# Run from project root
cd /home/shinelay/meta-autonomous-framework
python3 examples/e2e_yaml_debate.py
```

### JSON Parsing Errors

```
⚠️ JSON parsing error for agent_name
```

**Cause**: Small LLM models sometimes generate imperfect JSON

**Solution**:
- Use larger model (llama3.2:7b or gpt-3.5-turbo)
- Increase max_tokens
- Add stricter prompt instructions

---

## Summary

The E2E YAML workflow demonstrates:

✅ **Complete pipeline**: Config → Execution → Output
✅ **Production-ready**: YAML-driven, modular, traceable
✅ **LLM-powered**: Real agent reasoning
✅ **Structured output**: JSON with full trace
✅ **M3 features**: Multi-agent, synthesis, metrics
✅ **Extensible**: Easy to customize and extend

---

## Related Files

- **E2E Runner**: `examples/e2e_yaml_debate.py`
- **Workflow Config**: `configs/workflows/e2e_simple_debate.yaml`
- **Stage Config**: `configs/stages/e2e_simple_debate_stage.yaml`
- **Output Example**: `output_e2e_simple_debate_*.json`
- **YAML Guide**: `M3_YAML_CONFIGS_GUIDE.md`

---

**M3 Status**: 16/16 tasks complete (100%)
**E2E Workflow**: Production-ready ✓
